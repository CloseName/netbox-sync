"""Read-only configured host paths. Never proves provider-port or NAT edges."""

def paths(fields, interface=None, bridge=None):
    snapshots = [(k, fields.get(k)) for k in ('esxi_host_network', 'proxmox_host_network')
                 if isinstance(fields.get(k), dict) and fields[k].get('available') is True]
    if len(snapshots) != 1:
        return {'status': 'snapshot_missing_or_ambiguous', 'paths': []}
    provider, snapshot = snapshots[0]
    if snapshot.get('version') != 1:
        return {'status': 'unsupported_snapshot', 'paths': []}
    graph, physical, pending = {}, set(), set()
    duplicate = False

    def add(key, children):
        nonlocal duplicate
        if key in graph:
            duplicate = True
        graph[key] = children

    if provider == 'esxi_host_network':
        for row in snapshot.get('physical_nics', []):
            name = row.get('name')
            if name:
                key = 'nic:' + name
                add(key, [])
                physical.add(key)
        for row in snapshot.get('switches', []):
            if row.get('name'):
                add('switch:' + row['name'], ['nic:' + n for n in row.get('uplinks', [])])
        for row in snapshot.get('port_groups', []):
            if row.get('name'):
                add('group:' + row['name'], ['switch:' + row['switch']] if row.get('switch') else [])
        for row in snapshot.get('vmkernel', []):
            if row.get('name'):
                add('kernel:' + row['name'], ['group:' + row['port_group']]
                    if row.get('port_group') and not row.get('distributed_switch_uuid') else [])
        start = 'group:' + bridge if bridge else 'kernel:' + str(interface)
    else:
        for row in snapshot.get('interfaces', []):
            name = row.get('name')
            if not name:
                continue
            children = []
            kind = row.get('type')
            if kind == 'bridge':
                children = row.get('bridge_ports', [])
            elif kind == 'bond':
                children = row.get('bond_slaves', [])
            elif kind == 'vlan' and row.get('vlan_parent'):
                children = [row['vlan_parent']]
            elif kind == 'eth':
                physical.add(name)
            if row.get('pending'):
                pending.add(name)
            add(name, children)
        start = bridge or interface
    if duplicate:
        return {'status': 'ambiguous_names', 'paths': []}
    result, incomplete, visits = [], False, 0

    def walk(node, trail):
        nonlocal incomplete, visits
        visits += 1
        if visits > 1024 or node in trail or len(trail) >= 32 or len(result) >= 64:
            incomplete = True
            return
        trail = trail + [node]
        if node not in graph or node in pending:
            incomplete = True
            return
        if node in physical:
            result.append(trail)
            return
        if not graph[node]:
            incomplete = True
        for child in sorted(graph[node]):
            walk(child, trail)

    walk(start, [])
    # Incomplete/ambiguous paths must not masquerade as a complete uplink mapping.
    return {'status': 'incomplete' if incomplete else 'configured',
            'basis': provider, 'paths': result,
            'provider_port_confirmed': False}
