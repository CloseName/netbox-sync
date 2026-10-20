"""Validate the complete VM network batch before reporting or writing."""

from .netbox_record_values import object_id as _object_id
from .interface_display import interface_display_name, validate_interface_names
import ipaddress
from .network_scopes import scope_key

from .netbox_vm_metadata import (
    find_vm_sync_identity_matches,
)

from .netbox_vm_interface_metadata import (
    MANAGED_VM_INTERFACE_CUSTOM_FIELDS,
    build_nic_custom_fields,
    find_nic_sync_identity_matches,
    nic_identity_source_id,
)


class VMNetworkApplyError(RuntimeError):
    """A VM network identity or ownership check prevents safe application."""


class ManagedMACConflict(VMNetworkApplyError):
    """Closed operator-facing context, separate from arbitrary exception text."""

    def __init__(self, vm, nic, mac, *, duplicate=False):
        self.vm_name = vm.original_name
        self.nic_name = nic.name
        self.mac = mac
        self.duplicate = duplicate
        super().__init__(
            f"Duplicate NetBox MAC {mac}" if duplicate else f"MAC {mac} already assigned to another interface"
        )


def _canonical_mac(value):
    if not value:
        return None

    return str(value).strip().upper()


def _usable_address(value):
    try:
        interface = ipaddress.ip_interface(str(value))
    except ValueError:
        return None

    ip = interface.ip

    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return None

    return str(interface)


def _assigned_object(record):
    data = record.serialize()

    return (
        data.get("assigned_object_type"),
        data.get("assigned_object_id"),
    )


def _find_vm(
    target_vms,
    discovered_vm,
):
    matches = find_vm_sync_identity_matches(target_vms, discovered_vm)

    if len(matches) != 1:
        raise VMNetworkApplyError(
            f"Expected exactly one NetBox VM " f"for {discovered_vm.source_id}; " f"found {len(matches)}"
        )

    return matches[0]


def _interface_match(
    existing_interfaces,
    vm,
    nic,
):
    identity_matches = find_nic_sync_identity_matches(
        existing_interfaces,
        vm,
        nic,
    )

    if len(identity_matches) > 1:
        raise VMNetworkApplyError(f"Duplicate NIC identity " f"{vm.source}:" f"{nic_identity_source_id(vm, nic)}")

    if len(identity_matches) == 1:
        return identity_matches[0]

    name_matches = [
        interface
        for interface in existing_interfaces
        if (interface.name.casefold() in (nic.name.casefold(), interface_display_name(vm, nic).casefold()))
    ]

    if name_matches:
        raise VMNetworkApplyError(
            f"NIC adoption candidate exists "
            f"without sync identity: "
            f"vm={vm.original_name!r} "
            f"nic={interface_display_name(vm, nic)!r}"
        )

    return None


def _desired_interface_changes(
    existing,
    vm,
    nic,
):
    current_custom_fields = dict(
        getattr(
            existing,
            "custom_fields",
            None,
        )
        or {}
    )

    desired_custom_fields = build_nic_custom_fields(
        vm,
        nic,
        current_custom_fields,
    )

    changes = {}

    if existing.name != interface_display_name(vm, nic):
        changes["name"] = interface_display_name(vm, nic)

    data = existing.serialize()

    if data.get("enabled") is not True:
        changes["enabled"] = True

    changed_cf = any(
        current_custom_fields.get(field) != desired_custom_fields.get(field)
        for field in MANAGED_VM_INTERFACE_CUSTOM_FIELDS
    )

    if changed_cf:
        changes["custom_fields"] = desired_custom_fields

    return (
        changes,
        desired_custom_fields,
    )


def _current_primary_mac_id(interface):
    if interface is None:
        return None

    return _object_id(interface.serialize().get("primary_mac_address"))


def _current_primary_ip_id(vm):
    return _object_id(vm.serialize().get("primary_ip4"))


def _primary_ip_belongs_to_vm(ip_record, interfaces_by_id, vm_id):
    if ip_record is None:
        return False
    assigned_type, assigned_id = _assigned_object(ip_record)
    if assigned_type != "virtualization.vminterface":
        return False
    interface = interfaces_by_id.get(_object_id(assigned_id))
    if interface is None:
        return False
    return _object_id(interface.serialize().get("virtual_machine")) == vm_id


