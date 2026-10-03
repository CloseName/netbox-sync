"""Explicit manual IPv4 import for reviewed bindings. No deletes or reassignment."""
import ipaddress
import runpy
from datetime import datetime, timezone
from pathlib import Path

# Operator-reviewed VM/interface IDs, MACs and observed addresses. Names are not identity.
TEST_VM = 2609
TEST_BINDINGS = {
    3169: ('bc:24:11:90:8c:32', ['95.213.250.249/28', '95.213.250.243/28']),
    3170: ('bc:24:11:1d:9d:2b', ['10.10.110.14/24']),
    3171: ('bc:24:11:e1:65:54', ['10.24.0.1/24']),
    3172: ('bc:24:11:36:5f:bf', ['10.24.1.1/24']),
    3173: ('bc:24:11:32:11:8e', ['10.24.2.1/24']),
    3174: ('bc:24:11:ff:cb:3a', ['10.24.3.1/24']),
}


def reviewed_addresses(preview, expected, now=None):
    now = now or datetime.now(timezone.utc)
    stamp = datetime.fromisoformat(preview['collected_at'].replace('Z', '+00:00'))
    if stamp.tzinfo is None or not -120 <= (now-stamp).total_seconds() <= 900:
        raise ValueError('Collect a fresh snapshot (maximum 15 minutes old)')
    if not preview['all_interfaces_matched'] or preview['issues'] or preview['unmatched_vm_interfaces']:
        raise ValueError('Interface matching is incomplete')
    actual = {}
    for row in preview['interfaces']:
        target = row['match']['id']
        if target in actual:
            raise ValueError('Duplicate target interface')
        addresses = [str(ipaddress.ip_interface(a['address'])) for a in row['runtime']['addresses']
                     if a['ipam_candidate'] and ipaddress.ip_interface(a['address']).version == 4]
        actual[target] = (row['runtime']['mac'], sorted(addresses))
    reviewed = {key: (value[0], sorted(value[1])) for key, value in expected.items()}
    if actual != reviewed:
        raise ValueError('MAC/interface/address bindings changed: review a new plan')
    hosts = [str(ipaddress.ip_interface(a).ip) for _, addresses in actual.values() for a in addresses]
    if len(hosts) != len(set(hosts)):
        raise ValueError('Duplicate IPv4 observations in Global')
    return [(key, address) for key in sorted(actual) for address in actual[key][1]]


def import_test(snapshot_path, apply=False):
    from django.contrib.contenttypes.models import ContentType
    from django.db import connection, transaction
    from django.db.models import CharField, F, Func
    from virtualization.models import VirtualMachine, VMInterface
    from dcim.models import MACAddress
    from ipam.models import IPAddress
    from netbox_guard.pfsense_preview import load_snapshot, build_preview
    classify = runpy.run_path(str(Path(__file__).with_name('pfsense_ipam_preview.py')))['classify']
    snapshot = load_snapshot(snapshot_path)
    results = []
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            if apply:
                # Prevent concurrent inserts even when Global IP uniqueness is disabled.
                cursor.execute('LOCK TABLE ipam_ipaddress IN SHARE ROW EXCLUSIVE MODE')
            else:
                cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        vms = VirtualMachine.objects.select_for_update() if apply else VirtualMachine.objects
        vm = vms.get(pk=TEST_VM)
        query = VMInterface.objects.filter(virtual_machine_id=vm.pk).order_by('pk')
        interfaces = list((query.select_for_update() if apply else query)[:513])
        mac_ids = [i.primary_mac_address_id for i in interfaces if i.primary_mac_address_id]
        mac_query = MACAddress.objects.filter(pk__in=mac_ids).order_by('pk')
        macs = {m.pk: str(m.mac_address) for m in (mac_query.select_for_update() if apply else mac_query)}
        inventory = [dict(id=i.pk,vm_id=i.virtual_machine_id,name=i.name,mac=macs.get(i.primary_mac_address_id)) for i in interfaces]
        preview = build_preview(snapshot, inventory, vm.pk)
        addresses = reviewed_addresses(preview, TEST_BINDINGS)
        plans = []
        for target, address in addresses:
            host = str(ipaddress.ip_interface(address).ip)
            records = list(IPAddress.objects.annotate(observed_host=Func(F('address'),function='HOST',output_field=CharField()))
                .filter(observed_host=host,vrf_id=None).select_related('assigned_object_type').order_by('pk')[:3])
            evidence = [dict(id=r.pk,address=str(r.address),vrf_id=r.vrf_id,
                assigned_type=(r.assigned_object_type.app_label+'.'+r.assigned_object_type.model) if r.assigned_object_type_id else None,
                assigned_id=r.assigned_object_id) for r in records]
            action = classify(address,target,evidence,True,None)
            if action not in ('WOULD_CREATE_AND_ASSIGN','ALREADY_ASSIGNED'):
                raise ValueError('{}: {}. Nothing written.'.format(address,action))
            plans.append((target,address,action,records[0].pk if records else None))
        # Only create after every address passes. Validation errors roll back all creates.
        ct = ContentType.objects.get(app_label='virtualization',model='vminterface')
        for target,address,action,existing_id in plans:
            if action == 'ALREADY_ASSIGNED':
                results.append(('UNCHANGED',address,target,existing_id))
            elif not apply:
                results.append(('WOULD_CREATE',address,target,None))
            else:
                record = IPAddress(address=address,vrf_id=None,status='active',
                    assigned_object_type=ct,assigned_object_id=target,
                    description='Manual pfSense observation, VM {}'.format(vm.pk))
                record.full_clean()
                record.save()
                results.append(('CREATED',address,target,record.pk))
    print('VM {} | Global | {}'.format(TEST_VM,'APPLIED' if apply else 'PREVIEW ONLY'))
    for state,address,target,pk in results:
        print('{}: {} -> interface {} | IP ID {}'.format(state,address,target,pk))
    print('Created: {} | Unchanged: {}'.format(sum(r[0]=='CREATED' for r in results),sum(r[0]=='UNCHANGED' for r in results)))
    print('No prefixes, interface names, existing IP fields or VM primary IPs changed.')
    return results
