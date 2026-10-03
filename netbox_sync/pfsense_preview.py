"""Read-only pfSense network preview. Standard library only; never writes NetBox."""
import ipaddress
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path


class SnapshotError(ValueError):
    pass


def fail():
    raise SnapshotError('Invalid or incomplete network snapshot')


def mac(value):
    if not isinstance(value, str):
        fail()
    compact = re.sub('[:-]', '', value).lower()
    if not re.fullmatch(r'[0-9a-f]{12}', compact):
        fail()
    if int(compact[:2], 16) & 1 or int(compact, 16) == 0:
        fail()
    return ':'.join(compact[i:i + 2] for i in range(0, 12, 2))


def text(value, maximum=256):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
        fail()
    return value


def runtime_interfaces(raw):
    if not isinstance(raw, str) or not raw or len(raw) > 1024 * 1024:
        fail()
    result = {}
    current = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        if not line[0].isspace():
            match = re.fullmatch(r'([\w.:-]+): flags=[0-9a-f]+(?:<([^>]*)>)? metric \d+ mtu (\d+)', line)
            if not match or match[1] in result or len(result) >= 512:
                fail()
            current = dict(device=match[1], admin_up='UP' in (match[2] or '').split(','),
                           mtu=int(match[3]), mac=None, status=None, addresses=[], media=None)
            if not 1 <= current['mtu'] <= 1000000:
                fail()
            result[match[1]] = current
            continue
        if current is None:
            fail()
        fields = line.strip().split()
        if fields[0] == 'ether':
            if len(fields) != 2 or current['mac'] is not None:
                fail()
            current['mac'] = mac(fields[1])
        elif fields[0] in ('inet', 'inet6'):
            try:
                if fields[0] == 'inet':
                    if fields[2] != 'netmask':
                        fail()
                    mask = fields[3]
                    if mask.startswith('0x'):
                        mask = str(ipaddress.IPv4Address(int(mask, 16)))
                    prefix = ipaddress.IPv4Network('0.0.0.0/' + mask).prefixlen
                    address = ipaddress.IPv4Interface(fields[1] + '/' + str(prefix))
                    scope = None
                else:
                    if fields[2] != 'prefixlen':
                        fail()
                    host, _, scope = fields[1].partition('%')
                    address = ipaddress.IPv6Interface(host + '/' + fields[3])
                    if scope and scope != current['device']:
                        fail()
                value = dict(address=str(address), scope=scope or None,
                             link_local=address.ip.is_link_local,
                             ipam_candidate=not (address.ip.is_link_local or address.ip.is_loopback
                                 or address.ip.is_multicast or address.ip.is_unspecified))
                if value not in current['addresses']:
                    current['addresses'].append(value)
                if len(current['addresses']) > 512:
                    fail()
            except (ValueError, IndexError):
                fail()
        elif fields[0] == 'status:':
            current['status'] = text(' '.join(fields[1:]))
        elif fields[0] == 'media:':
            current['media'] = text(' '.join(fields[1:]))
    if not result:
        fail()
    return result


