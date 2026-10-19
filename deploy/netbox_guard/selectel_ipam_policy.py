"""Pure, conservative projection of accepted dedicated-server network evidence.

Allocation CIDR and interface netmask are different Selectel concepts (notably
shared /32 allocations on a /24). No NAT, cable or host NIC is inferred here.
"""
import ipaddress
import json
from .provider_policy import identity


def key(account, kind, native_id):
    return json.dumps(['selectel', account, kind, native_id], separators=(',', ':'))


def require(condition, code):
    if not condition:
        raise ValueError('SELECTEL_IPAM_' + code)


def section(snapshot, name):
    value = snapshot.get('sections', {}).get(name, {})
    require(value.get('status') in ('collected', 'empty') and not value.get('retained'),
            'SECTION_UNAVAILABLE_' + name.upper())
    return value['data']


def indexed(rows):
    result = {}
    for row in rows:
        uid = row.get('uuid')
        require(isinstance(uid, str) and bool(uid), 'UUID_REQUIRED')
        require(uid not in result or result[uid] == row, 'CONFLICTING_EVIDENCE')
        result[uid] = row
    return result


def project(snapshot):
    ident = snapshot['identity']
    identity(ident, 'device')
    account = ident['account']
    # Public global routing context is explicitly accepted in the CLI request.
    ips = indexed(section(snapshot, 'public_ips'))
    subnets = indexed(section(snapshot, 'public_subnets'))
    networks = indexed(section(snapshot, 'networks'))
    ports = indexed(section(snapshot, 'ports'))
    objects, links, notes = {}, [], []

    def add(kind, uid, fields, refs=None):
        k = key(account, kind, uid)
        value = dict(key=k, kind=kind, fields=fields, refs=refs or {})
        require(k not in objects or objects[k] == value, 'CONFLICTING_EVIDENCE')
        objects[k] = value
        return k

    def network(uid):
        n = networks.get(uid)
        if n is None:
            notes.append(dict(code='NETWORK_NOT_REPORTED', network_uuid=uid))
            return None
        require(n.get('location_uuid') and n.get('network_type'), 'NETWORK_SCOPE_REQUIRED')
        vid = n.get('vlan')
        require(type(vid) is int and 1 <= vid <= 4094, 'VLAN_INVALID')
        # Separate provider L2 services can use the same VID in the same DC.
        domain = n['location_uuid'] + ':' + n['network_type']
        g = add('vlangroup', domain, {'name': 'Selectel ' + account + ' ' + domain})
        return add('vlan', uid, {'vid': vid, 'name': 'Selectel ' + n['network_type'] + ' ' + str(vid)}, {'group_id': g})

    for uid, ip in sorted(ips.items()):
        require(ip.get('resource_uuid') == ident['native_id'], 'RESOURCE_MISMATCH')
        sub = subnets.get(ip.get('subnet_uuid'))
        require(sub is not None, 'SUBNET_NOT_REPORTED')
        require(ip.get('network_uuid') and sub.get('network_uuid') == ip['network_uuid'], 'NETWORK_MISMATCH')
        allocation = ipaddress.ip_network(sub['subnet'], strict=True)
        host = ipaddress.ip_address(ip['ip'])
        require(host in allocation and host.version == 4, 'PUBLIC_IPV4_REQUIRED')
        require(not (host.is_private or host.is_loopback or host.is_link_local or host.is_multicast or host.is_unspecified), 'PUBLIC_IPV4_REQUIRED')
        if ip.get('subnet'):
            require(ipaddress.ip_network(ip['subnet']) == allocation, 'SUBNET_MISMATCH')
        # Preserve provider's reported mask, not the allocation prefix length.
        mask = ip.get('netmask') or sub.get('netmask')
        require(bool(mask), 'ADDRESS_MASK_REQUIRED')
        address = ipaddress.ip_interface(str(host) + '/' + str(mask))
        require(allocation.subnet_of(address.network), 'MASK_CONFLICT')
        v = network(ip['network_uuid'])
        p = add('prefix', sub['uuid'], {'prefix': str(allocation), 'vrf_id': None}, {'vlan_id': v} if v else {})
        a = add('ipaddress', uid, {'address': str(address), 'vrf_id': None})
        evidence = {'allocation_uuid': uid, 'subnet_uuid': sub['uuid'], 'network_uuid': ip['network_uuid'],
                    'allocation_prefix': str(allocation), 'reported_netmask': str(mask), 'gateway': ip.get('gateway'),
                    'prefix_key': p, 'vlan_key': v}
        links.extend([dict(native=a, relation='allocation', evidence=evidence),
                      dict(native=p, relation='subnet', evidence={'network_uuid': ip['network_uuid'], 'vlan_key': v})])
        if allocation.prefixlen != address.network.prefixlen:
            notes.append(dict(code='ALLOCATION_AND_INTERFACE_MASK_DIFFER', address=str(address), allocation=str(allocation)))
    by_network = {}
    for port in ports.values():
        for n in port.get('networks', []):
            uid = n.get('uuid')
            require(uid in networks and all(networks[uid].get(k) == val for k, val in n.items()), 'PORT_NETWORK_CONFLICT')
            by_network.setdefault(uid, []).append({k: port.get(k) for k in
                ('uuid', 'port_name', 'port_type', 'port_mode', 'speed', 'is_enabled')})
    for uid, attached in sorted(by_network.items()):
        v = network(uid)
        links.append(dict(native=v, relation='attachment', evidence={'network_uuid': uid,
            'ports': sorted(attached, key=lambda p: p['uuid']), 'host_interface': None}))
    # Repeated allocations on a shared prefix produce one typed segment relation.
    unique = {}
    for link in links:
        k = (link['native'], link['relation'])
        require(k not in unique or unique[k] == link, 'CONFLICTING_LINK')
        unique[k] = link
    return {'objects': objects, 'links': list(unique.values()), 'notes': notes}
