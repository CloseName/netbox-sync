"""Execute only in the separate local NetBox guard DB with pinned image/plugin."""
import runpy
import os, json, time
import threading
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
runpy.run_path(str(Path(__file__).with_name('netbox_model_scope_scenario.py')))
from django.db import connection, connections
from django.contrib.auth import get_user_model
from virtualization.models import ClusterType, Cluster, VirtualMachine, VMInterface
from ipam.models import IPAddress
from netbox_guard.dependencies import DependencyGuardBlocked
from netbox_guard.models import CreationClaim, CreationReceipt, RetirementIntent, RetirementReceipt
from netbox_guard.service import create_owned, review, retire
assert connection.settings_dict['NAME'] == 'netbox_sync_guard_test'
assert connection.settings_dict['HOST'] == '127.0.0.1'
User=get_user_model()
tag='guard-' + uuid4().hex
admin=User.objects.create(username=tag, is_active=True)
viewer=User.objects.create(username=tag+'-viewer', is_active=True)
kind=ClusterType.objects.create(name=tag,slug=tag)
source='esxi-'+uuid4().hex
from users.models import ObjectPermission
from django.contrib.contenttypes.models import ContentType
permission=ObjectPermission.objects.create(name=tag, actions=['create','retire'], constraints={'source_instance':source})
permission.object_types.set([ContentType.objects.get_for_model(CreationReceipt),ContentType.objects.get_for_model(RetirementIntent)])
permission.users.add(admin)
from django.apps import apps
from netbox_guard.dependencies import MODELS
add_permission=ObjectPermission.objects.create(name=tag+'-add',actions=['add'])
add_permission.object_types.set([ContentType.objects.get_for_model(apps.get_model(label)) for label in MODELS.values()])
add_permission.users.add(admin)
assert not admin.has_perm('virtualization.delete_virtualmachine')
clusters=[]
checks=[]


def refuse(code, function):
    try: function()
    except DependencyGuardBlocked as exc:
        assert str(exc)==code,(code,str(exc))
    else: raise AssertionError('Expected '+code)
    checks.append(code)


def create(resource, values, cluster=None, nonce=None):
    return create_owned(admin,nonce or uuid4(),source,resource,values,cluster=cluster)


def tree():
    cluster=create('cluster',{'name':tag+'-'+str(len(clusters)), 'type':kind})
    clusters.append(cluster.pk)
    vm=create('vm',{'name':'owned-vm', 'cluster':cluster},cluster.pk)
    nic=create('vminterface',{'name':'owned-nic','virtual_machine':vm},cluster.pk)
    address=create('ip',{'address':'192.0.2.194/24','assigned_object':nic},cluster.pk)
    return cluster,vm,nic,address


