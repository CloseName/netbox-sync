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
