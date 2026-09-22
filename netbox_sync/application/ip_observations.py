"""Explicit inventory projection; observations are not IPAM assignments.

Never infer network areas from bridge names or choose one conflicting mask.
The caller must persist the returned interface evidence with the reviewed plan.
"""
from ipaddress import ip_interface
from .inventory_order import canonical_hosts
from .inventory_conflicts import inventory_conflicts


POLICIES = ('strict', 'observe')


class ObservationPrerequisiteError(ValueError):
    pass


def assignment_inventory(hosts, policy='strict'):
    """Return a copy for assignment and all excluded facts, keeping strict default.

    VM identity conflicts are returned as blockers even in observe mode. The input
    Discovery inventory is untouched; no address is removed from NetBox here.
    """
    if policy not in POLICIES:
        raise ValueError('Unknown IP conflict policy')
    result = canonical_hosts(hosts)
    conflicts = inventory_conflicts(result)
    if policy == 'strict':
        return result, conflicts, ()
    blockers = tuple(c for c in conflicts if c.kind != 'IP_ASSIGNMENT')
    observations = tuple(c for c in conflicts if c.kind == 'IP_ASSIGNMENT')
    if blockers:
        return result, conflicts, ()
    excluded = {c.value for c in observations}
    for host in result:
        for vm in [*host.virtual_machines, *host.containers]:
            for nic in vm.interfaces:
                kept = []
                observed = []
                for raw in nic.ip_addresses:
                    try:
                        disputed = str(ip_interface(raw).ip) in excluded
                    except ValueError:
                        disputed = False  # Existing validation remains authoritative.
                    if disputed:
                        observed.append(str(ip_interface(raw)))
                    else:
                        kept.append(raw)
                nic.ip_addresses = kept
                nic.network_observations = {
                    'version': 1, 'status': 'REVIEW_REQUIRED' if observed else 'NO_DISPUTED_ADDRESSES',
                    'addresses': observed, 'bridge': nic.bridge, 'vlan_id': nic.vlan_id,
                    'ipam_complete': not bool(observed),
                }
    return result, (), observations


def source_policy(config):
    target = getattr(config, 'target', config)
    return getattr(target, 'onboarding_mapping', {}).get('ip_conflict_policy', 'strict')


def executable_inventory(api, hosts, config):
    """Executors repeat the same projection and refuse unresolved identity conflicts."""
    policy = source_policy(config)
    projected, blockers, observations = assignment_inventory(hosts, policy)
    if policy == 'observe':
        if blockers:
            raise ValueError('Inventory identity conflict')
        from ..prerequisites import reconcile
        rows = [row.serialize() for row in api.extras.custom_fields.filter(name='sync_network_observations')]
        field = next(row for row in reconcile(rows) if row['name'] == 'sync_network_observations')
        if field['status'] != 'ready':
            raise ObservationPrerequisiteError('Network observation prerequisite requires preparation')
    return projected, observations
