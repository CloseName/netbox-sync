from .netbox_vm_metadata import (
    vm_identity_source_id,
)
from .source_identity import (
    SourceIdentity,
    lxc_nic_source_identity,
    merge_original_name,
    merge_source_identities,
    virtual_machine_nic_source_identity,
    select_best_identity_matches,
    source_identity_match_rank,
)


MANAGED_VM_INTERFACE_CUSTOM_FIELDS = (
    'sync_identities',
    'sync_original_names',
    'source_bridge',
    'source_vlan_id',
    'sync_network_observations',
)


def nic_identity_source_id(vm, nic):
    return (
        f'{vm_identity_source_id(vm)}:'
        f'{nic.name}'
    )


def matches_nic_sync_identity(
        custom_fields,
        vm,
        nic,
):
    return bool(nic_sync_identity_match_rank(custom_fields, vm, nic))


def nic_sync_identity_match_rank(custom_fields, vm, nic):
    """Return the centralized v2/v1 match priority for one NIC."""

    wanted = nic_identity_source_id(
        vm,
        nic,
    )
    builder = (
        lxc_nic_source_identity
        if hasattr(vm, 'architecture')
        else virtual_machine_nic_source_identity
    )
    desired = builder(vm, nic)
    rank = source_identity_match_rank(
        custom_fields,
        desired,
        (wanted,),
        vm.legacy_identity_owner,
    )
    stable_key = getattr(nic, 'external_id', None)
    if (
        rank
        or desired.type != 'proxmox'
        or desired.kind != 'lxc-nic'
        or not stable_key
        or str(stable_key) == str(nic.name)
    ):
        return rank

    # PHASE 2B originally wrote Proxmox NIC v2 identities from the displayed
    # interface name. Read that exact same source-scoped v2 identity once so
    # the next managed update can migrate it to the provider's netX key.
    legacy_v2 = SourceIdentity(
        schema=desired.schema,
        type=desired.type,
        instance=desired.instance,
        kind=desired.kind,
        external_id=f'{vm.vmid}:{nic.name}',
    )
    return source_identity_match_rank(custom_fields, legacy_v2)


def find_nic_sync_identity_matches(candidates, vm, nic):
    """Find best-ranked interface records, retaining duplicates."""

    return select_best_identity_matches(
        candidates,
        lambda candidate: nic_sync_identity_match_rank(
            getattr(candidate, 'custom_fields', None) or {}, vm, nic,
        ),
    )


def build_nic_custom_fields(
        vm,
        nic,
        existing_custom_fields=None,
):
    existing = dict(
        existing_custom_fields or {}
    )

    builder = (
        lxc_nic_source_identity
        if hasattr(vm, 'architecture')
        else virtual_machine_nic_source_identity
    )
    desired_identity = builder(vm, nic)
    merged_identities = merge_source_identities(existing, desired_identity)
    merged_original_names = merge_original_name(
        existing, desired_identity, nic.name,
    )

    result = dict(existing)

    result.update({
        'sync_identities':
            merged_identities,

        'sync_original_names':
            merged_original_names,

        'source_bridge':
            nic.bridge,

        'source_vlan_id':
            nic.vlan_id,
    })

    observations = getattr(nic, 'network_observations', None)
    if observations is not None:
        # Preserve entries belonging to other sources and arbitrary unrelated fields.
        previous = existing.get('sync_network_observations') or {}
        if not isinstance(previous, dict):
            raise ValueError('Incompatible network observation field')
        result['sync_network_observations'] = {
            **previous, vm.source_instance: observations,
        }
    return result
