"""Report source-scoped missing objects without deleting retained inventory."""

from .disappearance_report import print_disappearance_report
from .disappearance_report import find_missing_objects
from .disappearance_inventory import load_disappearance_inventory
from .disappearance_identity import build_managed_identity_resolver
from .disappearance_identity import collect_discovered_identities
from .disappearance_inventory import resolve_disappearance_target
from .netbox_record_values import object_id as _object_id
from .host_mapping import cluster_filter
from .netbox_vm_metadata import (
    vm_identity_source_id,
)

from .netbox_lxc_metadata import (
    lxc_identity_source_id,
)

from .netbox_vm_interface_metadata import (
    nic_identity_source_id,
)
from .source_identity import (
    SourceIdentity,
    lxc_nic_source_identity,
    lxc_source_identity,
    virtual_machine_nic_source_identity,
    virtual_machine_source_identity,
)


def _local_source_id(obj):
    """Strip only the matching provider prefix from a source identifier."""

    value = str(obj.source_id)

    prefix = f"{obj.source}:"

    if value.startswith(prefix):
        return value[len(prefix) :]

    return value


def _identities(custom_fields):
    """Extract valid legacy source and object identifier pairs from custom fields."""

    custom_fields = dict(custom_fields or {})

    values = custom_fields.get("sync_identities")

    if not isinstance(
        values,
        list,
    ):
        return []

    result = []

    for item in values:
        if not isinstance(
            item,
            dict,
        ):
            continue

        source = item.get("source")

        source_id = item.get(
            "source_id",
            item.get("id"),
        )

        if source and source_id:
            result.append(
                (
                    str(source),
                    str(source_id),
                )
            )

    return result


def _v2_identities(custom_fields):
    """Parse recognized v2 identities from the custom-field list."""

    values = dict(custom_fields or {}).get("sync_identities")
    if not isinstance(values, list):
        return []

    result = []
    for value in values:
        parsed = SourceIdentity.from_record(value)
        if parsed is not None:
            result.append(parsed)
    return result


def _identity_label(identity):
    """Render either a typed v2 identity or a legacy identity pair."""

    if isinstance(identity, SourceIdentity):
        return f"{identity.type}/{identity.instance}/" f"{identity.kind}/{identity.external_id}"
    return f"{identity[0]}:{identity[1]}"


def report_missing_managed_objects(
    nb_api,
    hosts,
    config,
):
    """Compare scoped managed inventory with discovery and print a read-only disappearance report."""

    _site, cluster = resolve_disappearance_target(
        nb_api,
        config,
        cluster_filter=cluster_filter,
    )

    source_scopes, source_instances, discovered_guests, discovered_interfaces = collect_discovered_identities(
        hosts,
        _local_source_id=_local_source_id,
        vm_identity_source_id=vm_identity_source_id,
        virtual_machine_source_identity=virtual_machine_source_identity,
        nic_identity_source_id=nic_identity_source_id,
        virtual_machine_nic_source_identity=virtual_machine_nic_source_identity,
        lxc_identity_source_id=lxc_identity_source_id,
        lxc_source_identity=lxc_source_identity,
        lxc_nic_source_identity=lxc_nic_source_identity,
    )

    managed_identity = build_managed_identity_resolver(
        source_scopes,
        source_instances,
        _identities=_identities,
        _v2_identities=_v2_identities,
    )

    target_vms, interfaces_by_vm = load_disappearance_inventory(
        nb_api,
        cluster,
        _object_id=_object_id,
    )

    managed_guests, missing_guests, managed_interfaces, missing_interfaces = find_missing_objects(
        target_vms,
        interfaces_by_vm,
        discovered_guests,
        discovered_interfaces,
        managed_identity,
    )

    print_disappearance_report(
        managed_guests,
        missing_guests,
        managed_interfaces,
        missing_interfaces,
        discovered_guests,
        discovered_interfaces,
        _identity_label=_identity_label,
    )
