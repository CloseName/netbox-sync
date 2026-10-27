"""Independent PostgreSQL transactions. Disposable model harness ONLY."""
import copy
import runpy
from pathlib import Path
from uuid import uuid4
runpy.run_path(str(Path(__file__).with_name('netbox_model_scope_scenario.py')))
from django.conf import settings
from django.db import connection
from django.test import override_settings
from django.contrib.auth import get_user_model
from virtualization.models import VirtualMachine, VMInterface
from ipam.models import IPAddress
from dcim.models import Site
from netbox_guard.provider_service import review_binding, apply_binding
from netbox_guard.provider_schema import configure_provider_fields
from netbox_guard.provider_lifecycle import review, execute
from netbox_guard.models import ProviderBinding, ProviderCreatedObject, ProviderAccountFence, ProviderDetachedResource
from netbox_guard.provider_policy import identity
assert connection.settings_dict['NAME']=='netbox_sync_guard_test'
assert connection.settings_dict['HOST']=='127.0.0.1'
assert not connection.in_atomic_block
configure_provider_fields()
account=str(uuid4().int)[:20]
admin=get_user_model().objects.create(username='lifecycle-'+uuid4().hex,is_superuser=True,is_active=True)
config=copy.deepcopy(settings.PLUGINS_CONFIG)
config.setdefault('netbox_guard',{})['selectel_native_reconcile']=True
addresses=list(IPAddress.objects.order_by('pk').values())

def bind(vm,native,created=False):
    ident=dict(account=account,kind='cloud_vm',native_id=native,project='test',region='test')
    spec=dict(resource='vm',object_id=vm.pk,identity=ident,serial=None,reason='isolated scenario',evidence_digest='a'*64)
    apply_binding(admin,uuid4(),spec,review_binding(admin,spec)['fingerprint'])
    if created:
        ProviderCreatedObject.objects.create(account=account,model_label=vm._meta.label_lower,
            object_id=vm.pk,object_created=vm.created,provider_key=identity(ident,'vm'))
    return identity(ident,'vm')

with override_settings(PLUGINS_CONFIG=config):
    site=Site.objects.create(name='lifecycle-'+account, slug='lifecycle-'+account)
    adopted=VirtualMachine.objects.create(name='adopted-'+account, site=site)
    owned=VirtualMachine.objects.create(name='owned-'+account, site=site)
    detached=VirtualMachine.objects.create(name='detached-'+account, site=site)
    bind(adopted,'adopted'); bind(owned,'owned',True); key=bind(detached,'detached',True)
    nic=VMInterface.objects.create(virtual_machine=detached,name='external-interface')
    plan=review(admin,account,'delete')
    assert any(b['reason']=='foreign_dependencies_or_sync_source' for b in plan['blockers'])
    detachment=review(admin,account,'detach',key)
    execute(admin,account,'detach',uuid4(),detachment['fingerprint'],key)
    assert ProviderDetachedResource.objects.filter(pk=key).exists()
    assert not ProviderCreatedObject.objects.filter(account=account,object_id=detached.pk,model_label=detached._meta.label_lower).exists()
    detached.refresh_from_db(); assert not any(k.startswith('selectel_') for k in detached.custom_field_data)
    assert VMInterface.objects.get(pk=nic.pk).virtual_machine_id==detached.pk
    plan=review(admin,account,'delete')
    assert not plan['blockers'] and [r['id'] for r in plan['delete']]==[owned.pk]
    owned.description='changed after review'; owned.save(update_fields=['description'])
    try: execute(admin,account,'delete',uuid4(),plan['fingerprint'])
    except ValueError as exc: assert str(exc)=='PROVIDER_REVIEW_STALE'
    else: raise AssertionError('Stale removal accepted')
    assert ProviderBinding.objects.filter(account=account).count()==2
    plan=review(admin,account,'delete'); nonce=uuid4()
    result=execute(admin,account,'delete',nonce,plan['fingerprint'])
    assert result['writes_performed'] and not VirtualMachine.objects.filter(pk=owned.pk).exists()
    assert VirtualMachine.objects.filter(pk__in=[adopted.pk,detached.pk]).count()==2
    assert not ProviderBinding.objects.filter(account=account).exists()
    assert execute(admin,account,'delete',nonce,plan['fingerprint'])['replayed']
    assert ProviderAccountFence.objects.get(pk=account).deleted
    try: bind(adopted,'late-write')
    except ValueError as exc: assert str(exc)=='PROVIDER_ACCOUNT_DELETED'
    else: raise AssertionError('Late write after removal accepted')
    activation=review(admin,account,'activate')
    execute(admin,account,'activate',uuid4(),activation['fingerprint'])
    assert not ProviderAccountFence.objects.get(pk=account).deleted
    assert list(IPAddress.objects.order_by('pk').values())==addresses
