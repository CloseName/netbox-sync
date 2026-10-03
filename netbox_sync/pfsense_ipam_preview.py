"""Read-only IPAM evidence and proposed actions. No writes or implicit VRF selection."""
import ipaddress
from collections import Counter


def classify(address, interface_id, records, scope_selected=False, vrf_id=None):
    wanted = ipaddress.ip_interface(address)
    if wanted.version == 4 and wanted.network.prefixlen < 31 and wanted.ip in (wanted.network.network_address, wanted.network.broadcast_address):
        return 'INVALID_HOST_ADDRESS'
    if not scope_selected:
        return 'SCOPE_REQUIRED'
    candidates = [row for row in records if row['vrf_id'] == vrf_id]
    if len(candidates) > 1:
        return 'DUPLICATE_IP_RECORDS'
    if not candidates:
        return 'WOULD_CREATE_AND_ASSIGN'
    row = candidates[0]
    if ipaddress.ip_interface(row['address']) != wanted:
        return 'PREFIX_LENGTH_CONFLICT'
    if row['assigned_type'] is None and row['assigned_id'] is None:
        return 'UNASSIGNED_REVIEW_REQUIRED'
    if row['assigned_type'] != 'virtualization.vminterface' or row['assigned_id'] != interface_id:
        return 'ASSIGNED_ELSEWHERE'
    return 'ALREADY_ASSIGNED'


def plan(preview, evidence, vrf_by_interface=None):
    if not preview['all_interfaces_matched'] or preview['issues'] or preview['unmatched_vm_interfaces']:
        raise ValueError('Complete unambiguous VM interface matching is required')
    scopes = vrf_by_interface or {}
    ids = {str(row['match']['id']) for row in preview['interfaces']}
    if not isinstance(scopes, dict) or set(scopes) - ids:
        raise ValueError('Scope mapping contains an unknown interface')
    for choice in scopes.values():
        if choice is not None and (type(choice) is not int or choice <= 0):
            raise ValueError('Select global (null) or an existing positive VRF ID')
    result = []
    for row in preview['interfaces']:
        target = row['match']
        for observation in row['runtime']['addresses']:
            if not observation['ipam_candidate']:
                continue
            address = str(ipaddress.ip_interface(observation['address']))
            host = str(ipaddress.ip_interface(address).ip)
            facts = evidence[host]
            if any(str(ipaddress.ip_interface(r['address']).ip) != host for r in facts['addresses']):
                raise ValueError('IP evidence contains a different host')
            selected = str(target['id']) in scopes
            vrf = scopes.get(str(target['id']))
            result.append(dict(address=address, device=row['configuration']['device'],
                label=row['configuration']['name'], interface_id=target['id'], interface_name=target['name'],
                scope_selected=selected, vrf_id=vrf,
                action=classify(address, target['id'], facts['addresses'], selected, vrf),
                existing=facts['addresses'], covering_prefixes=facts['prefixes']))
    counts = Counter((str(ipaddress.ip_interface(r['address']).ip), r['scope_selected'], r['vrf_id']) for r in result)
    for row in result:
        key = (str(ipaddress.ip_interface(row['address']).ip), row['scope_selected'], row['vrf_id'])
        if counts[key] > 1:
            row['action'] = 'DUPLICATE_OBSERVATION'
    return result


def netbox_ipam_preview(snapshot_path, vm_id, vrf_by_interface=None):
    from django.db import connection, transaction
    from django.db.models import CharField, F, Func
    from virtualization.models import VirtualMachine
    from ipam.models import IPAddress, Prefix, VRF
    from netbox_guard.pfsense_preview import build_preview, load_snapshot
    snapshot = load_snapshot(snapshot_path)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        vm = VirtualMachine.objects.get(pk=vm_id)
        interfaces = list(vm.interfaces.select_related('primary_mac_address').all()[:513])
        inventory = [dict(id=i.pk, vm_id=i.virtual_machine_id, name=i.name,
            mac=str(i.primary_mac_address.mac_address) if i.primary_mac_address_id else None) for i in interfaces]
        preview = build_preview(snapshot, inventory, vm.pk)
        hosts = {str(ipaddress.ip_interface(a['address']).ip) for row in preview['interfaces']
                 for a in (row['runtime'] or {}).get('addresses', []) if a['ipam_candidate']}
        if len(hosts) > 128:
            raise ValueError('Too many observed addresses for manual preview')
        scopes = vrf_by_interface or {}
        chosen = {v for v in scopes.values() if v is not None}
        if set(VRF.objects.filter(pk__in=chosen).values_list('pk', flat=True)) != chosen:
            raise ValueError('Selected VRF does not exist')
        evidence = {}
        for host in sorted(hosts):
            addresses = list(IPAddress.objects.annotate(observed_host=Func(F('address'), function='HOST', output_field=CharField()))
                .filter(observed_host=host).select_related('vrf', 'assigned_object_type').order_by('pk')[:201])
            prefixes = list(Prefix.objects.filter(prefix__net_contains_or_equals=host).select_related('vrf').order_by('pk')[:201])
            if len(addresses) > 200 or len(prefixes) > 200:
                raise ValueError('Too many matching records; narrow the scope before continuing')
            evidence[host] = dict(addresses=[dict(id=a.pk, address=str(a.address), vrf_id=a.vrf_id,
                vrf_name=str(a.vrf.name) if a.vrf_id else 'Global', status=a.status, role=a.role,
                assigned_type=(a.assigned_object_type.app_label + '.' + a.assigned_object_type.model) if a.assigned_object_type_id else None,
                assigned_id=a.assigned_object_id) for a in addresses],
                prefixes=[dict(id=p.pk, prefix=str(p.prefix), vrf_id=p.vrf_id,
                               vrf_name=str(p.vrf.name) if p.vrf_id else 'Global') for p in prefixes])
        rows = plan(preview, evidence, vrf_by_interface)
    print('READ-ONLY IPAM PLAN: VM {} ({}) | snapshot {}'.format(vm.pk, vm.name, preview['collected_at']))
    for row in rows:
        print('\n{} ({}) -> {} [{}]: {} | {}'.format(row['label'], row['device'], row['interface_name'], row['interface_id'], row['address'], row['action']))
        for existing in row['existing']:
            print('  IP #{id}: {address} | VRF={vrf_name} [{vrf_id}] | assignment={assigned_type}:{assigned_id} | status={status} role={role}'.format(**existing))
        if not row['existing']:
            print('  No existing IP with this host address in any VRF.')
        for prefix in row['covering_prefixes']:
            print('  Prefix #{id}: {prefix} | VRF={vrf_name} [{vrf_id}]'.format(**prefix))
        if not row['covering_prefixes']:
            print('  No covering prefix in NetBox.')
    print('\nCandidates: {}. No changes written. Prefixes and VM names do not select a VRF automatically.'.format(len(rows)))
    return rows
