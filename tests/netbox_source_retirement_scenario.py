"""Full-tree atomic rollback/receipt tests against the isolated real NetBox DB."""
import runpy
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
runpy.run_path(str(Path(__file__).with_name('netbox_model_scope_scenario.py')))
from django.db import connection,connections
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from users.models import ObjectPermission
from virtualization.models import ClusterType,Cluster,VirtualMachine,VMInterface
from dcim.models import Site,Manufacturer,DeviceType,DeviceRole,Device
from netbox_guard.dependencies import MODELS,DependencyGuardBlocked
from netbox_guard.models import CreationClaim,CreationReceipt,RetirementIntent,RetirementReceipt
from netbox_guard.service import create_owned
from netbox_guard.source_retirement import review_source,retire_source
assert connection.settings_dict['NAME']=='netbox_sync_guard_test'
tag='source-retire-'+uuid4().hex;source='esxi-'+uuid4().hex
user=get_user_model().objects.create(username=tag,is_active=True)
permission=ObjectPermission.objects.create(name=tag,actions=['create','retire'],constraints={'source_instance':source})
permission.object_types.set([ContentType.objects.get_for_model(CreationReceipt),ContentType.objects.get_for_model(RetirementIntent)])
permission.users.add(user)
add=ObjectPermission.objects.create(name=tag+'-add',actions=['add'])
add.object_types.set([ContentType.objects.get_for_model(apps.get_model(label)) for label in MODELS.values()]);add.users.add(user)
kind=ClusterType.objects.create(name=tag,slug=tag)
site=Site.objects.create(name=tag,slug=tag)
manufacturer=Manufacturer.objects.create(name=tag,slug=tag)
dtype=DeviceType.objects.create(manufacturer=manufacturer,model=tag,slug=tag)
role=DeviceRole.objects.create(name=tag,slug=tag)
clusters=[]
def create(resource,values,cluster=None): return create_owned(user,uuid4(),source,resource,values,cluster=cluster)
def refused(code,call):
    try: call()
    except DependencyGuardBlocked as exc: assert str(exc)==code,(code,str(exc))
    else: raise AssertionError('expected '+code)
def tree(manual=False):
    label=tag+'-'+str(len(clusters))
    cluster=Cluster.objects.create(name=label,type=kind) if manual else create('cluster',{'name':label,'type':kind})
    clusters.append(cluster.pk)
    host=create('device',{'name':label,'site':site,'role':role,'device_type':dtype,'cluster':cluster},cluster.pk)
    physical=create('interface',{'name':'vmk0','type':'virtual','device':host},cluster.pk)
    create('ip',{'address':'192.0.2.181/24','assigned_object':physical},cluster.pk)
    vm=create('vm',{'name':'owned','cluster':cluster,'device':host},cluster.pk)
    nic=create('vminterface',{'name':'eth0','virtual_machine':vm},cluster.pk)
    create('ip',{'address':'192.0.2.182/24','assigned_object':nic},cluster.pk)
    create('mac',{'mac_address':'02:00:00:00:81:22','assigned_object':nic},cluster.pk)
    create('disk',{'name':'disk0','size':1024,'virtual_machine':vm},cluster.pk)
    return cluster,host,vm
try:
    cluster,host,vm=tree()
    intent=review_source(user,uuid4(),source,cluster.pk)
    assert len(intent.manifest['objects'])==9
    manual=VMInterface.objects.create(virtual_machine=vm,name='manual')
    refused('CREATION_OWNERSHIP_UNPROVEN',lambda:retire_source(user,intent.pk,intent.digest))
    assert Device.objects.filter(pk=host.pk).exists() and VirtualMachine.objects.filter(pk=vm.pk).exists()
    manual.delete()
    # A failure in the final receipt rolls back VM and host phases too.
    with patch.object(RetirementReceipt.objects,'create',side_effect=RuntimeError('fixture')):
        try: retire_source(user,intent.pk,intent.digest)
        except RuntimeError: pass
        else: raise AssertionError('receipt failure not reached')
    assert Cluster.objects.filter(pk=cluster.pk).exists()
    assert Device.objects.filter(pk=host.pk).exists() and VirtualMachine.objects.filter(pk=vm.pk).exists()
    assert CreationClaim.objects.filter(source_instance=source).count()==9
    receipt=retire_source(user,intent.pk,intent.digest)
    assert len(receipt.deleted)==9 and not Cluster.objects.filter(pk=cluster.pk).exists()
    assert not CreationClaim.objects.filter(source_instance=source).exists()
    assert retire_source(user,intent.pk,intent.digest).pk==receipt.pk
    # Re-add/re-sync creates a genuinely new generation; old intent cannot delete it.
    new_cluster,new_host,new_vm=tree()
    assert retire_source(user,intent.pk,intent.digest).pk==receipt.pk
    assert VirtualMachine.objects.filter(pk=new_vm.pk).exists()
    fresh=review_source(user,uuid4(),source,new_cluster.pk)
    retire_source(user,fresh.pk,fresh.digest)
    # Manual placement survives while every exclusively created child retires.
    manual_cluster,manual_host,manual_vm=tree(manual=True)
    fresh=review_source(user,uuid4(),source,manual_cluster.pk)
    assert fresh.manifest['retained_cluster']
    retire_source(user,fresh.pk,fresh.digest)
    assert Cluster.objects.filter(pk=manual_cluster.pk).exists()
    assert not Device.objects.filter(pk=manual_host.pk).exists()
    assert Site.objects.filter(pk=site.pk).exists() and ClusterType.objects.filter(pk=kind.pk).exists()
    print('PASS full source: host/VM/NIC/IP/MAC/disk atomic deletion; manual child refusal; receipt rollback; lost-response replay; new generation retained; manual cluster/catalog retained')
finally:
    VirtualMachine.objects.filter(cluster_id__in=clusters).delete()
    Device.objects.filter(cluster_id__in=clusters).delete()
    Cluster.objects.filter(pk__in=clusters).delete()
    RetirementReceipt.objects.filter(intent__source_instance=source).delete()
    RetirementIntent.objects.filter(source_instance=source).delete()
    CreationReceipt.objects.filter(source_instance=source).delete()
    CreationClaim.objects.filter(source_instance=source).delete()
    add.delete();permission.delete();user.delete();kind.delete()
    dtype.delete();manufacturer.delete();role.delete();site.delete()
    connections.close_all()
