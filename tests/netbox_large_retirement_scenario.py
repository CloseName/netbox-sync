"""Opt-in real NetBox 4.7/PostgreSQL large retirement, isolated fixture only."""
import os, runpy, time, json, faulthandler
from uuid import uuid4
assert os.environ.get('NETBOX_SYNC_ISOLATED_MODEL_TEST') == '1'
runpy.run_path('/app/tests/netbox_model_scope_scenario.py')
faulthandler.dump_traceback_later(900, exit=True)
from django.db import connection
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from users.models import ObjectPermission
from dcim.models import Site, Manufacturer, DeviceType, DeviceRole
from virtualization.models import ClusterType
from netbox_guard.dependencies import MODELS, DependencyGuardBlocked
from netbox_guard.models import CreationClaim, CreationReceipt, RetirementIntent, RetirementReceipt, SourceClosure
from netbox_guard.service import create_owned
from netbox_guard import source_retirement as service
assert connection.settings_dict['NAME']=='netbox_sync_guard_test'
source='large-'+uuid4().hex
user=get_user_model().objects.create(username=source,is_active=True)
permission=ObjectPermission.objects.create(name=source,actions=['add','create','retire'])
permission.object_types.set([ContentType.objects.get_for_model(apps.get_model(label)) for label in MODELS.values()]+[ContentType.objects.get_for_model(model) for model in (CreationReceipt,RetirementIntent)])
permission.users.add(user)
kind=ClusterType.objects.create(name=source,slug=source)
site=Site.objects.create(name=source,slug=source)
manufacturer=Manufacturer.objects.create(name=source,slug=source)
device_type=DeviceType.objects.create(manufacturer=manufacturer,model=source,slug=source)
role=DeviceRole.objects.create(name=source,slug=source)
cluster=create_owned(user,uuid4(),source,'cluster',{'name':source,'type':kind})
def create(kind,values):return create_owned(user,uuid4(),source,kind,values,cluster=cluster.pk)
host=create('device',dict(name=source,site=site,role=role,device_type=device_type,cluster=cluster))
start=time.monotonic()
for index in range(276):
    vm=create('vm',dict(name=f'vm-{index}',cluster=cluster,device=host))
    nic=create('vminterface',dict(name='eth0',virtual_machine=vm))
    if index<273:create('ip',dict(address=f'198.18.{index//250}.{index%250+1}/24',assigned_object=nic))
    if index<272:create('mac',dict(mac_address=f'02:00:00:01:{index//256:02x}:{index%256:02x}',assigned_object=nic))
assert CreationClaim.objects.filter(source_instance=source).count()==1099
print('LARGE fixture: 276 VM, 1099 objects; setup_ms='+str(round((time.monotonic()-start)*1000)),flush=True)
class Profile:
    def __init__(self):self.count=0;self.seconds=0
    def __call__(self,execute,sql,params,many,context):
        start=time.monotonic();self.count+=1
        try:return execute(sql,params,many,context)
        finally:self.seconds+=time.monotonic()-start
# Prove homogeneous Collector batching against the unchanged per-root closure.
# Every experiment below rolls back; no alternate production deletion path.
from django.db import transaction
from django.db.models.deletion import Collector
from netbox_guard.dependencies import _closure, _batch_closure, _database_fence
from netbox_guard.service import _claims
expected, roots = service._inventory(source, cluster.pk, float('inf'))
batch_closure=_batch_closure
profile=Profile();started=time.monotonic()
with connection.execute_wrapper(profile):
    with _database_fence():
        remaining=dict(expected.objects)
        for kind in ('vm','device','cluster'):
            group=[root for root in roots if root[0]==kind]
            if not group:continue
            individual={};updates=set()
            for root in group:
                snapshot,_=_closure([root]);individual.update(snapshot.objects);updates.update(snapshot.field_updates)
            batch,collector=batch_closure(group)
            assert dict(batch.objects)==individual
            assert set(batch.field_updates)==updates
            assert all(remaining.get(key)==value for key,value in batch.objects)
            _claims(batch,source,cluster.pk)
            expected_counts={}
            for key,_ in batch.objects:
                model=MODELS[key.split(':')[0]]
                expected_counts[model]=expected_counts.get(model,0)+1
            count,actual=collector.delete()
            assert actual==expected_counts and count==len(batch.objects)
            for key,_ in batch.objects:remaining.pop(key)
        assert not remaining
        assert not CreationClaim.objects.filter(source_instance=source).exists()
        transaction.set_rollback(True)
