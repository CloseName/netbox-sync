"""Resolve duplicate ESXi UUIDs without rewriting an existing ownership key.

A namespaced key records both original instance UUID and verified BIOS UUID.
It is persisted by the normal VM/NIC creation paths, not by discovery. Missing
VMs remain retained; their keys still fence ambiguous replacement attempts.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from .source_identity import SourceIdentity
from .esxi_discovery import _normalized_uuid
from .application.inventory_conflicts import InventoryConflict, ConflictParticipant

PREFIX = 'esxi-bios-v1/'


def bios_key(instance, bios):
    return f'{PREFIX}{instance}/{bios}'


def parse_key(value):
    if not value.startswith(PREFIX):
        return None
    parts = value[len(PREFIX):].split('/')
    if len(parts) != 2 or any(_normalized_uuid(p) != p for p in parts):
        raise ValueError('Invalid persisted ESXi BIOS identity')
    return tuple(parts)


def resolve_vm_identities(api, hosts, config):
    """Complete source inventory required. Return copies and explicit blockers."""
    if config.source_type != 'esxi':
        return hosts, ()
    result = deepcopy(list(hosts))
    vms = [vm for host in result for vm in host.virtual_machines]
    groups = defaultdict(list)
    bios_counts = Counter(vm.esxi_bios_uuid for vm in vms if vm.esxi_bios_uuid)
    for vm in vms:
        if vm.source_instance != config.source_instance or vm.source != 'esxi':
            raise ValueError('ESXi identity inventory outside source scope')
        if vm.esxi_instance_uuid:
            groups[vm.esxi_instance_uuid].append(vm)
    invalid = [InventoryConflict('VM_IDENTITY', instance, tuple(
        ConflictParticipant(name=v.original_name, external_id=str(v.external_id or v.vmid),
            provider_object_id=v.provider_object_id, host_id=v.node_source_id)
        for v in sorted(members, key=lambda v: (str(v.provider_object_id), v.original_name))))
        for instance, members in sorted(groups.items()) if len(members) > 1
        and any(not v.esxi_bios_uuid or bios_counts[v.esxi_bios_uuid] != 1 for v in members)]
    if invalid:
        return result, tuple(invalid)
    owned = defaultdict(set)
    tagged = defaultdict(set)
    historical = defaultdict(set)
    for record in api.virtualization.virtual_machines.all():
        for raw in (getattr(record, 'custom_fields', None) or {}).get('sync_identities', []) or []:
            identity = SourceIdentity.from_record(raw)
            if (identity is None or identity.type != 'esxi' or identity.kind != 'vm'
                    or identity.instance != config.source_instance):
                continue
            owned[identity.external_id].add(record.id)
            pair = parse_key(identity.external_id)
            if pair:
                original, bios = pair
                tagged[bios].add(identity.external_id)
                historical[original].add(identity.external_id)
    conflicts = []
    blocked = set()
    def block(value, members):
        key = (value, tuple(sorted(str(v.provider_object_id) for v in members)))
        if key in blocked:
            return
        blocked.add(key)
        conflicts.append(InventoryConflict('VM_IDENTITY', value, tuple(
            ConflictParticipant(name=v.original_name, external_id=str(v.external_id or v.vmid),
                provider_object_id=v.provider_object_id, host_id=v.node_source_id)
            for v in sorted(members, key=lambda v: (str(v.provider_object_id), v.original_name)))))
    for instance, members in groups.items():
        # An old shared key cannot be attributed to one clone using a name/MoRef.
        if len(members) > 1 and owned.get(instance):
            block(instance, members)
            continue
        for vm in members:
            bios = vm.esxi_bios_uuid
            persisted = tagged.get(bios, set())
            needs_bios = len(members) > 1 or bool(persisted)
            if not needs_bios:
                if (historical.get(instance) or (bios != instance and owned.get(bios) and not owned.get(instance))
                        or (vm.provider_object_id != instance and owned.get(vm.provider_object_id))):
                    block(instance, members)  # Lost/changed BIOS cannot create a replacement.
                continue
            if (not bios or bios_counts[bios] != 1 or len(persisted) > 1
                    or (persisted and (len(owned[next(iter(persisted))]) != 1 or owned.get(instance)))
                    or owned.get(bios)
                    or owned.get(vm.provider_object_id)):
                block(instance, members)
                continue
            selected = next(iter(persisted)) if persisted else bios_key(instance, bios)
            vm.external_id = vm.vmid = selected
            vm.source_id = f'esxi:{selected}'
    # A persisted BIOS choice also survives loss of the instance UUID itself.
    for vm in vms:
        if vm.esxi_instance_uuid:
            continue
        if ((not vm.esxi_bios_uuid and tagged)
                or (vm.provider_object_id != vm.external_id and owned.get(vm.provider_object_id))):
            block(str(vm.external_id or vm.vmid), [vm])
            continue
        if not tagged.get(vm.esxi_bios_uuid):
            continue
        keys = tagged[vm.esxi_bios_uuid]
        if (bios_counts[vm.esxi_bios_uuid] != 1 or len(keys) != 1
                or len(owned[next(iter(keys))]) != 1 or owned.get(vm.esxi_bios_uuid)):
            block(vm.esxi_bios_uuid, [vm])
            continue
        vm.external_id = vm.vmid = next(iter(keys))
        vm.source_id = f'esxi:{vm.external_id}'
    return result, tuple(sorted(conflicts, key=lambda c: (c.value, repr(c.participants))))
