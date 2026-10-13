"""Independent real transactions, only in the disposable NetBox Guard harness."""
import os
from copy import deepcopy
from uuid import uuid4
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from extras.models import CustomField
from virtualization.models import Cluster, ClusterType, VirtualMachine, VMInterface, VirtualDisk
from ipam.models import IPAddress
from dcim.models import MACAddress
from netbox_guard.models import CreationClaim, CreationReceipt
from netbox_guard.service import create_owned
from netbox_guard.dependencies import DependencyGuardBlocked
from netbox_guard.vm_replacement import review, execute

assert os.environ.get('NETBOX_SYNC_ISOLATED_MODEL_TEST') == '1'
assert connection.settings_dict['NAME'] == 'netbox_sync_guard_test'
assert not connection.in_atomic_block
from netbox_guard.dependencies import _digest, NETBOX_470_HOOKS
with connection.cursor() as cursor:
    cursor.execute('SELECT c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid),pg_get_functiondef(t.tgfoid) FROM pg_catalog.pg_trigger t '
        'JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace '
        'WHERE n.nspname=current_schema() AND NOT t.tgisinternal ORDER BY c.relname,t.tgname')
    hooks = cursor.fetchall()
    native = [row for row in hooks if row[1] not in ('netbox_guard_provider_write', 'guard_provider_ipam', 'guard_provider_immutable')]
    print('Disposable migrated database hooks:', len(hooks), _digest(hooks), 'native:', len(native), _digest(native), flush=True)
    assert _digest(native) == NETBOX_470_HOOKS
actor = get_user_model().objects.create(username='vm-replacement-fixture', is_superuser=True)
denied = get_user_model().objects.create(username='vm-replacement-denied')
ct = ClusterType.objects.create(name='Replacement fixture', slug='replacement-fixture')
cluster = Cluster.objects.create(name='Replacement fixture', type=ct)
source = 'replacement-fixture-esxi'
for field_name in ('sync_identities', 'sync_original_names'):
    field, _ = CustomField.objects.get_or_create(name=field_name, defaults={'type': 'json'})
    field.object_types.add(*ContentType.objects.filter(app_label='virtualization',
        model__in=['virtualmachine', 'vminterface', 'virtualdisk']))
for field_name, field_type, model in [('source_bridge', 'text', 'vminterface'),
                                     ('sync_disk_identity', 'json', 'virtualdisk')]:
    field, _ = CustomField.objects.get_or_create(name=field_name, defaults={'type': field_type})
    field.object_types.add(ContentType.objects.get(app_label='virtualization', model=model))


def fixture(name):
    identity = dict(schema='v2', type='esxi', instance=source, kind='vm', external_id=str(uuid4()))
    vm = create_owned(actor, uuid4(), source, 'vm', dict(name=name, cluster=cluster,
        custom_field_data={'sync_identities': [identity], 'sync_original_names': {f'esxi/{source}/vm': name}}), cluster=cluster.pk)
    nic = create_owned(actor, uuid4(), source, 'vminterface',
        dict(name='old-nic', virtual_machine=vm, custom_field_data={'source_bridge': 'Fixture portgroup'}), cluster=cluster.pk)
    octets = vm.pk.to_bytes(4, 'big')
    mac = create_owned(actor, uuid4(), source, 'mac',
        dict(mac_address='02:aa:' + ':'.join(f'{part:02x}' for part in octets), assigned_object=nic), cluster=cluster.pk)
    nic.primary_mac_address = mac
    nic.save()
    disk = create_owned(actor, uuid4(), source, 'disk',
        dict(name='old-disk', virtual_machine=vm, size=8000, custom_field_data={'sync_disk_identity':
            {**identity, 'kind': 'vm-disk', 'external_id': identity['external_id'] + ':2000'}}), cluster=cluster.pk)
    return vm, nic, disk, {**identity, 'external_id': str(uuid4())}


def refused(call):
    try:
        call()
    except DependencyGuardBlocked:
        return
    raise AssertionError('Unsafe replacement accepted')