def build_preview(snapshot, inventory, vm_id):
    if type(vm_id) is not int or vm_id <= 0 or not isinstance(snapshot, dict):
        fail()
    if snapshot.get('schema') != 'netbox-sync.pfsense.network.v1':
        fail()
    try:
        stamp = text(snapshot['collected_at'])
        parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            fail()
        version = text(snapshot['version'])
        config = snapshot['configuration']
        configured = config['interfaces']
        vlans = config['vlans']
        runtime = runtime_interfaces(snapshot['runtime']['ifconfig'])
    except (KeyError, TypeError, ValueError):
        fail()
    if (not isinstance(configured, list) or not 1 <= len(configured) <= 512
            or not isinstance(vlans, list) or len(vlans) > 512
            or not isinstance(inventory, list) or len(inventory) > 512):
        fail()
    targets = {}
    target_ids = set()
    for row in inventory:
        if (not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] <= 0
                or row['id'] in target_ids or type(row.get('vm_id')) is not int or row['vm_id'] != vm_id):
            fail()
        target_ids.add(row['id'])
        name = text(row.get('name'))
        if row.get('mac'):
            targets.setdefault(mac(row['mac']), []).append(dict(id=row['id'], name=name))
    runtime_macs = Counter(row['mac'] for row in runtime.values() if row['mac'])
    seen_ids, seen_devices = set(), set()
    rows, issues = [], []
    for entry in configured:
        if not isinstance(entry, dict):
            fail()
        try:
            selected = {key: text(entry[key]) for key in (
                'id', 'name', 'device', 'ipv4_config', 'ipv4_prefix',
                'ipv6_config', 'ipv6_prefix', 'configured_mtu')}
            if type(entry['enabled']) is not bool:
                fail()
            selected['enabled'] = entry['enabled']
        except (KeyError, TypeError):
            fail()
        device = selected['device']
        if not selected['id'] or not device or selected['id'] in seen_ids or device in seen_devices:
            fail()
        seen_ids.add(selected['id']); seen_devices.add(device)
        live = runtime.get(device)
        matches = targets.get(live['mac'], []) if live else []
        if live is None:
            state = 'RUNTIME_MISSING'
        elif live['mac'] is None:
            state = 'MAC_MISSING'
        elif runtime_macs[live['mac']] > 1 or len(matches) > 1:
            state = 'AMBIGUOUS_MAC'
        elif not matches:
            state = 'NO_VM_INTERFACE_MATCH'
        else:
            state = 'MATCHED'
        if state != 'MATCHED':
            issues.append(dict(device=device, code=state))
        rows.append(dict(configuration=selected, runtime=live,
                         match=matches[0] if state == 'MATCHED' else None, status=state))
    clean_vlans = []
    for vlan in vlans:
        if not isinstance(vlan, dict):
            fail()
        try:
            clean_vlans.append({key: text(vlan[key]) for key in ('parent', 'tag', 'device', 'description')})
        except KeyError:
            fail()
    return dict(schema='netbox-sync.pfsense.preview.v1', mode='READ_ONLY', vm_id=vm_id,
                collected_at=stamp, version=version, interfaces=rows, vlans=clean_vlans,
                issues=issues, all_interfaces_matched=not issues,
                unmapped_runtime_devices=sorted(set(runtime) - seen_devices),
                unmatched_vm_interfaces=sorted(target_ids - {r['match']['id'] for r in rows if r['match']}))


def load_snapshot(path):
    with Path(path).open('rb') as stream:
        data = stream.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        fail()
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                fail()
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        fail()


def netbox_preview(snapshot_path, vm_id):
    """Invoke inside NetBox manage.py shell; only SELECT queries are performed."""
    from virtualization.models import VirtualMachine
    from django.db import connection, transaction
    snapshot = load_snapshot(snapshot_path)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION READ ONLY')
        vm = VirtualMachine.objects.get(pk=vm_id)
        interfaces = list(vm.interfaces.select_related('primary_mac_address').all()[:513])
        inventory = [dict(id=iface.pk, vm_id=iface.virtual_machine_id, name=iface.name,
                          mac=str(iface.primary_mac_address.mac_address) if iface.primary_mac_address_id else None)
                     for iface in interfaces]
    result = build_preview(snapshot, inventory, vm_id)
    result['vm_name'] = str(vm.name)
    print('READ-ONLY PREVIEW: VM {} ({})'.format(vm_id, vm.name))
    print('pfSense {} | snapshot {}'.format(result['version'], result['collected_at']))
    print('pfSense | NetBox interface [ID] | MAC | MTU | state | IP addresses')
    for row in result['interfaces']:
        live = row['runtime'] or {}
        target = row['match']
        addresses = ', '.join(a['address'] for a in live.get('addresses', []) if a['ipam_candidate'])
        print('{} ({}) | {} | {} | {} | {} | {}'.format(
            row['configuration']['name'], row['configuration']['device'],
            '{} [{}]'.format(target['name'], target['id']) if target else row['status'],
            live.get('mac'), live.get('mtu'), live.get('status'), addresses))
    print('MATCHED: {}/{}'.format(sum(r['status'] == 'MATCHED' for r in result['interfaces']), len(result['interfaces'])))
    print('VLAN definitions: {}'.format(len(result['vlans'])))
    print('Other runtime interfaces: {}'.format(', '.join(result['unmapped_runtime_devices'])))
    print('Unmatched NetBox interface IDs: {}'.format(result['unmatched_vm_interfaces']))
    print('Issues: {}'.format(result['issues']))
    print('No changes written to NetBox.')
    return result