def _check_vm_mac(existing, vm, nic, macs_by_address, discovered_macs):
    """Check MAC ownership, retaining VM-specific structured conflict details.

    Record discovery before validating NetBox ownership. A stable managed NIC may
    change primary MAC; the previous MAC record remains untouched.
    """
    mac_value = _canonical_mac(nic.mac_address)

    existing_mac = None

    if mac_value:
        discovered_macs.setdefault(
            mac_value,
            [],
        ).append(
            (
                vm.original_name,
                interface_display_name(vm, nic),
            )
        )

        mac_matches = macs_by_address.get(
            mac_value,
            [],
        )

        if len(mac_matches) > 1:
            raise ManagedMACConflict(vm, nic, mac_value, duplicate=True)

        if len(mac_matches) == 1:
            existing_mac = mac_matches[0]

            (
                assigned_type,
                assigned_id,
            ) = _assigned_object(existing_mac)

            allowed = assigned_type is None and assigned_id is None

            if existing is not None and assigned_type == "virtualization.vminterface" and assigned_id == existing.id:
                allowed = True

            if not allowed:
                raise ManagedMACConflict(vm, nic, mac_value)

        # The interface was matched by stable source/VM/NIC identity.
        # A changed MAC is a normal update. The desired MAC has already
        # passed assignment checks above. Keep the old MAC record and
        # its history; only switch this managed interface's primary.

    return mac_value, existing_mac


def _check_vm_ips(existing, vm, nic, ips_by_address, discovered_ips):
    """Collect usable scoped IPs and IPv4 candidates in discovery order.

    Reject duplicate NetBox records or foreign assignments before the batch-level
    duplicate check. Preserve record references and exact assignment semantics.
    """
    vm_ipv4 = []
    ip_contexts = []

    for raw_address in nic.ip_addresses:
        address = _usable_address(raw_address)

        if address is None:
            continue

        address_identity = scope_key(address, nic.ip_vrf_id)
        discovered_ips.setdefault(
            address_identity,
            [],
        ).append(
            (
                vm.original_name,
                interface_display_name(vm, nic),
            )
        )

        if ipaddress.ip_interface(address).version == 4:
            vm_ipv4.append(address_identity)

        matches = ips_by_address.get(
            address_identity,
            [],
        )

        if len(matches) > 1:
            raise VMNetworkApplyError(f"Duplicate NetBox IP " f"{address}")

        existing_ip = matches[0] if matches else None

        if existing_ip is not None:
            (
                assigned_type,
                assigned_id,
            ) = _assigned_object(existing_ip)

            allowed = assigned_type is None and assigned_id is None

            if existing is not None and assigned_type == "virtualization.vminterface" and assigned_id == existing.id:
                allowed = True

            if not allowed:
                raise VMNetworkApplyError(f"IP {address} " f"already assigned to " f"{assigned_type}:" f"{assigned_id}")

        ip_contexts.append(
            {
                "key": address_identity,
                "vrf_id": nic.ip_vrf_id,
                "address": address,
                "existing": existing_ip,
            }
        )

    return ip_contexts, vm_ipv4


def _prepare_vm_primary(vm_context, vm_ipv4, inventory):
    """Select a sole IPv4 candidate, preserving a manual primary owned by this VM.

    Mutate only the pending context. Foreign or missing current-primary records
    still raise before batch duplicate checks and before reporting or writing.
    """
    vm = vm_context["source_vm"]
    netbox_vm = vm_context["netbox_vm"]
    unique_ipv4 = sorted(set(vm_ipv4))

    if len(unique_ipv4) == 1:
        candidate = unique_ipv4[0]
        current_primary = _current_primary_ip_id(netbox_vm)
        candidate_records = inventory.ips_by_address.get(candidate, ())
        candidate_id = candidate_records[0].id if len(candidate_records) == 1 else None
        if current_primary is None:
            primary_action = "set"
        elif current_primary == candidate_id:
            primary_action = "match"
        else:
            current_record = inventory.ips_by_id.get(current_primary)
            current_address = current_record.serialize().get("address") if current_record is not None else None
            if not _primary_ip_belongs_to_vm(
                current_record,
                inventory.interfaces_by_id,
                netbox_vm.id,
            ):
                raise VMNetworkApplyError(
                    "Existing primary IPv4 conflicts on "
                    f"{vm.original_name}: current={current_address!r} "
                    f"discovered={candidate!r}"
                )
            primary_action = "preserve_manual"
            vm_context["primary_current"] = current_address
        vm_context["primary_candidate"] = candidate
        vm_context["primary_action"] = primary_action


