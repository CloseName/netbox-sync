"""Explicitly confirmed reuse of legacy interfaces for managed ESXi objects."""

from dataclasses import dataclass

from .esxi_migration import (
    EsxiMigrationPlan,
    InterfaceMigrationClassification,
    ObjectMigrationClassification,
    _NetworkOwnership,
    _canonical_ip,
    _canonical_mac,
    _object_id,
    _serialized,
)
from .source_identity import (
    IDENTITY_SCHEMA_V2,
    V2_IDENTITY_MATCH,
    SourceIdentity,
    merge_original_name,
    merge_source_identities,
    source_identity_match_rank,
)


class EsxiInterfaceMigrationError(RuntimeError):
    """A confirmed interface migration failed closed before any write."""


@dataclass(frozen=True)
class _PendingMigration:
    kind: str
    interface: object
    changes: dict
    discovered_mac: str | None
    mac_record: object | None
    attach_mac: bool


def _identity(plan, kind, external_id):
    identity_kind = "host" if kind == "host" else "vm"
    return SourceIdentity(
        schema=IDENTITY_SCHEMA_V2,
        type="esxi",
        instance=plan.source_instance,
        kind=identity_kind,
        external_id=str(external_id),
    )


def _parent_endpoint(nb_api, kind):
    return nb_api.dcim.devices if kind == "host" else nb_api.virtualization.virtual_machines


def _interface_endpoint(nb_api, kind):
    return nb_api.dcim.interfaces if kind == "host" else nb_api.virtualization.interfaces


def _relation(kind):
    return "device" if kind == "host" else "virtual_machine"


def _assigned_type(kind):
    return "dcim.interface" if kind == "host" else "virtualization.vminterface"


def _custom_fields(record):
    return dict(getattr(record, "custom_fields", None) or {})


def _matches_expected_identity(record, identity):
    try:
        rank = source_identity_match_rank(_custom_fields(record), identity)
    except ValueError as exc:
        raise EsxiInterfaceMigrationError(f"Invalid parent identity metadata on id={record.id}") from exc
    return rank == V2_IDENTITY_MATCH


def _validate_parent(nb_api, plan, kind, item):
    if item.classification != ObjectMigrationClassification.MANAGED or len(item.candidates) != 1:
        raise EsxiInterfaceMigrationError("Interface migration requires one managed parent")
    parent_id = item.candidates[0].object_id
    endpoint = _parent_endpoint(nb_api, kind)
    parent = endpoint.get(id=parent_id)
    if parent is None:
        raise EsxiInterfaceMigrationError("Managed parent no longer exists")
    expected = _identity(plan, kind, item.external_id)
    matches = [record for record in endpoint.all() if _matches_expected_identity(record, expected)]
    if len(matches) != 1 or matches[0].id != parent_id:
        raise EsxiInterfaceMigrationError("Managed parent identity changed after preflight")
    data = _serialized(parent)
    if _object_id(data.get("cluster")) != plan.cluster_id:
        raise EsxiInterfaceMigrationError("Managed parent moved outside target")
    if kind == "host" and _object_id(data.get("site")) != plan.site_id:
        raise EsxiInterfaceMigrationError("Managed host moved outside target")
    return parent


def _selected_items(plan):
    selected = []
    for kind, parents in (
        ("host", plan.hosts),
        ("vm", plan.virtual_machines),
    ):
        for parent in parents:
            for item in parent.interfaces:
                if item.classification == (InterfaceMigrationClassification.SAFE_RENAME_OR_REUSE_CANDIDATE):
                    selected.append((kind, parent, item))
    return tuple(selected)


def _validate_candidate(ownership, kind, parent, item):
    if len(item.candidates) != 1:
        raise EsxiInterfaceMigrationError("Safe interface migration must have exactly one candidate")
    candidate = item.candidates[0]
    interface = ownership.by_id[kind].get(candidate.interface_id)
    if interface is None:
        raise EsxiInterfaceMigrationError("Interface candidate no longer exists")
    data = _serialized(interface)
    if (
        candidate.parent_id != parent.id
        or _object_id(data.get(_relation(kind))) != parent.id
        or str(getattr(interface, "name", "")) != candidate.interface_name
    ):
        raise EsxiInterfaceMigrationError("Interface candidate changed after preflight")
    current_ips, current_macs = ownership._current_network(  # pylint: disable=protected-access
        kind,
        interface,
    )
    ip_assignments, mac_assignments = ownership.current_assignments(
        kind,
        interface,
    )
    if (
        current_ips != candidate.current_ips
        or current_macs != candidate.current_macs
        or ip_assignments != candidate.current_ip_assignments
        or mac_assignments != candidate.current_mac_assignments
    ):
        raise EsxiInterfaceMigrationError("Interface network assignments changed after preflight")
    collisions = [
        other
        for other in ownership.owned_interfaces(kind, parent.id)
        if (other.id != interface.id and str(getattr(other, "name", "")).casefold() == item.discovered_name.casefold())
    ]
    if collisions:
        raise EsxiInterfaceMigrationError("Desired interface name is already used on the parent")
    return interface


def _validate_ips(nb_api, kind, interface, discovered_ips):
    expected_type = _assigned_type(kind)
    for record in nb_api.ipam.ip_addresses.all():
        data = _serialized(record)
        address = _canonical_ip(data.get("address"))
        if address not in discovered_ips:
            continue
        assigned_type = data.get("assigned_object_type")
        assigned_id = _object_id(data.get("assigned_object_id"))
        if assigned_type is None and assigned_id is None:
            continue
        if assigned_type != expected_type or assigned_id != interface.id:
            raise EsxiInterfaceMigrationError(f"Discovered IP {address} is owned by another interface")