assert CreationClaim.objects.filter(source_instance=source).count()==1099
print(json.dumps(dict(phase='batch_equivalence_rolled_back',code='OK',duration_ms=round((time.monotonic()-started)*1000),queries=profile.count)),flush=True)
# A foreign child must be present in both closures and fail unchanged ownership.
vm=apps.get_model(MODELS['vm']).objects.filter(cluster=cluster).first()
foreign=apps.get_model(MODELS['vminterface']).objects.create(virtual_machine=vm,name='foreign-preserved')
try:
    with _database_fence():
        for closure in (_closure,batch_closure):
            snapshot,_=closure([['vm',vm.pk]])
            assert ('vminterface:'+str(foreign.pk)) in dict(snapshot.objects)
            try:_claims(snapshot,source,cluster.pk)
            except DependencyGuardBlocked as error:assert str(error)=='CREATION_OWNERSHIP_UNPROVEN'
            else:raise AssertionError('foreign child accepted')
    assert type(foreign).objects.filter(pk=foreign.pk).exists()
finally:foreign.delete()
print('PASS unchanged ownership blocks foreign child for both collectors',flush=True)
# Fail after the actual large deletion and prove the receipt/closure transaction
# restores every object, then continue the SAME intent after process interruption.
from unittest.mock import patch
intent=service.review_source(user,uuid4(),source,cluster.pk)
with patch.object(RetirementReceipt.objects,'create',side_effect=RuntimeError('isolated receipt interruption')):
    try:service.retire_source(user,intent.pk,intent.digest)
    except RuntimeError as error:assert str(error)=='isolated receipt interruption'
    else:raise AssertionError('Interrupted deletion committed')
assert CreationClaim.objects.filter(source_instance=source).count()==1099
assert not SourceClosure.objects.filter(source_instance=source).exists()
assert not RetirementReceipt.objects.filter(intent=intent).exists()
print('PASS large deletion interrupted before receipt: 1099 objects and claims rolled back',flush=True)
# Expiration inside the real Collector SQL loop must roll back and release the
# namespace lock, so the original nonce can then complete on this connection.
from netbox_guard.retirement_diagnostics import set_deadline
from unittest.mock import patch
from django.db.models.deletion import Collector
actual_delete=Collector.delete
def expired_delete(collector):
    set_deadline(time.monotonic()-1)
    return actual_delete(collector)
with patch.object(Collector,'delete',expired_delete):
    try:service.retire_source(user,intent.pk,intent.digest)
    except DependencyGuardBlocked as error:assert str(error)=='RETIREMENT_DEADLINE'
    else:raise AssertionError('Collector ignored expired budget')
assert CreationClaim.objects.filter(source_instance=source).count()==1099
assert not SourceClosure.objects.filter(source_instance=source).exists()
print('PASS deadline within Collector SQL: atomic rollback and original nonce retained',flush=True)
for phase in ('review','execute'):
    profile=Profile();start=time.monotonic();code='OK'
    try:
        with connection.execute_wrapper(profile):
            if phase=='review':service.review_source(user,intent.pk,source,cluster.pk)
            else:receipt=service.retire_source(user,intent.pk,intent.digest)
    except DependencyGuardBlocked as exc:code=str(exc)
    print(json.dumps(dict(phase=phase,code=code,duration_ms=round((time.monotonic()-start)*1000),queries=profile.count,sql_ms=round(profile.seconds*1000))),flush=True)
    if code!='OK':
        assert not RetirementReceipt.objects.filter(intent__source_instance=source).exists()
        assert not SourceClosure.objects.filter(source_instance=source).exists()
        assert CreationClaim.objects.filter(source_instance=source).count()==1099
        print('PASS atomic rollback: all 1099 claims and objects retained',flush=True)
        raise AssertionError('Large retirement did not complete: '+code)
    if phase=='execute':assert profile.count<20000, profile.count
else:
    assert len(receipt.deleted)==1099
    assert not CreationClaim.objects.filter(source_instance=source).exists()
    assert service.retire_source(user,intent.pk,intent.digest).pk==receipt.pk
    print('PASS real large retirement: 1099 deleted, same-nonce receipt retry',flush=True)
faulthandler.cancel_dump_traceback_later()