def _prepare_vm_nic_context(vm, nic, existing_interfaces):
    """Match a stable NIC identity and prepare metadata without mutating records."""
    existing = _interface_match(
        existing_interfaces,
        vm,
        nic,
    )

    if existing is None:
        desired_cf = build_nic_custom_fields(
            vm,
            nic,
            {},
        )

        interface_changes = {}
    else:
        (
            interface_changes,
            desired_cf,
        ) = _desired_interface_changes(
            existing,
            vm,
            nic,
        )

    return {
        "source": nic,
        "existing": existing,
        "interface_changes": interface_changes,
        "desired_custom_fields": desired_cf,
    }


def _prepare_vm_network_context(vm, inventory, discovered_macs, discovered_ips):
    """Validate one VM in NIC order, then resolve its primary IPv4 policy."""
    netbox_vm = _find_vm(
        inventory.target_vms,
        vm,
    )

    existing_interfaces = inventory.interfaces_by_vm.get(
        netbox_vm.id,
        [],
    )

    validate_interface_names(
        vm,
        existing_interfaces,
        _interface_match,
        VMNetworkApplyError,
    )

    nic_names = {}

    for nic in vm.interfaces:
        nic_names.setdefault(
            interface_display_name(vm, nic).casefold(),
            [],
        ).append(nic)

    duplicates = [name for name, items in nic_names.items() if len(items) > 1]

    if duplicates:
        raise VMNetworkApplyError(f"Duplicate discovered NIC " f"names on {vm.original_name}: " + ",".join(duplicates))

    vm_context = {
        "source_vm": vm,
        "netbox_vm": netbox_vm,
        "nics": [],
        "primary_candidate": None,
        "primary_action": None,
        "primary_current": None,
    }

    vm_ipv4 = []

    for nic in vm.interfaces:
        nic_context = _prepare_vm_nic_context(vm, nic, existing_interfaces)
        nic_context["mac_value"], nic_context["existing_mac"] = _check_vm_mac(
            nic_context["existing"], vm, nic, inventory.macs_by_address, discovered_macs
        )
        nic_context["ips"], nic_ipv4 = _check_vm_ips(
            nic_context["existing"], vm, nic, inventory.ips_by_address, discovered_ips
        )
        vm_ipv4.extend(nic_ipv4)
        vm_context["nics"].append(nic_context)

    _prepare_vm_primary(vm_context, vm_ipv4, inventory)
    return vm_context


def prepare_vm_network_contexts(hosts, inventory):
    """Validate all VM networks before reporting or writing any NetBox changes.

    Per-VM failures precede batch duplicates; duplicate MACs precede duplicate IPs.
    LXC has separate primary-MAC and cluster policies and is not handled here.
    """
    contexts = []
    discovered_macs = {}
    discovered_ips = {}
    for host in hosts:
        for vm in host.virtual_machines:
            contexts.append(_prepare_vm_network_context(vm, inventory, discovered_macs, discovered_ips))

    duplicate_macs = {value: locations for value, locations in discovered_macs.items() if len(locations) > 1}

    if duplicate_macs:
        raise VMNetworkApplyError("Duplicate discovered MACs: " + ",".join(sorted(duplicate_macs)))

    duplicate_ips = {value: locations for value, locations in discovered_ips.items() if len(locations) > 1}

    if duplicate_ips:
        raise VMNetworkApplyError("Duplicate discovered IPs: " + ",".join(sorted(duplicate_ips)))

    return contexts