print('Selectel lifecycle: dependencies, detach, stale review, deletion, replay, late-write fence, activation and unchanged IPs OK')

# Unowned V1 placement can be referenced, but account removal cannot own/delete it.
from dcim.models import Region
from netbox_guard.provider_policy import digest
from netbox_guard.provider_placement import resolve
legacy_account = str(uuid4().int)[:20]
scope = digest([legacy_account, 'r'])[:16]
legacy_region = Region.objects.create(name=f'Selectel / {legacy_account} / r', slug='selectel-'+scope)
legacy_site = Site.objects.create(name=f'Selectel / {legacy_account} / Zone', region=legacy_region,
    slug='selectel-'+digest([scope, 'Zone'])[:16])
legacy_snapshot = dict(identity=dict(account=legacy_account,region='r'), sections={
    'placement':dict(status='collected',data=dict(uuid='zone',name='Zone'))})
with override_settings(PLUGINS_CONFIG=config):
    assert resolve(admin, legacy_snapshot).pk == legacy_site.pk
    assert not ProviderCreatedObject.objects.filter(account=legacy_account).exists()
    deletion = review(admin, legacy_account, 'delete')
    assert deletion['delete'] == [] and not deletion['blockers']
    execute(admin, legacy_account, 'delete', uuid4(), deletion['fingerprint'])
    assert Region.objects.filter(pk=legacy_region.pk).exists()
    assert Site.objects.filter(pk=legacy_site.pk, region_id=legacy_region.pk).exists()
    assert list(IPAddress.objects.order_by('pk').values()) == addresses
print('Legacy placement: reuse never grants deletion ownership; IDs and IPs retained OK')

# Repeat real account import/delete/activate three times. The manually existing
# chassis is re-adopted by hardware identity; cloud cards are created once per cycle.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from django.utils import timezone
from dcim.models import Device, DeviceRole, DeviceType, Manufacturer
from django.db.models.deletion import Collector
from netbox_guard.account_import import import_account
from netbox_guard.models import ProviderInventory, ProviderResourceRegistry
from tools.selectel_audit.resource_registry import registry
fixture = runpy.run_path(str(Path(__file__).with_name('selectel_inventory_fixture.py')))['fixture']
cycle_account = str(uuid4().int)[:20]
# NetBox queues nullable relation updates even for a completely empty Site.
# These empty querysets must not be mistaken for writes to foreign objects.
empty_site = Site.objects.create(name='empty-'+cycle_account, slug='empty-'+cycle_account)
empty_collector = Collector(using=connection.alias)
empty_collector.collect([empty_site])
assert empty_collector.field_updates
assert not any(bool(group) for groups in empty_collector.field_updates.values() for group in groups)
print('Empty Site deletion has queued field updates but no affected rows OK')
manufacturer = Manufacturer.objects.create(name='cycle-'+cycle_account, slug='cycle-'+cycle_account)
device_type = DeviceType.objects.create(manufacturer=manufacturer, model='cycle-'+cycle_account,
    slug='cycle-'+cycle_account)
device_role = DeviceRole.objects.create(name='cycle-'+cycle_account, slug='cycle-'+cycle_account)
chassis = Device.objects.create(name='existing-'+cycle_account, serial='CYCLE-'+cycle_account,
    site=site, device_type=device_type, role=device_role)
