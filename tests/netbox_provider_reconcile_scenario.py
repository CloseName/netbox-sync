"""Real models, within the disposable outer transaction."""
from datetime import timedelta
from django.utils import timezone
from django.test import RequestFactory
from netbox_guard.resource_registry_views import registry as registry_view
from netbox_guard.provider_reconcile import prepare as native_prepare, apply as native_apply
from netbox_guard.provider_policy import identity as provider_key
from netbox_guard.models import ProviderInventory

account = '98765'
def insert_resource(kind, native, name, serial='', age=0):
    ident = dict(account=account, kind=kind, native_id=native, project='project-native', region='ru-test')
    key = provider_key(ident, 'device' if kind == 'dedicated' else 'vm')
    sections = {'resource': {'status': 'collected', 'data': {'name': name, 'status': 'ACTIVE'}},
                'hardware': {'status': 'collected', 'data': {'serial': serial, 'vcpus': 2, 'ram': 2048}},
                'placement': {'status': 'collected', 'data': {'name': 'Test zone'}}}
    return ProviderInventory.objects.create(provider_key=key, account=account,
        snapshot={'identity': ident, 'sections': sections}, evidence_digest='e' * 64,
        observed_at=timezone.now() - timedelta(days=age))

native_host = Device.objects.create(name='native-existing-host', serial='NATIVE-UNIQUE', site=site, device_type=dtype, role=role)
host_pk, host_created = native_host.pk, native_host.created
match = insert_resource('dedicated', 'match', 'Different provider name', serial='NATIVE-UNIQUE')
cloud = insert_resource('cloud_vm', 'cloud', 'Cloud fixture')
physical = insert_resource('dedicated', 'physical', 'Physical fixture', serial='NATIVE-NEW-HARDWARE')
unknown = insert_resource('dedicated', 'unknown', 'Unknown hardware')
stale = insert_resource('cloud_vm', 'stale', 'Old VM', age=3)
plan = native_prepare(admin, account)
actions = {r['key']: r['action'] for r in plan['resources']}
assert actions[match.pk] == 'bind' and actions[cloud.pk] == 'create'
assert actions[unknown.pk] == actions[stale.pk] == 'blocked'
rejected(lambda: native_prepare(unprivileged, account), (DependencyGuardBlocked, ValueError))
rejected(lambda: native_apply(admin, account, uuid4(), '0' * 64), (ValueError,))
count = VirtualMachine.objects.count()
with patch('netbox_guard.provider_reconcile.apply_binding', side_effect=ValueError('rollback')):
    rejected(lambda: native_apply(admin, account, uuid4(), plan['fingerprint']), (ValueError,))
assert VirtualMachine.objects.count() == count
assert not ProviderBinding.objects.filter(account=account).exists()
nonce = uuid4()
result = native_apply(admin, account, nonce, plan['fingerprint'])
assert len(result['applied']) == 3
assert native_apply(admin, account, nonce, plan['fingerprint'])['replayed']
native_host.refresh_from_db()
assert native_host.pk == host_pk and native_host.created == host_created
assert native_host.name == 'native-existing-host'
assert native_host.primary_ip4_id is None
assert not any(p['action'] in ('bind', 'create') for p in native_prepare(admin, account)['resources'])
vm_binding = ProviderBinding.objects.get(provider_key=cloud.pk)
cloud_vm = VirtualMachine.objects.get(pk=vm_binding.object_id)
assert cloud_vm.site.region.name.endswith('ru-test')
assert cloud_vm.memory == 2048 and cloud_vm.primary_ip4_id is None

# Duplicate hardware IDs never silently choose one Device.
insert_resource('dedicated', 'duplicate', 'Another label', serial='NATIVE-UNIQUE')
assert next(p for p in native_prepare(admin, account)['resources'] if p['key'].endswith('"duplicate"]'))['action'] == 'blocked'
print('Native reconciliation: adoption, VM creation, scopes, stale inventory, permissions, duplicate refusal, rollback and replay OK')