def _matching_mac_records(nb_api, address):
    return [
        record
        for record in nb_api.dcim.mac_addresses.all()
        if _canonical_mac(_serialized(record).get("mac_address")) == address
    ]


def _validate_mac(nb_api, kind, interface, discovered_mac):
    if discovered_mac is None:
        return None, False
    records = _matching_mac_records(nb_api, discovered_mac)
    if len(records) > 1:
        raise EsxiInterfaceMigrationError(f"Discovered MAC {discovered_mac} is duplicated")
    if not records:
        return None, False
    record = records[0]
    data = _serialized(record)
    assigned_type = data.get("assigned_object_type")
    assigned_id = _object_id(data.get("assigned_object_id"))
    unassigned = assigned_type is None and assigned_id is None
    same_owner = assigned_type == _assigned_type(kind) and assigned_id == interface.id
    if not (unassigned or same_owner):
        raise EsxiInterfaceMigrationError(f"Discovered MAC {discovered_mac} is owned by another interface")
    primary_id = _object_id(_serialized(interface).get("primary_mac_address"))
    if primary_id is not None and primary_id != record.id:
        raise EsxiInterfaceMigrationError("Interface has a different primary MAC address")
    return record, unassigned


def _vm_interface_metadata(plan, parent_item, item, interface):
    if not item.discovered_external_id:
        raise EsxiInterfaceMigrationError("ESXi VM interface has no stable external id")
    identity = SourceIdentity(
        schema=IDENTITY_SCHEMA_V2,
        type="esxi",
        instance=plan.source_instance,
        kind="vm-nic",
        external_id=f"{parent_item.external_id}:{item.discovered_external_id}",
    )
    current = _custom_fields(interface)
    base = dict(current)
    if base.get("sync_identities") is None:
        base["sync_identities"] = []
    if base.get("sync_original_names") is None:
        base["sync_original_names"] = {}
    if not isinstance(base["sync_identities"], list):
        raise EsxiInterfaceMigrationError(f"Invalid interface identity metadata on id={interface.id}")
    if not isinstance(base["sync_original_names"], dict):
        raise EsxiInterfaceMigrationError(f"Invalid interface original-name metadata on id={interface.id}")
    for value in base["sync_identities"]:
        try:
            parsed = SourceIdentity.from_record(value)
        except ValueError as exc:
            raise EsxiInterfaceMigrationError(f"Invalid interface identity metadata on id={interface.id}") from exc
        if (
            parsed is not None
            and (
                parsed.type,
                parsed.instance,
                parsed.kind,
            )
            == (identity.type, identity.instance, identity.kind)
            and parsed != identity
        ):
            raise EsxiInterfaceMigrationError("Interface already has a different ESXi NIC identity")
    try:
        desired = dict(current)
        desired["sync_identities"] = merge_source_identities(base, identity)
        desired["sync_original_names"] = merge_original_name(
            base,
            identity,
            item.discovered_name,
        )
    except (TypeError, ValueError) as exc:
        raise EsxiInterfaceMigrationError(f"Invalid interface metadata on id={interface.id}") from exc
    return desired


def _preflight(nb_api, plan):
    ownership = _NetworkOwnership(nb_api)
    selected = _selected_items(plan)
    claims = [(kind, item.candidates[0].interface_id) for kind, _, item in selected if len(item.candidates) == 1]
    if len(claims) != len(selected) or len(set(claims)) != len(claims):
        raise EsxiInterfaceMigrationError("Migration plan contains a shared interface claim")
    pending = []
    for kind, parent_item, item in selected:
        parent = _validate_parent(nb_api, plan, kind, parent_item)
        interface = _validate_candidate(ownership, kind, parent, item)
        _validate_ips(nb_api, kind, interface, set(item.discovered_ips))
        mac_record, attach_mac = _validate_mac(
            nb_api,
            kind,
            interface,
            item.discovered_mac,
        )
        changes = {}
        if str(interface.name) != item.discovered_name:
            changes["name"] = item.discovered_name
        if kind == "vm":
            metadata = _vm_interface_metadata(
                plan,
                parent_item,
                item,
                interface,
            )
            if metadata != _custom_fields(interface):
                changes["custom_fields"] = metadata
        pending.append(
            _PendingMigration(
                kind=kind,
                interface=interface,
                changes=changes,
                discovered_mac=item.discovered_mac,
                mac_record=mac_record,
                attach_mac=attach_mac,
            )
        )
    return tuple(pending)


def apply_esxi_interface_migration(nb_api, plan, *, confirmed=False):
    """Reuse only safe legacy interfaces after a complete confirmed preflight."""

    if not isinstance(plan, EsxiMigrationPlan):
        raise TypeError("plan must be EsxiMigrationPlan")
    if not confirmed:
        raise EsxiInterfaceMigrationError("ESXi interface migration requires explicit confirmation")

    pending = _preflight(nb_api, plan)
    for migration in pending:
        mac_record = migration.mac_record
        if migration.discovered_mac and mac_record is None:
            mac_record = nb_api.dcim.mac_addresses.create(
                mac_address=migration.discovered_mac,
                assigned_object_type=_assigned_type(migration.kind),
                assigned_object_id=migration.interface.id,
            )
        elif migration.attach_mac:
            mac_record.update(
                {
                    "assigned_object_type": _assigned_type(migration.kind),
                    "assigned_object_id": migration.interface.id,
                }
            )

        changes = dict(migration.changes)
        if mac_record is not None and (
            _object_id(_serialized(migration.interface).get("primary_mac_address")) != mac_record.id
        ):
            changes["primary_mac_address"] = mac_record.id
        if changes:
            migration.interface.update(changes)
    return len(pending)
