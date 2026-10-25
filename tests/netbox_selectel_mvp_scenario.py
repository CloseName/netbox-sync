"""Executed inside disposable PostgreSQL transaction from provider scenario."""
import tempfile
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from netbox_guard.account_import import import_account
from netbox_guard.models import ProviderAccountRun, ProviderInventoryImport, ProviderResourceRegistry
from tools.selectel_audit.resource_registry import registry
document = runpy.run_path(str(Path(__file__).with_name('selectel_inventory_fixture.py')))['fixture']('67890')
document['projects'] = [{'id': 'p', 'name': 'Readable project'}]
document['datasets'].append(dict(service='image', kind='images', project='p', region='r',
    status='collected', items=[{'id': 'unused-image', 'name': 'Public catalog choice', 'metadata': 'x'*1000000}]))
# NetBox does not install Sync's runtime dependencies; load the pure wire module.
wire = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'netbox_sync/selectel_payload.py'))
inventory_document, import_payload = wire['inventory_document'], wire['import_payload']
from netbox_guard.selectel_inventory import Inventory
compact = inventory_document(document)
assert Inventory(compact).normalize() == Inventory(document).normalize()
assert len(json.dumps(compact)) < len(json.dumps(document)) - 900000
payload = import_payload('67890', str(uuid4()), dict(document=compact, registry=registry(document)))
before = list(Device.objects.order_by('pk').values())
rejected(lambda: import_account(unprivileged, payload), (DependencyGuardBlocked,))
receipts = ProviderInventoryImport.objects.count()
with patch('netbox_guard.account_import.apply', side_effect=ValueError('registry failed')):
    rejected(lambda: import_account(admin, payload), (ValueError,))
assert ProviderInventoryImport.objects.count() == receipts
assert not ProviderAccountRun.objects.filter(account='67890').exists()
result = import_account(admin, payload)
assert result['servers'] == 2 and result['unmatched'] == 2
assert import_account(admin, payload)['replayed']
assert list(Device.objects.order_by('pk').values()) == before
changed = copy.deepcopy(payload); changed['document']['finished_at'] = '2026-10-13T00:00:00Z'
changed['registry']['observed_at'] = changed['document']['finished_at']
rejected(lambda: import_account(admin, changed), (ValueError,))
assert ProviderAccountRun.objects.filter(account='67890').count() == 1

# Provision a dedicated non-admin account and prove the import works with it.
with tempfile.TemporaryDirectory() as temp:
    output = Path(temp) / 'token.json'
    call_command('configure_selectel_mvp', output=str(output))
    assert json.loads(output.read_text())['token']
    service_user = get_user_model().objects.get(username='netbox-sync-selectel')
    assert not service_user.is_superuser and not getattr(service_user, 'is_staff', False)
    assert not service_user.has_perm('dcim.add_device')
    assert not service_user.has_perm('ipam.change_ipaddress')
    payload['nonce'] = str(uuid4())
    assert import_account(service_user, payload)['servers'] == 2
    from rest_framework.test import APIRequestFactory, force_authenticate
    from netbox_guard.api.provider import ProviderAccountImport
    from netbox_guard.models import GuardIdentity
    from users.models import Token
    token = Token.objects.get(pk=json.loads(output.read_text())['token_id'])
    factory = APIRequestFactory()
    headers = {'HTTP_X_NETBOX_SYNC_GUARD_INSTANCE': str(GuardIdentity.objects.get(pk=1).identifier)}
    request = factory.get('/providers/account-import/', **headers)
    force_authenticate(request, user=service_user, token=token)
    assert ProviderAccountImport.as_view()(request).data == {'ready': True}
    payload['nonce'] = str(uuid4())
    request = factory.post('/providers/account-import/', payload, format='json', **headers)
    force_authenticate(request, user=service_user, token=token)
    response = ProviderAccountImport.as_view()(request)
    assert response.status_code == 200, response.data
    assert response.data['servers'] == 2
    request = factory.get('/providers/account-import/', **headers)
    force_authenticate(request, user=unprivileged)
    assert ProviderAccountImport.as_view()(request).status_code == 403
print('Selectel MVP atomic import, rollback, replay, permissions and native preservation OK')

# Opt-in automatic native import runs under dedicated, non-admin permissions.
from django.test import override_settings
from django.conf import settings
from django.utils import timezone
from netbox_guard.models import ProviderCreatedObject
from netbox_guard.provider_creation import create_native
from dcim.models import Region
from django.contrib.contenttypes.models import ContentType
from users.models import ObjectPermission