original_device_id = chassis.pk
retained_site_id = None
old_delete = old_activate = None
with override_settings(PLUGINS_CONFIG=config):
    for cycle in range(3):
        doc = fixture(cycle_account)
        doc['finished_at'] = timezone.now().isoformat()
        for dataset in doc['datasets']:
            if dataset['service'] == 'dedicated' and dataset['kind'] == 'resources':
                dataset['items'][0].update(serial=chassis.serial, user_desc='Provider chassis '+cycle_account)
            if dataset['service'] == 'compute' and dataset['kind'] == 'servers':
                dataset['items'][0].update(name='Cloud cycle '+cycle_account, status='ACTIVE')
        payload = dict(account=cycle_account, nonce=str(uuid4()), document=doc, registry=registry(doc))
        result = import_account(admin, payload)
        assert result['native_adopted'] == 1 and result['native_created'] == 1, result
        chassis.refresh_from_db()
        if retained_site_id is None:
            retained_site_id = chassis.site_id
        assert chassis.site_id == retained_site_id
        binding_ids = set(ProviderBinding.objects.filter(account=cycle_account).values_list('resource','object_id'))
        assert ('device', original_device_id) in binding_ids
        cloud_id = next(pk for kind, pk in binding_ids if kind == 'vm')
        assert import_account(admin, payload)['replayed']
        doc['finished_at'] = timezone.now().isoformat()
        again = import_account(admin, dict(account=cycle_account,nonce=str(uuid4()),document=doc,registry=registry(doc)))
        assert again['native_created'] == again['native_adopted'] == 0
        assert set(ProviderBinding.objects.filter(account=cycle_account).values_list('resource','object_id')) == binding_ids
        if old_delete:
            try: execute(admin, cycle_account, 'delete', uuid4(), old_delete['fingerprint'])
            except ValueError as exc: assert str(exc) == 'PROVIDER_REVIEW_STALE'
            else: raise AssertionError('Prior-cycle deletion review accepted')
        deletion = review(admin, cycle_account, 'delete')
        assert not deletion['blockers'], deletion
        deleted_nonce = uuid4()
        execute(admin, cycle_account, 'delete', deleted_nonce, deletion['fingerprint'])
        assert Device.objects.filter(pk=original_device_id).exists()
        assert not VirtualMachine.objects.filter(pk=cloud_id).exists()
        for model in (ProviderInventory, ProviderBinding, ProviderCreatedObject, ProviderResourceRegistry):
            assert not model.objects.filter(account=cycle_account).exists(), model
        chassis.refresh_from_db()
        assert not any(k.startswith('selectel_') for k in chassis.custom_field_data)
        assert list(IPAddress.objects.order_by('pk').values()) == addresses
        if old_activate:
            try: execute(admin, cycle_account, 'activate', uuid4(), old_activate['fingerprint'])
            except ValueError as exc: assert str(exc) == 'PROVIDER_REVIEW_STALE'
            else: raise AssertionError('Prior-cycle activation review accepted')
        activation = review(admin, cycle_account, 'activate')
        execute(admin, cycle_account, 'activate', uuid4(), activation['fingerprint'])
        # A lost old deletion response is only a receipt replay, never another purge.
        assert execute(admin, cycle_account, 'delete', deleted_nonce, deletion['fingerprint'])['replayed']
        assert not ProviderAccountFence.objects.get(pk=cycle_account).deleted
        old_delete, old_activate = deletion, activation
        print('Selectel cycle', cycle + 1, 'import/delete/reactivate with same adopted Device and Site OK')
print('Selectel repeated lifecycle: three imports/deletions/reconnections, stable chassis adoption, no duplicate clouds, old reviews refused and IPs unchanged OK')

