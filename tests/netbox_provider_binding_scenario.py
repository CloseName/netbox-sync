"""Actual NetBox 4.7 + PostgreSQL; use only the existing disposable model harness."""
import copy
import runpy
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from types import SimpleNamespace

runpy.run_path(str(Path(__file__).with_name('netbox_model_scope_scenario.py')))
from django.db import connection, transaction, IntegrityError
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from dcim.models import Device, DeviceType, DeviceRole, Manufacturer, Site
from extras.models import CustomField
from virtualization.models import VirtualMachine
from netbox_guard.models import ProviderBinding, ProviderFieldClaim, ProviderBindingChange
from netbox_guard.provider_schema import configure_provider_fields
from netbox_guard.provider_service import review_binding, apply_binding
from netbox_guard.dependencies import DependencyGuardBlocked
from netbox_guard.service import _claims

assert connection.settings_dict['NAME'] == 'netbox_sync_guard_test'
call_command('makemigrations', 'netbox_guard', check=True, dry_run=True, verbosity=0)


def rejected(action, errors=(IntegrityError,)):
    try:
        with transaction.atomic():
            action()
    except errors:
        return
    raise AssertionError('Expected refusal')


with transaction.atomic():
    admin = get_user_model().objects.create(username='provider-fixture', is_superuser=True)
    unprivileged = get_user_model().objects.create(username='provider-fixture-no-permission')
    site = Site.objects.create(name='Provider test', slug='provider-test')
    maker = Manufacturer.objects.create(name='Provider fixture', slug='provider-fixture')
    dtype = DeviceType.objects.create(manufacturer=maker, model='Fixture', slug='provider-fixture')
    role = DeviceRole.objects.create(name='Fixture', slug='provider-fixture')
    obj = Device.objects.create(name='preserved-host', site=site, device_type=dtype, role=role)
    original_created = obj.created
    configure_provider_fields()
    identity_field, _ = CustomField.objects.get_or_create(name='sync_identities', defaults={'type': 'json'})
    identity_field.object_types.add(identity_field.object_types.model.objects.get(app_label='dcim', model='device'))
    ids = list(CustomField.objects.filter(name__startswith='selectel_').values_list('id', flat=True))
    configure_provider_fields()
    assert ids == list(CustomField.objects.filter(name__startswith='selectel_').values_list('id', flat=True))
    with transaction.atomic():
        CustomField.objects.filter(name='selectel_refs').update(type='text')
        rejected(configure_provider_fields, (ValueError,))
        transaction.set_rollback(True)
    payload = {'resource': 'device', 'object_id': obj.pk,
        'identity': {'account': 'fixture', 'kind': 'dedicated', 'native_id': 'server-a', 'project': '', 'region': ''},
        'serial': 'SN123', 'reason': 'Operator-confirmed fixture', 'evidence_digest': 'a' * 64}
    rejected(lambda: review_binding(unprivileged, payload), (DependencyGuardBlocked,))
    preview = review_binding(admin, payload)
    Device.objects.filter(pk=obj.pk).update(name='changed-since-review')
    rejected(lambda: apply_binding(admin, uuid4(), payload, preview['fingerprint']), (ValueError,))
    preview = review_binding(admin, payload)
    nonce = uuid4()
    apply_binding(admin, nonce, payload, preview['fingerprint'])
    assert apply_binding(admin, nonce, payload, preview['fingerprint'])['replayed']
    assert ProviderBinding.objects.count() == 1 and ProviderBindingChange.objects.count() == 1
    obj.refresh_from_db()
    assert obj.created == original_created and obj.serial == 'SN123' and obj.name == 'changed-since-review'
    # Bulk update bypasses Django save signals; database enforcement must still work.
    rejected(lambda: Device.objects.filter(pk=obj.pk).update(serial='old-hypervisor-value'))
    rejected(lambda: Device.objects.filter(pk=obj.pk).update(custom_field_data={}))
    rejected(lambda: Device.objects.filter(pk=obj.pk).delete())
    rejected(lambda: _claims(SimpleNamespace(objects=((f'device:{obj.pk}', {}),)), 'fixture', 1),
             (DependencyGuardBlocked,))
    # Unclaimed fields and a matching full-object update remain valid.
    Device.objects.filter(pk=obj.pk).update(name='same-object-new-name', serial='SN123')
    obj.refresh_from_db()
    obj.custom_field_data['sync_identities'] = [{'schema': 'v2', 'type': 'esxi', 'instance': 'fixture', 'kind': 'host', 'external_id': 'h1'}]
    obj.save()
    assert ProviderBinding.objects.get().object_id == obj.pk
    # A different resource/account cannot claim this object; same provider cannot claim another.
    foreign = copy.deepcopy(payload)
    foreign['identity']['account'] = 'other'
    rejected(lambda: review_binding(admin, foreign), (ValueError,))
    duplicate = Device.objects.create(name='other-host', site=site, device_type=dtype, role=role)
    rejected(lambda: review_binding(admin, dict(payload, object_id=duplicate.pk)), (ValueError,))
    # Guard update succeeds; omission of serial never silently releases its claim.
    update = copy.deepcopy(payload)
    update['serial'] = 'SN456'
    preview = review_binding(admin, update)
    apply_binding(admin, uuid4(), update, preview['fingerprint'])
    update['serial'] = None
    preview = review_binding(admin, update)
    apply_binding(admin, uuid4(), update, preview['fingerprint'])
    obj.refresh_from_db()
    assert obj.serial == 'SN456' and obj.custom_field_data['sync_identities'][0]['external_id'] == 'h1'
    assert ProviderFieldClaim.objects.get(field='serial').value == 'SN456'
    failed = dict(update, serial='SN789')
    failed_preview = review_binding(admin, failed)
    before_count = ProviderBindingChange.objects.count()
    with patch.object(Device, 'save', side_effect=ValidationError('fixture refusal')):
        rejected(lambda: apply_binding(admin, uuid4(), failed, failed_preview['fingerprint']), (ValidationError,))
    obj.refresh_from_db()
    assert obj.serial == 'SN456'
    assert ProviderFieldClaim.objects.get(field='serial').value == 'SN456'
    assert ProviderBindingChange.objects.count() == before_count
    rejected(lambda: Device.objects.filter(pk=duplicate.pk).update(custom_field_data={'selectel_summary': 'forged'}))
    vm = VirtualMachine.objects.create(name='cloud-fixture', site=site)
    vm_spec = dict(payload, resource='vm', object_id=vm.pk, serial=None,
                  identity={'account': 'fixture', 'kind': 'cloud_vm', 'native_id': 'vm-a', 'project': 'p', 'region': 'r'})
    vm_preview = review_binding(admin, vm_spec)
    apply_binding(admin, uuid4(), vm_spec, vm_preview['fingerprint'])
    rejected(lambda: VirtualMachine.objects.filter(pk=vm.pk).update(custom_field_data={}))
    rejected(lambda: VirtualMachine.objects.filter(pk=vm.pk).delete())
    # Full inventory uses accepted bindings only, with a registry for unbound servers.
    from netbox_guard.inventory_service import review_inventory, apply_inventory
    from netbox_guard.models import ProviderInventory, ProviderInventoryImport
    fixture = runpy.run_path(str(Path(__file__).with_name('selectel_inventory_fixture.py')))['fixture']
    document = fixture()
    unbound = copy.deepcopy(document['datasets'][0]['items'][0])
    unbound['uuid'] = 'unbound-server'
    document['datasets'][0]['items'].append(unbound)
    rejected(lambda: review_inventory(unprivileged, document, 'b' * 64), (DependencyGuardBlocked,))
    inv_review = review_inventory(admin, document, 'b' * 64)
    assert inv_review['server_count'] == 3 and inv_review['bound_count'] == 2
    obj.refresh_from_db()
    original = {f.attname: copy.deepcopy(getattr(obj, f.attname)) for f in obj._meta.concrete_fields
                if f.attname not in ('custom_field_data', 'last_updated', '_config_context_data', '_config_context_generation')}
    original_cf = copy.deepcopy(obj.custom_field_data)
    import_nonce = uuid4()
    imported = apply_inventory(admin, import_nonce, document, 'b' * 64, inv_review['fingerprint'])
    assert len(imported['targets_updated']) == 2 and imported['unmatched_count'] == 1
    assert ProviderInventory.objects.count() == 3
    assert apply_inventory(admin, import_nonce, document, 'b' * 64, inv_review['fingerprint'])['replayed']
    obj.refresh_from_db()
    for name, value in original.items():
        assert getattr(obj, name) == value, name
    for name, value in original_cf.items():
        if name not in ('selectel_inventory', 'selectel_location', 'selectel_configuration', 'selectel_os',
                        'selectel_networks', 'selectel_collection_status'):
            assert obj.custom_field_data[name] == value, name
    assert obj.custom_field_data['selectel_location'] == 'SPB-3'
    assert obj.custom_field_data['selectel_networks'] == '192.0.2.2'
    assert 'never-export' not in str(obj.custom_field_data)
    changed_cf = dict(obj.custom_field_data, selectel_location='forged')
    rejected(lambda: Device.objects.filter(pk=obj.pk).update(custom_field_data=changed_cf))
    rejected(lambda: Device.objects.filter(pk=duplicate.pk).update(custom_field_data={'selectel_inventory': {}}))
    # Repeat fresh review is a no-op, not an endless sequence of object updates.
    again = review_inventory(admin, document, 'b' * 64)
    assert not any(x['projection_changed'] for x in again['resources'])
    assert not apply_inventory(admin, uuid4(), document, 'b' * 64, again['fingerprint'])['writes_performed']
    # Failure of one projection rolls back registry, claims, revisions and journals for the whole batch.
    newer = copy.deepcopy(document)
    newer['finished_at'] = '2026-10-12T14:00:00Z'
    newer_review = review_inventory(admin, newer, 'c' * 64)
    receipts = ProviderInventoryImport.objects.count()
    with patch.object(VirtualMachine, 'save', side_effect=ValidationError('fixture refusal')):
        rejected(lambda: apply_inventory(admin, uuid4(), newer, 'c' * 64, newer_review['fingerprint']), (ValidationError,))
    assert ProviderInventoryImport.objects.count() == receipts
    assert set(ProviderInventory.objects.values_list('evidence_digest', flat=True)) == {'b' * 64}
    # An intervening host change invalidates the review, even on an unrelated field.
    Device.objects.filter(pk=obj.pk).update(name='concurrent-host-change')
    rejected(lambda: apply_inventory(admin, uuid4(), newer, 'c' * 64, newer_review['fingerprint']), (ValueError,))
    newer_review = review_inventory(admin, newer, 'c' * 64)
    apply_inventory(admin, uuid4(), newer, 'c' * 64, newer_review['fingerprint'])
    rejected(lambda: review_inventory(admin, document, 'b' * 64), (ValueError,))
    runpy.run_path(str(Path(__file__).with_name('netbox_provider_ipam_scenario.py')), init_globals=globals())
    runpy.run_path(str(Path(__file__).with_name('netbox_resource_registry_scenario.py')), init_globals=globals())
    runpy.run_path(str(Path(__file__).with_name('netbox_provider_reconcile_scenario.py')), init_globals=globals())
    runpy.run_path(str(Path(__file__).with_name('netbox_selectel_mvp_scenario.py')), init_globals=globals())
    transaction.set_rollback(True)
print('Provider schema, server inventory, atomic rollback, stale review, replay, permissions and PostgreSQL protection OK; fixtures rolled back')
