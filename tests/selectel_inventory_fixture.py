def fixture(account='fixture'):
    data = {'schema': 'selectel-audit-v1', 'account_verified': True, 'account': account,
            'finished_at': '2026-10-12T12:00:00+00:00', 'datasets': []}
    def add(service, kind, items, **kw):
        data['datasets'].append(dict(service=service, kind=kind, items=items, status='collected',
                                     project='', region='', **kw))
    add('dedicated', 'resources', [{'uuid': 'server-a', 'service_type': 'custom', 'hw_uuid': 'hw-a',
                                  'location_uuid': 'loc-a', 'user_desc': 'Dedicated A'}])
    add('dedicated', 'resource_info', [{'config_name': 'CPU / RAM', 'config': {
        'cpu': [{'name': 'CPU A', 'count': 1, 'price': 123, 'password': 'never-export'}]}}], resource_id='server-a')
    add('dedicated', 'locations', [{'uuid': 'loc-a', 'name': 'SPB-3'}])
    add('dedicated', 'public_ips', [{'uuid': 'ip-a', 'resource_uuid': 'server-a', 'ip': '192.0.2.2',
                                   'network_uuid': 'net-a', 'subnet_uuid': 'sub-a'},
                                  {'resource_uuid': 'other', 'ip': '192.0.2.3'}])
    add('dedicated', 'private_ips', [])
    add('dedicated', 'public_subnets', [{'uuid': 'sub-a', 'subnet': '192.0.2.0/24', 'network_uuid': 'net-a'}])
    add('dedicated', 'private_subnets', [])
    add('dedicated', 'networks', [{'uuid': 'net-a', 'vlan': 1608}])
    add('dedicated', 'ports', [{'hw_uuid': 'hw-a', 'port_name': 'test-port', 'network': [{'uuid': 'net-a'}]}])
    add('dedicated', 'operating_system', [{'os_template': 'linux', 'version': '1', 'password': 'never-export',
        'user_script': 'never-export', 'cloud_init_user_data': 'never-export'}], resource_id='server-a')
    for kind, items in (
        ('servers', [{'id': 'vm-a', 'name': 'Cloud A', 'flavor': {'id': 'flavor-a'},
                      'OS-EXT-AZ:availability_zone': 'ru-7a', 'adminPass': 'never-export'}]),
        ('flavors', [{'id': 'flavor-a', 'vcpus': 2, 'ram': 4096, 'disk': 20}])):
        data['datasets'].append(dict(service='compute', kind=kind, items=items, status='collected', project='p', region='r'))
    for project, ip in (('p', '198.51.100.1'), ('other', '203.0.113.1')):
        data['datasets'].append(dict(service='network', kind='ports', status='collected', project=project, region='r',
            items=[{'id': 'port-a', 'device_id': 'vm-a', 'network_id': 'net-cloud',
                    'fixed_ips': [{'subnet_id': 'cloud-sub', 'ip_address': ip}]}]))
    return data
