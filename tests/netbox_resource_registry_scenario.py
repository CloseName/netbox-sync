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

# Project/category drill-down and historical isolation are read-only.
request = RequestFactory().get('/providers/123/', {'project': 'p', 'kind': 'storage_container'})
request.user = admin
response = registry_view(request, '123')
assert response.status_code == 200
assert b'resource=' in response.content
assert b'<pre>' not in response.content
request = RequestFactory().get('/providers/123/', {'project': 'other', 'kind': 'storage_container'})
request.user = admin
assert b'resource=' not in registry_view(request, '123').content
request = RequestFactory().get('/providers/')
request.user = admin
assert registry_view(request).status_code in (200, 302)
assert ProviderResourceRegistry.objects.get(pk='123').revision == 2

from netbox_guard.resource_tree import build_tree
bucket_rows, _ = build_tree(ProviderResourceRegistry.objects.get(pk='123').snapshot['resources'].values())
request = RequestFactory().get('/providers/123/', {'kind': 'storage_container', 'resource': bucket_rows[0]['ref']})
request.user = admin
response = registry_view(request, '123')
assert response.status_code == 200 and b'<pre>' not in response.content

# Repair project names from the exact source audit, keeping imports idempotent.
import tempfile
import json
with tempfile.TemporaryDirectory() as directory:
    audit_path = Path(directory) / 'inventory.json'
    audit_path.write_text(json.dumps({'schema': 'selectel-audit-v1', 'account': '123',
        'finished_at': registry_new['observed_at'], 'projects': [{'id': 'p', 'name': 'Readable project'}]}))
    call_command('provider_project_names', input=str(audit_path), account='123', actor=admin.username)
    repaired = ProviderResourceRegistry.objects.get(pk='123')
    assert repaired.revision == 3
    assert next(r for r in repaired.snapshot['resources'].values() if r['kind'] == 'project')['name'] == 'Readable project'
    call_command('provider_project_names', input=str(audit_path), account='123', actor=admin.username)
    assert ProviderResourceRegistry.objects.get(pk='123').revision == 3
    assert registry_prepare(admin, registry_new)[3]['changes'] == 0

# Global Router cards render through the same stored registry without native Devices.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.selectel_audit.resource_registry import registry as audit_registry
routing_document = audit_registry(dict(account='123', finished_at='2026-11-04T10:00:00Z',
    datasets=[dict(service='global-router', kind='routers', status='collected',
                   items=[dict(id='router-fixture', name='Routing fixture')]),
              dict(service='global-router', kind='networks', status='collected',
                   items=[dict(id='network-fixture', name='Routing network', router_id='router-fixture', vlan=100)])],
    coverage=[dict(service='global-router', kind='routers', status='collected')]))
routing_preview = registry_prepare(admin, routing_document)[3]
registry_apply(admin, uuid4(), routing_document, routing_preview['fingerprint'])
routing_rows, _ = build_tree(ProviderResourceRegistry.objects.get(pk='123').snapshot['resources'].values())
router_row = next(r for r in routing_rows if r['kind'] == 'global_router')
request = RequestFactory().get('/providers/123/', {'kind': 'global_router', 'resource': router_row['ref']})
request.user = admin
response = registry_view(request, '123')
assert response.status_code == 200 and b'Routing network' in response.content
from django.utils.html import strip_tags
import re
routing_text = re.sub(r'\s+', ' ', strip_tags(response.content.decode()))
assert 'NOT_REPORTED' not in routing_text and 'VLAN 100' in routing_text
assert 'Сведения ещё не получены'.encode() in response.content
assert b'router-fixture' not in response.content and b'network-fixture' not in response.content
assert list(Device.objects.order_by('pk').values()) == native_before
from netbox_guard.provider_resource_graph import document as resource_graph
graph = resource_graph(admin, '123')
assert graph['schema'] == 'netbox-sync.provider-resources.v1' and not graph['writes_performed']
assert any(n['kind'] == 'global_router' for n in graph['nodes'])
assert any(e['kind'] == 'contains' and 'routing_network' in e['target'] for e in graph['edges'])
rejected(lambda: resource_graph(unprivileged, '123'), (PermissionDenied,))