# Real NetBox permission backend: model permission is not sufficient, and a
# rejected provisional row must not survive the helper's savepoint.
with transaction.atomic():
    suffix = uuid4().hex
    limited_creator = get_user_model().objects.create(username='selectel-create-' + suffix)
    allowed_name = 'Allowed ' + suffix
    scoped = ObjectPermission.objects.create(name='selectel-create-' + suffix,
        actions=['add'], constraints={'name': allowed_name})
    scoped.object_types.add(ContentType.objects.get_for_model(Region))
    scoped.users.add(limited_creator)
    limited_creator = get_user_model().objects.get(pk=limited_creator.pk)
    assert limited_creator.has_perm('dcim.add_region')
    assert not limited_creator.has_perm('dcim.add_region', Region(name=allowed_name))
    allowed_region = create_native(limited_creator, Region(name=allowed_name, slug='allowed-' + suffix))
    assert Region.objects.filter(pk=allowed_region.pk).exists()
    count = Region.objects.count()
    rejected(lambda: create_native(limited_creator, Region(name='Denied ' + suffix, slug='denied-' + suffix)),
             (DependencyGuardBlocked,))
    assert Region.objects.count() == count
    assert not Region.objects.filter(slug='denied-' + suffix).exists()
    transaction.set_rollback(True)

with tempfile.TemporaryDirectory() as temp:
    call_command('configure_selectel_mvp', output=str(Path(temp)/'native-token.json'), native_resources=True)
    service_user = get_user_model().objects.get(username='netbox-sync-selectel')
    assert service_user.has_perm('dcim.add_device')
    assert not service_user.has_perm('ipam.change_ipaddress')
    native_document = copy.deepcopy(document)
    native_document['account'] = '67891'
    native_document['finished_at'] = timezone.now().isoformat()
    for dataset in native_document['datasets']:
        if dataset['service'] == 'compute' and dataset['kind'] == 'servers':
            dataset['items'][0].update(name='Automatic native import fixture', status='ACTIVE')
    native_payload = import_payload('67891', str(uuid4()), dict(
        document=inventory_document(native_document), registry=registry(native_document)))
    config = copy.deepcopy(settings.PLUGINS_CONFIG)
    config.setdefault('netbox_guard', {})['selectel_native_reconcile'] = True
    with override_settings(PLUGINS_CONFIG=config):
        initial_count = VirtualMachine.objects.count()
        with patch('netbox_guard.provider_reconcile.apply_binding', side_effect=ValueError('atomic refusal')):
            rejected(lambda: import_account(service_user, native_payload), (ValueError,))
        assert VirtualMachine.objects.count() == initial_count
        assert not ProviderAccountRun.objects.filter(account='67891').exists()
        native_result = import_account(service_user, native_payload)
        assert native_result['native_mode'] == 'automatic'
        assert native_result['native_created'] == 1 and native_result['native_blocked'] == 1
        assert native_result['matched'] == 1 and native_result['unmatched'] == 1
        assert import_account(service_user, native_payload)['replayed']
        assert VirtualMachine.objects.count() == initial_count + 1
        created = VirtualMachine.objects.get(name='Automatic native import fixture')
        assert created.custom_field_data['selectel_inventory']['identity']['account'] == '67891'
        assert ProviderCreatedObject.objects.filter(account='67891', object_id=created.pk,
            model_label='virtualization.virtualmachine').exists()
        assert created.primary_ip4_id is None
        # A later provider refresh wins over native values, without a new card.
        from datetime import timedelta
        revised = copy.deepcopy(native_document)
        revised['finished_at'] = (timezone.now() + timedelta(seconds=1)).isoformat()
        for dataset in revised['datasets']:
            if dataset['service'] == 'compute' and dataset['kind'] == 'servers':
                dataset['items'][0]['name'] = 'Renamed by Selectel fixture'
            if dataset['service'] == 'compute' and dataset['kind'] == 'flavors':
                dataset['items'][0].update(vcpus=6, ram=12288)
        revised_payload = import_payload('67891', str(uuid4()), dict(
            document=inventory_document(revised), registry=registry(revised)))
        changed = import_account(service_user, revised_payload)
        created.refresh_from_db()
        assert created.name == 'Renamed by Selectel fixture'
        assert created.vcpus == 6 and created.memory == 12288
        assert created.primary_ip4_id is None and changed['native_created'] == 0
        assert set(created.custom_field_data['selectel_inventory']['native_fields']) >= {'name','vcpus','memory','site_id'}
        from django.db import IntegrityError
        rejected(lambda: VirtualMachine.objects.filter(pk=created.pk).update(memory=2048), (IntegrityError,))
        # Region/site labels can change while stable provider location IDs stay.
        from netbox_guard.provider_placement import resolve
        placement = {'identity':dict(account='67891',kind='dedicated',native_id='placement-only',project='',region=''),
                     'sections':{'placement':dict(status='collected',retained=False,data=dict(uuid='placement-1',name='Original'))}}
        first_site = resolve(service_user, placement)
        previous = copy.deepcopy(placement)
        placement['sections']['placement']['data']['name'] = 'Renamed'
        renamed_site = resolve(service_user, placement, previous)
        assert first_site.pk == renamed_site.pk and renamed_site.name.endswith('/ Renamed')
        assert renamed_site.region_id is None
print('Opt-in automatic native import: dedicated permission, creation provenance, atomic rollback and replay OK')
