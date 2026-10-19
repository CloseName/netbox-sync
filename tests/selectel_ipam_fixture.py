def snapshot(native_id='server-a', address='8.8.4.2', allocation='ip-a'):
    def section(data):
        return {'status': 'collected' if data else 'empty', 'retained': False, 'data': data}
    network = {'uuid': 'inet-a', 'location_uuid': 'spb3', 'network_type': 'inet', 'vlan': 1608}
    return {'identity': {'account': 'fixture', 'kind': 'dedicated', 'native_id': native_id, 'project': '', 'region': ''},
        'sections': {
            'public_ips': section([{'uuid': allocation, 'resource_uuid': native_id, 'ip': address,
                'subnet_uuid': 'subnet-a', 'subnet': '8.8.4.0/29', 'network_uuid': 'inet-a', 'netmask': '255.255.255.248'}]),
            'public_subnets': section([{'uuid': 'subnet-a', 'subnet': '8.8.4.0/29', 'network_uuid': 'inet-a'}]),
            'networks': section([network]),
            'ports': section([{'uuid': 'port-' + native_id, 'port_name': 'ge-0/0/1', 'networks': [network]}]),
        }}
