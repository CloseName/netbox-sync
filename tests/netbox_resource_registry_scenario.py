"""Loaded inside disposable NetBox test transaction; no live infrastructure."""
fixture = runpy.run_path(str(Path(__file__).with_name('resource_registry_fixture.py')))['fixture']
from netbox_guard.resource_registry_service import prepare as registry_prepare, apply as registry_apply
from netbox_guard.models import ProviderResourceRegistry, ProviderResourceRegistryChange
from netbox_guard.resource_registry_views import registry as registry_view
from django.test import RequestFactory
from django.core.exceptions import PermissionDenied
from netbox_guard.dependencies import DependencyGuardBlocked

registry_document = fixture()
native_before = list(Device.objects.order_by('pk').values())
registry_review = registry_prepare(admin, registry_document)[3]
registry_nonce = uuid4()
registry_result = registry_apply(admin, registry_nonce, registry_document, registry_review['fingerprint'])
assert registry_result['revision'] == 1 and registry_result['writes_performed']
assert registry_apply(admin, registry_nonce, registry_document, registry_review['fingerprint'])['replayed']
assert registry_prepare(admin, registry_document)[3]['changes'] == 0
rejected(lambda: registry_prepare(unprivileged, registry_document), (DependencyGuardBlocked,))
registry_new = copy.deepcopy(registry_document)
registry_new['observed_at'] = '2026-10-13T11:00:00Z'
registry_new['resources'][-1]['observations'][1].update(status='HTTP_403', data=[])
registry_new_review = registry_prepare(admin, registry_new)[3]
assert registry_new_review['retained_sections'] == 1
rejected(lambda: registry_apply(admin, uuid4(), registry_new, registry_review['fingerprint']), (ValueError,))
with patch.object(ProviderResourceRegistryChange.objects, 'create', side_effect=ValueError('fixture rollback')):
    rejected(lambda: registry_apply(admin, uuid4(), registry_new, registry_new_review['fingerprint']), (ValueError,))
assert ProviderResourceRegistry.objects.get(pk='123').revision == 1
registry_apply(admin, uuid4(), registry_new, registry_new_review['fingerprint'])
assert ProviderResourceRegistryChange.objects.filter(registry_id='123').count() == 2
rejected(lambda: registry_prepare(admin, registry_document), (ValueError,))
assert list(Device.objects.order_by('pk').values()) == native_before
request = RequestFactory().get('/providers/123/')
request.user = unprivileged
rejected(lambda: registry_view(request, '123'), (PermissionDenied,))
request.user = admin
assert registry_view(request, '123').status_code == 200
request.GET = request.GET.copy(); request.GET['revision'] = '1'
assert registry_view(request, '123').status_code == 200
print('Persistent DNS/S3 registry: migration, replay, stale review, retention, rollback, permissions and HTML OK')
