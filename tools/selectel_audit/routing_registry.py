"""Allowlisted Global Router topology from explicit provider references only."""
FIELDS = {
    'routers': {'id', 'name', 'status', 'enabled', 'account_id', 'project_id', 'created_at', 'updated_at', 'tags', 'vpn_id'},
    'networks': {'id', 'name', 'status', 'account_id', 'project_id', 'router_id', 'zone_id', 'zone_name', 'zone_service', 'vlan', 'inner_vlan', 'vdc_name', 'os_network_id', 'created_at', 'updated_at', 'tags'},
    'subnets': {'id', 'name', 'status', 'account_id', 'project_id', 'network_id', 'cidr', 'gateway', 'service_addresses', 'os_subnet_id', 'created_at', 'updated_at', 'tags'},
    'static_routes': {'id', 'name', 'status', 'account_id', 'project_id', 'router_id', 'subnet_id', 'cidr', 'next_hop', 'created_at', 'updated_at', 'tags'},
}
KINDS = {'routers': 'global_router', 'networks': 'routing_network',
         'subnets': 'routing_subnet', 'static_routes': 'routing_route'}


def add_routing(document, key, node, edge, unresolved):
    account = str(document['account'])
    index, rows = {}, []
    zones = {}
    for dataset in document.get('datasets', []):
        if dataset.get('service') == 'global-router' and dataset.get('kind') == 'zones' and dataset.get('status') == 'collected':
            for zone in dataset.get('items', []):
                if isinstance(zone, dict) and isinstance(zone.get('id'), str):
                    zones[zone['id']] = zone

    for dataset in document.get('datasets', []):
        section = dataset.get('kind')
        if dataset.get('service') != 'global-router' or section not in KINDS:
            continue
        for raw in dataset.get('items', []):
            if not isinstance(raw, dict) or not isinstance(raw.get('id'), str) or not raw['id']:
                unresolved.append({'code': 'ROUTING_ID_MISSING'})
                continue
            if raw.get('account_id') not in (None, account):
                unresolved.append({'code': 'ROUTING_ACCOUNT_MISMATCH'})
                continue
            data = {k: v for k, v in raw.items() if k in FIELDS[section]}
            if section == 'networks':
                zone = zones.get(raw.get('zone_id'), {})
                for source, destination in (('visible_name', 'zone_name'), ('service', 'zone_service')):
                    if isinstance(zone.get(source), str):
                        data[destination] = zone[source]
            kind = KINDS[section]
            project = raw.get('project_id') or ''
            if not isinstance(project, str):
                unresolved.append({'code': 'ROUTING_PROJECT_INVALID'})
                continue
            ident = key(account, project, kind=kind, native_id=raw['id'])
            node(ident, kind, raw.get('name') or raw.get('cidr') or raw['id'],
                 {'section': section, 'status': dataset['status'], 'data': data})
            index.setdefault((section, raw['id']), set()).add(ident)
            rows.append((ident, section, data))
    for ident, section, data in rows:
        if section == 'routers':
            edge(key(account), ident, 'contains')
            continue
        parent_section, field = ('networks', 'network_id') if section == 'subnets' else ('routers', 'router_id')
        parents = index.get((parent_section, data.get(field)), set())
        if len(parents) == 1:
            edge(next(iter(parents)), ident, 'contains')
        else:
            unresolved.append({'code': 'ROUTING_PARENT_NOT_CONFIRMED', 'key': ident})