vm, nic, disk, new = fixture('Recreated')
evidence = review(actor, vm.pk, source, cluster.pk)
# Known-name hooks must still have the exact enabled state/body; no name-only bypass.
with connection.cursor() as cursor:
    cursor.execute('ALTER TABLE virtualization_virtualmachine DISABLE TRIGGER netbox_guard_provider_write')
try:
    refused(lambda: review(actor, vm.pk, source, cluster.pk))
finally:
    with connection.cursor() as cursor:
        cursor.execute('ALTER TABLE virtualization_virtualmachine ENABLE TRIGGER netbox_guard_provider_write')
old_mac = nic.primary_mac_address_id
assert {tuple(row) for row in evidence['children']} == {('vminterface', nic.pk), ('disk', disk.pk), ('mac', old_mac)}
nonce = uuid4()
refused(lambda: execute(denied, vm.pk, source, cluster.pk, nonce, evidence, new, vm.name))
refused(lambda: review(denied, vm.pk, source, cluster.pk))
# Changes between review and write never discard new dependencies.
ip = IPAddress.objects.create(address='192.0.2.10/24', assigned_object=nic)
refused(lambda: execute(actor, vm.pk, source, cluster.pk, nonce, evidence, new, vm.name))
assert VMInterface.objects.filter(pk=nic.pk).exists() and ip.assigned_object_id == nic.pk
ip.delete()
evidence = review(actor, vm.pk, source, cluster.pk)
# A failure after child deletion rolls the entire reset back.
with patch.object(VirtualMachine, 'full_clean', side_effect=RuntimeError('fixture failure')):
    try:
        execute(actor, vm.pk, source, cluster.pk, nonce, evidence, new, vm.name)
    except RuntimeError as exc:
        assert str(exc) == 'fixture failure'
    else:
        raise AssertionError('Expected injected failure')
assert VMInterface.objects.filter(pk=nic.pk).exists()
assert VirtualDisk.objects.filter(pk=disk.pk).exists()
assert not CreationReceipt.objects.filter(pk=nonce).exists()
vm.refresh_from_db()
assert vm.custom_field_data['sync_identities'] != [new]
before_id, before_created = vm.pk, vm.created
assert execute(actor, vm.pk, source, cluster.pk, nonce, evidence, new, vm.name) == {'id': vm.pk, 'replayed': False}
vm.refresh_from_db()
assert (vm.pk, vm.created) == (before_id, before_created)
assert vm.custom_field_data['sync_identities'] == [new]
assert not VMInterface.objects.filter(pk=nic.pk).exists()
assert not VirtualDisk.objects.filter(pk=disk.pk).exists()
assert not MACAddress.objects.filter(pk=old_mac).exists()
assert not CreationClaim.objects.filter(resource='vminterface', object_id=nic.pk).exists()
assert execute(actor, vm.pk, source, cluster.pk, nonce, evidence, new, vm.name)['replayed']
refused(lambda: execute(actor, vm.pk, source, cluster.pk, nonce, evidence, {**new, 'external_id': str(uuid4())}, vm.name))
VirtualMachine.objects.filter(pk=vm.pk).update(custom_field_data={'sync_identities': [{**new, 'external_id': str(uuid4())}]})
refused(lambda: execute(actor, vm.pk, source, cluster.pk, nonce, evidence, new, vm.name))

for mode in ('unclaimed-vm', 'unclaimed-nic', 'manual-description', 'pfsense'):
    target, interface, _, _ = fixture('pfSense-protected' if mode == 'pfsense' else mode)
    if mode.startswith('unclaimed'):
        CreationClaim.objects.filter(resource='vm' if mode == 'unclaimed-vm' else 'vminterface',
            object_id=target.pk if mode == 'unclaimed-vm' else interface.pk).delete()
    elif mode == 'manual-description':
        interface.description = 'Operator notes'; interface.save()
    refused(lambda: review(actor, target.pk, source, cluster.pk))
    assert VirtualMachine.objects.filter(pk=target.pk).exists()
    assert VMInterface.objects.filter(pk=interface.pk).exists()
print('VM replacement: same card, actual claims, rollback, stale dependencies, IP protection, permissions and replay OK')