# Historical baseline changes only an audit/fence receipt, never native rows.
from netbox_guard.account_import import import_account
from netbox_guard.models import ProviderLifecycleReceipt
run = str(uuid4())
with override_settings(PLUGINS_CONFIG=config):
    before = list(VirtualMachine.objects.order_by('pk').values())
    baseline = review(admin, account, 'baseline', run)
    adopted.description = 'concurrent baseline edit'
    adopted.save(update_fields=['description'])
    try: execute(admin, account, 'baseline', uuid4(), baseline['fingerprint'], run)
    except ValueError as exc: assert str(exc) == 'PROVIDER_REVIEW_STALE'
    else: raise AssertionError('Stale baseline accepted')
    baseline = review(admin, account, 'baseline', run)
    before = list(VirtualMachine.objects.order_by('pk').values())
    result = execute(admin, account, 'baseline', uuid4(), baseline['fingerprint'], run)
    assert result['baseline_accepted'] and result['historical_outcome'] == 'unknown'
    assert execute(admin, account, 'baseline', uuid4(), baseline['fingerprint'], run)['replayed']
    assert list(VirtualMachine.objects.order_by('pk').values()) == before
    assert list(IPAddress.objects.order_by('pk').values()) == addresses
    old_payload = dict(account=account, nonce=run,
                       document=dict(account=account,account_verified=True,finished_at='2026-10-26T00:00:00Z'),
                       registry=dict(account=account,observed_at='2026-10-26T00:00:00Z'))
    try: import_account(admin,old_payload)
    except ValueError as exc: assert str(exc) == 'PROVIDER_HISTORICAL_RUN_RETIRED'
    else: raise AssertionError('Historical write passed baseline fence')
print('Selectel historical baseline: stale review, audit, replay, late import fence and native/IP preservation OK')

# Saved hardware evidence executes the reviewed source against PostgreSQL in read-only mode.
import io
import json
import tempfile
from contextlib import redirect_stdout
from unittest.mock import patch
from django.core.management import call_command
from django.db import DatabaseError
from django.utils import timezone
from dcim.models import Device
from netbox_guard.models import ProviderInventory
with tempfile.TemporaryDirectory() as temp:
    call_command('configure_selectel_mvp', output=str(Path(temp) / 'hardware-token.json'), native_resources=True)
shape_account = str(uuid4().int)[:20]
shape_ident = dict(account=shape_account, kind='dedicated', native_id=str(uuid4()), project='', region='')
shape_key = identity(shape_ident, 'device')
ProviderInventory.objects.create(provider_key=shape_key, account=shape_account,
    observed_at=timezone.now(), evidence_digest='a'*64, snapshot=dict(identity=shape_ident, sections={
        'resource': dict(status='collected', data=dict(user_desc='shape test', hw_uuid='PRIVATE-RESOURCE')),
        'hardware': dict(status='collected', data=dict(disk=[dict(serial='PRIVATE-DISK')]))}))
shape_path = Path(__file__).resolve().parents[1] / 'deploy/selectel_hardware_evidence.py'
shapes = runpy.run_path(str(shape_path))
before_shapes = {model: list(model.objects.order_by('pk').values())
                for model in (ProviderInventory, ProviderBinding, Device, VirtualMachine, IPAddress)}
out = io.StringIO()
with redirect_stdout(out):
    call_command('shell', command=shape_path.read_text() + '\nprint(MARKER + json.dumps(read_account(' + repr(shape_account) + ')))', stdout=out)
shape_report = json.loads(out.getvalue().split('SELECTEL_HARDWARE_SHAPE:')[-1])
assert shape_report['resource_count'] == 1 and shape_report['writes_performed'] is False
assert shape_report['resources'][0]['sections']['hardware']['component_serial_counts']['disk']['nonempty_scalar'] == 1
assert 'PRIVATE-' not in out.getvalue()
def try_write(*args):
    ProviderInventory.objects.filter(provider_key=shape_key).update(evidence_digest='b'*64)
    raise AssertionError('Database accepted a write during read-only evidence')
with patch.dict(shapes['read_account'].__globals__, section_shape=try_write):
    try: shapes['read_account'](shape_account)
    except DatabaseError as exc:
        assert 'read-only' in str(exc).lower()
    else: raise AssertionError('Expected read-only transaction refusal')
for model, values in before_shapes.items():
    assert list(model.objects.order_by('pk').values()) == values
print('Selectel stored hardware evidence: actual command, sanitized output, DB-enforced read-only and retained IDs/IPs OK')
