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
    transaction.set_rollback(True)
print('Provider schema, bindings, stale review, replay, permission and PostgreSQL overwrite/delete protection OK; fixtures rolled back')