request = RequestFactory().get('/providers/' + account + '/', {'kind': 'cloud_vm'})
request.user = admin
response = registry_view(request, account)
assert response.status_code == 200
assert cloud_vm.get_absolute_url().encode() in response.content
assert b'<pre>' not in response.content
assert b'provider_key' not in response.content

# Network scope and guest placement are evidence, never identity by themselves.
from virtualization.models import VMInterface
from dcim.models import Interface
from ipam.models import IPAddress

guest = VirtualMachine.objects.create(name='scope-guest', site=site, device=native_host)
guest_nic = VMInterface.objects.create(virtual_machine=guest, name='WAN')
host_nic = Interface.objects.create(device=native_host, name='fixture-management', type='virtual')
private_ip = IPAddress.objects.create(address='192.168.199.231/24', assigned_object=guest_nic)
public_ip = IPAddress.objects.create(address='8.8.4.231/24', assigned_object=guest_nic)
host_ip = IPAddress.objects.create(address='8.8.4.232/24', assigned_object=host_nic)

def with_addresses(record, values, status='ACTIVE', task=None):
    record.snapshot['sections']['addresses'] = {'status': 'collected', 'data': {
        'network': [{'addr': v} for v in values]}}
    record.snapshot['sections']['resource']['data'].update(status=status, **{'OS-EXT-STS:task_state': task})
    record.save()
    return record

scoped = with_addresses(insert_resource('cloud_vm', 'scope', 'Distinct cloud VM'), ['192.168.199.231'])
error_vm = with_addresses(insert_resource('cloud_vm', 'error', 'Failed cloud VM'), [], status='ERROR')
busy = with_addresses(insert_resource('cloud_vm', 'busy', 'Busy cloud VM'), [], status='ERROR', task='rebuilding')
unknown_state = with_addresses(insert_resource('cloud_vm', 'unknown-state', 'Unknown state'), [], status='NEW_STATE')
chain = with_addresses(insert_resource('dedicated', 'chain', 'Guest-host chain'), ['8.8.4.231', '8.8.4.232'])
public_collision = with_addresses(insert_resource('cloud_vm', 'public-collision', 'Public collision'), ['8.8.4.231'])
plan = native_prepare(admin, account)
rows = {r['key']: r for r in plan['resources']}
assert rows[scoped.pk]['action'] == 'create' and not rows[scoped.pk]['candidates']
assert rows[scoped.pk]['ignored_address_matches'][0]['reason'] == 'network_scope_unverified'
assert rows[error_vm.pk]['action'] == 'create' and rows[error_vm.pk]['native_status'] == 'failed'
assert rows[busy.pk]['reason'] == 'provider_task_in_progress'
assert rows[unknown_state.pk]['reason'] == 'provider_state_not_ready'
assert rows[public_collision.pk]['action'] == 'blocked'
assert rows[chain.pk]['action'] == 'blocked'
assert len(rows[chain.pk]['host_groups']) == 1
assert rows[chain.pk]['host_groups'][0]['device_id'] == native_host.pk
assert len(rows[chain.pk]['host_groups'][0]['members']) == 2
assert rows[chain.pk]['host_groups'][0]['confirmed'] is False
# Same private address plus equal name remains a duplicate candidate.
scoped.snapshot['sections']['resource']['data']['name'] = guest.name
scoped.save()
assert next(r for r in native_prepare(admin, account)['resources'] if r['key'] == scoped.pk)['action'] == 'blocked'
scoped.snapshot['sections']['resource']['data']['name'] = 'Distinct cloud VM'
scoped.save()
plan = native_prepare(admin, account)
result = native_apply(admin, account, uuid4(), plan['fingerprint'])
failed_binding = ProviderBinding.objects.get(provider_key=error_vm.pk)
assert VirtualMachine.objects.get(pk=failed_binding.object_id).status == 'failed'
for address, owner in ((private_ip, guest_nic), (public_ip, guest_nic), (host_ip, host_nic)):
    address.refresh_from_db()
    assert address.assigned_object == owner and address.nat_inside_id is None
assert not any(r['action'] in ('create', 'bind') for r in native_prepare(admin, account)['resources'])
print('Scope isolation, ERROR inventory, task guard and guest-host evidence preservation OK')