try:
    refuse('PERMISSION_DENIED',lambda:create_owned(viewer,uuid4(),source,'cluster',{'name':tag,'type':kind}))
    refuse('PERMISSION_DENIED',lambda:create_owned(admin,uuid4(),'esxi-not-authorized','cluster',{'name':tag+'-forbidden','type':kind}))
    assert not Cluster.objects.filter(name=tag+'-forbidden').exists()
    cluster,vm,nic,address=tree()
    # Receipt retry cannot create another object, even after response loss.
    nonce=uuid4(); values={'name':'second-owned-vm','cluster':cluster}
    extra=create('vm',values,cluster.pk,nonce)
    assert create('vm',values,cluster.pk,nonce).pk==extra.pk
    refuse('REQUEST_CONFLICT',lambda:create('vm',{**values,'name':'changed'},cluster.pk,nonce))
    refuse('PERMISSION_DENIED',lambda:review(viewer,uuid4(),source,cluster.pk))
    # Placement and foreign provenance are fenced independently of names.
    placement_intent=review(admin,uuid4(),source,cluster.pk,root=('vm',vm.pk))
    old_name=cluster.name
    Cluster.objects.filter(pk=cluster.pk).update(name=old_name+'-changed')
    refuse('PLACEMENT_CHANGED',lambda:retire(admin,placement_intent.nonce,placement_intent.digest))
    Cluster.objects.filter(pk=cluster.pk).update(name=old_name)
    VirtualMachine.objects.filter(pk=vm.pk).update(custom_field_data={'sync_identities':[{'schema':'v2','instance':'esxi-foreign','kind':'vm','external_id':'fixture','type':'esxi'}]})
    refuse('OWNERSHIP_CONFLICT',lambda:review(admin,uuid4(),source,cluster.pk,root=('vm',vm.pk)))
    VirtualMachine.objects.filter(pk=vm.pk).update(custom_field_data={})
    # Same placement does not establish ownership after a manual reassignment.
    manual_vm=VirtualMachine.objects.create(name='manual-parent',cluster=cluster)
    manual_nic=VMInterface.objects.create(name='manual-parent-nic',virtual_machine=manual_vm)
    original_type=address.assigned_object_type
    original_id=address.assigned_object_id
    address.assigned_object=manual_nic;address.save()
    refuse('OWNERSHIP_CONFLICT',lambda:review(admin,uuid4(),source,cluster.pk,root=('ip',address.pk)))
    # An incomplete v2 dictionary is not a valid retained-parent identity.
    VMInterface.objects.filter(pk=manual_nic.pk).update(custom_field_data={'sync_identities':[{'schema':'v2','instance':source}]})
    refuse('OWNERSHIP_CONFLICT',lambda:review(admin,uuid4(),source,cluster.pk,root=('ip',address.pk)))
    address.assigned_object_type=original_type;address.assigned_object_id=original_id;address.save()
    manual_vm.delete() # exact locally created fixture only
    intent=review(admin,uuid4(),source,cluster.pk,root=('vm',vm.pk))
    # Foreign/manual dependency added after preview must invalidate the manifest.
    foreign=VMInterface.objects.create(name='manual',virtual_machine=vm)
    refuse('DEPENDENCIES_CHANGED',lambda:retire(admin,intent.nonce,intent.digest))
    assert Cluster.objects.filter(pk=cluster.pk).exists()
    refuse('CREATION_OWNERSHIP_UNPROVEN',lambda:review(admin,uuid4(),source,cluster.pk,root=('vm',vm.pk)))
    foreign.delete() # exact fixture ID, never a product operation
    intent=review(admin,uuid4(),source,cluster.pk,root=('vm',vm.pk))
    # Simulate failure storing receipt: infrastructure deletion and claims roll back.
    with patch.object(RetirementReceipt.objects,'create',side_effect=RuntimeError('controlled receipt failure')):
        try: retire(admin,intent.nonce,intent.digest)
        except RuntimeError as exc: assert str(exc)=='controlled receipt failure'
        else: raise AssertionError('Failure injection not reached')
    assert Cluster.objects.filter(pk=cluster.pk).exists()
    assert CreationClaim.objects.filter(resource='ip',object_id=address.pk).exists()
    assert not RetirementReceipt.objects.filter(intent=intent).exists()
    checks.append('receipt failure rolls back objects and creation claims')
    receipt=retire(admin,intent.nonce,intent.digest)
    assert Cluster.objects.filter(pk=cluster.pk).exists()
    assert not VirtualMachine.objects.filter(pk=vm.pk).exists()
    assert VirtualMachine.objects.filter(pk=extra.pk).exists()
    assert not IPAddress.objects.filter(pk=address.pk).exists()
    assert not CreationClaim.objects.filter(resource='ip',object_id=address.pk).exists()
    assert retire(admin,intent.nonce,intent.digest).pk==receipt.pk
    assert review(admin,intent.nonce,source,cluster.pk,root=('vm',vm.pk)).digest==intent.digest
    assert RetirementReceipt.objects.filter(intent=intent).count()==1
    checks.append('retire + lost-response retry returns same durable receipt')
    if os.environ.get('NETBOX_SYNC_GUARD_BACKUP_GATE') == '1':
        # Permit an isolated database template copy; no transaction is active.
        connections.close_all()
        gate=Path('/guard-gate')
        (gate/'ready.json').write_text(json.dumps({'nonce':str(intent.nonce),'digest':intent.digest,
            'source':source,'actor':admin.pk,'cluster':cluster.pk,'remaining_vm':extra.pk}),encoding='utf-8')
        deadline=time.monotonic()+120
        while not (gate/'done').exists():
            if time.monotonic()>deadline: raise AssertionError('Backup test coordination deadline exceeded')
            time.sleep(.1)
        assert (gate/'done').read_text()=='passed'
        checks.append('pg_dump/pg_restore retains claims and receipt; restored retry does not write')

    extra_intent=review(admin,uuid4(),source,cluster.pk,root=('vm',extra.pk))
    retire(admin,extra_intent.nonce,extra_intent.digest)
    cluster_intent=review(admin,uuid4(),source,cluster.pk)
    retire(admin,cluster_intent.nonce,cluster_intent.digest)
    assert not Cluster.objects.filter(pk=cluster.pk).exists()
    assert not CreationClaim.objects.filter(cluster_id=cluster.pk).exists()
    checks.append('child receipts then empty cluster retirement retain an exact completion chain')
    refuse('CREATED_OBJECT_NO_LONGER_OWNED',lambda:create('vm',values,cluster.pk,nonce))
    # A fresh generation may be created under a fresh explicit request.
    cluster,vm,nic,address=tree()
    intent=review(admin,uuid4(),source,cluster.pk,root=('vm',vm.pk))
    results=[]; errors=[]; barrier=threading.Barrier(2)
    def concurrent():
        try:
            user=User.objects.get(pk=admin.pk)
            barrier.wait(timeout=5)
            results.append(str(retire(user,intent.nonce,intent.digest).pk))
        except Exception as exc: errors.append(type(exc).__name__+':'+str(exc))
        finally: connections['default'].close()
    threads=[threading.Thread(target=concurrent) for _ in range(2)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(20)
    assert not errors and len(results)==2 and len(set(results))==1,errors
    assert not VirtualMachine.objects.filter(pk=vm.pk).exists()
    checks.append('two concurrent confirmations delete once')
    # Ordinary deletion invalidates the claim; ID/name reuse does not recreate proof.
    cluster,vm,nic,address=tree()
    old=vm.pk
    vm.delete()
    assert not CreationClaim.objects.filter(resource='vm',object_id=old).exists()
    replacement=VirtualMachine.objects.create(pk=old,name='owned-vm',cluster=cluster)
    refuse('CREATION_OWNERSHIP_UNPROVEN',lambda:review(admin,uuid4(),source,cluster.pk,root=('vm',old)))
    assert replacement.pk==old
    checks.append('ordinary delete and ID reuse cannot inherit ownership')
    # A manually supplied placement is retained; its own claimed VM may retire.
    manual_cluster=Cluster.objects.create(name=tag+'-manual',type=kind)
    clusters.append(manual_cluster.pk)
    claimed_vm=create('vm',{'name':'owned-in-manual','cluster':manual_cluster},manual_cluster.pk)
    leaf_intent=review(admin,uuid4(),source,manual_cluster.pk,root=('vm',claimed_vm.pk))
    retire(admin,leaf_intent.nonce,leaf_intent.digest)
    assert Cluster.objects.filter(pk=manual_cluster.pk).exists()
    refuse('CREATION_OWNERSHIP_UNPROVEN',lambda:review(admin,uuid4(),source,manual_cluster.pk))
    checks.append('manual placement retained while its source-created child can retire')
    assert ClusterType.objects.filter(pk=kind.pk).exists()
    checks.append('shared catalog retained')
finally:
    # Exact test-owned IDs/source in the separate guard DB, no global cleanup.
    VirtualMachine.objects.filter(cluster_id__in=clusters).delete()
    Cluster.objects.filter(pk__in=clusters).delete()
    RetirementReceipt.objects.filter(intent__source_instance=source).delete()
    RetirementIntent.objects.filter(source_instance=source).delete()
    CreationReceipt.objects.filter(source_instance=source).delete()
    CreationClaim.objects.filter(source_instance=source).delete()
    add_permission.delete(); permission.delete(); kind.delete(); admin.delete(); viewer.delete()
print('NetBox retirement protocol passed:', '; '.join(checks))
