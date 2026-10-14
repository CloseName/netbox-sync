"""Explainable candidates only: this module has no NetBox writer."""
import ipaddress
from collections import defaultdict


def ip(value):
    try:
        address = ipaddress.ip_interface(str(value)).ip
        if (address.is_unspecified or address.is_loopback or address.is_link_local
                or address.is_multicast or str(address) == '255.255.255.255'):
            return None
        return str(address)
    except ValueError:
        return None


def object_id(value):
    return value.get('id') if isinstance(value, dict) else value


def addresses(value, key=''):
    result = set()
    if isinstance(value, dict):
        for k, item in value.items():
            result.update(addresses(item, k))
    elif isinstance(value, list):
        for item in value:
            result.update(addresses(item, key))
    elif key.lower() in ('addr', 'address', 'ip', 'ip_address', 'ipv4_address', 'ipv6_address',
                          'local_ipv4_address', 'floating_ip_address', 'fixed_ip_address',
                          'accessipv4', 'accessipv6'):
        parsed = ip(value)
        if parsed:
            result.add(parsed)
    return result


def inventory(document):
    """Resource rows for review; the complete field export remains in datasets."""
    rows, seen = [], set()
    datasets = document['datasets']
    for data in datasets:
        service, kind = data['service'], data['kind']
        if not ((service == 'compute' and kind == 'servers') or
                (service == 'dedicated' and kind == 'resources')):
            continue
        for obj in data['items']:
            ident = obj.get('id') or obj.get('uuid')
            if not ident:
                continue
            project, region = data.get('project') or obj.get('project_uuid', ''), data.get('region', '')
            key = (document['account'], project, region, service, str(ident))
            if key in seen:
                continue
            seen.add(key)
            resource_type = obj.get('service_type', '')
            row = {'account': document['account'], 'project': project, 'region': region,
                   'kind': 'cloud_vm' if service == 'compute' else 'dedicated_resource',
                   'provider_id': str(ident), 'name': obj.get('name') or obj.get('user_desc') or '',
                   'status': obj.get('status') or obj.get('state') or '',
                   'resource_type': resource_type, 'addresses': sorted(addresses(obj)),
                   'source_status': data['status'], 'serial': obj.get('serial') or '',
                   'hardware_id': obj.get('hw_uuid') or '', 'candidates': [],
                   'match_status': 'NOT_COMPARED', 'auto_apply': False}
            extras = []
            for other in datasets:
                if service == 'dedicated' and other.get('resource_id') == ident:
                    extras.extend(other['items'])
                if other['service'] == 'dedicated' and other['kind'] in ('public_ips', 'private_ips'):
                    extras.extend(x for x in other['items'] if x.get('resource_uuid') == ident)
                if service == 'compute' and other['service'] == 'network' and other['kind'] == 'ports':
                    if other.get('project') == project and other.get('region') == region:
                        extras.extend(x for x in other['items'] if x.get('device_id') == ident)
            row['addresses'] = sorted(set(row['addresses']) | addresses(extras))
            row['private_ip_scope'] = 'unmapped'
            if service == 'dedicated' and resource_type not in ('server', 'serverchip', 'custom', 'colocation'):
                row['kind'] = 'other_dedicated_resource'
            rows.append(row)
    return rows


def match_candidates(rows, netbox):
    """IP/MAC/name evidence never constitutes provider identity or write authority."""
    data = netbox['datasets']
    complete = all(x['status'] == 'collected' for x in netbox['coverage'])
    ips_by_target = defaultdict(set)
    iface_owner = {}
    for table, obj_type, owner, target_type in (
        ('device_interfaces', 'dcim.interface', 'device', 'device'),
        ('vm_interfaces', 'virtualization.vminterface', 'virtual_machine', 'vm'),
    ):
        for obj in data.get(table, []):
            ident = object_id(obj.get(owner))
            if ident:
                iface_owner[(obj_type, obj['id'])] = (target_type, ident)
    for obj in data.get('ips', []):
        target = iface_owner.get((obj.get('assigned_object_type'), obj.get('assigned_object_id')))
        parsed = ip(obj.get('address'))
        if target and parsed:
            ips_by_target[target].add((parsed, object_id(obj.get('vrf'))))
    targets = {}
    for table, typ in (('devices', 'device'), ('vms', 'vm')):
        for obj in data.get(table, []):
            target = (typ, obj['id'])
            targets[target] = obj
            for field in ('primary_ip4', 'primary_ip6'):
                primary = obj.get(field)
                if isinstance(primary, dict) and ip(primary.get('address')):
                    ips_by_target[target].add((ip(primary['address']), None))
    for row in rows:
        if row['kind'] == 'other_dedicated_resource':
            row['match_status'] = 'NOT_A_HOST_OR_VM'
            continue
        wanted = 'vm' if row['kind'] == 'cloud_vm' else 'device'
        for target, obj in targets.items():
            evidence = []
            name = str(obj.get('name') or '').casefold().rstrip('.')
            if row['name'] and row['name'].casefold().rstrip('.') == name:
                evidence.append({'type': 'name_exact', 'strength': 'hint'})
            serial = str(obj.get('serial') or '').strip()
            if row['serial'] and row['serial'] == serial and serial.casefold() not in ('unknown', 'none', 'n/a', '0'):
                evidence.append({'type': 'serial_exact', 'strength': 'review'})
            for addr, vrf in sorted(ips_by_target[target], key=lambda x: (x[0], str(x[1]))):
                if addr in row['addresses']:
                    public = ipaddress.ip_address(addr).is_global
                    evidence.append({'type': 'public_ip' if public else 'private_ip_unmapped',
                                     'address': addr, 'netbox_vrf': vrf, 'strength': 'hint'})
            if evidence:
                row['candidates'].append({'type': target[0], 'id': target[1],
                    'name': obj.get('name', ''), 'evidence': evidence,
                    'object_type_conflict': target[0] != wanted})
        if not complete:
            row['match_status'] = 'INCOMPLETE_NETBOX_READ'
        elif len(row['candidates']) > 1 or any(x['object_type_conflict'] for x in row['candidates']):
            row['match_status'] = 'CONFLICT'
        elif row['candidates']:
            row['match_status'] = 'REVIEW_REQUIRED'
        else:
            row['match_status'] = 'NO_CANDIDATE'
    # Two provider records proposing the same NetBox object are a conflict too.
    reverse = defaultdict(list)
    for row in rows:
        for candidate in row['candidates']:
            reverse[(candidate['type'], candidate['id'])].append(row)
    for group in reverse.values():
        if len(group) > 1:
            for row in group:
                if row['match_status'] != 'INCOMPLETE_NETBOX_READ':
                    row['match_status'] = 'CONFLICT'
    return rows
