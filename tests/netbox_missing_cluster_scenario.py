"""Real NetBox-only regression, invoked inside the owned production fixture."""
def exercise():
    from uuid import uuid4
    from unittest.mock import patch
    from django.db import connection
    from django.contrib.auth import get_user_model
    from django.contrib.contenttypes.models import ContentType
    from virtualization.models import Cluster, ClusterType, VirtualMachine
    from users.models import ObjectPermission
    from netbox_guard.models import CreationClaim, CreationReceipt, RetirementIntent, RetirementReceipt, SourceClosure
    from netbox_guard.service import create_owned, _cluster_fingerprint
    from netbox_guard import source_retirement as service
    from netbox_guard.dependencies import DependencyGuardBlocked
    from netbox_guard.api.views import _public
    assert connection.settings_dict['NAME']=='netbox_sync_guard_test'
    source='missing-'+uuid4().hex; sources=[source]
    user=get_user_model().objects.create(username=source,is_active=True)
    permission=ObjectPermission.objects.create(name=source,actions=['create','retire'],constraints={'source_instance__startswith':source})
    permission.object_types.set([ContentType.objects.get_for_model(CreationReceipt),ContentType.objects.get_for_model(RetirementIntent)])
    permission.users.add(user)
    add=ObjectPermission.objects.create(name=source+'-add',actions=['add'])
    add.object_types.set([ContentType.objects.get_for_model(Cluster),ContentType.objects.get_for_model(VirtualMachine)]);add.users.add(user)
    kind=ClusterType.objects.create(name=source,slug=source)
    objects=[]
    def absent_cluster():
        cluster=create_owned(user,uuid4(),source,'cluster',{'name':source+'-'+uuid4().hex,'type':kind})
        objects.append(cluster)
        return cluster
    def refused(fn):
        try:fn()
        except DependencyGuardBlocked as exc:assert str(exc)=='SOURCE_OBJECTS_REMAIN',str(exc)
        else:raise AssertionError('Detached inventory was ignored')
    try:
        cluster=absent_cluster();identifier=cluster.pk;cluster.delete()
        # Exact original failing chain: empty _inventory then required fingerprint.
        snapshot,roots=service._inventory(source,identifier, float('inf'))
        assert not snapshot.objects and not roots
        try:_cluster_fingerprint(identifier)
        except DependencyGuardBlocked as exc:assert str(exc)=='OBJECT_MISSING'
        else:raise AssertionError('Original missing-cluster condition not reproduced')
        intent=service.review_source(user,uuid4(),source,identifier)
        assert intent.manifest['cluster_missing'] and not intent.manifest['objects']
        # Identity-only, detached object (no active creation claim) blocks completion.
        vm=VirtualMachine.objects.create(name=source,custom_field_data={'sync_identities':[{'instance':source}]})
        objects.append(vm)
        refused(lambda:service.retire_source(user,intent.pk,intent.digest))
        assert not RetirementReceipt.objects.filter(intent=intent).exists()
        vm.delete()
        # Atomic interruption must roll back both closure and receipt.
        with patch.object(RetirementReceipt.objects,'create',side_effect=RuntimeError('isolated interruption')):
            try:service.retire_source(user,intent.pk,intent.digest)
            except RuntimeError:pass
            else:raise AssertionError('Interrupted receipt committed')
        assert not SourceClosure.objects.filter(source_instance=source).exists()
        done=service.retire_source(user,intent.pk,intent.digest)
        assert done.deleted==[] and service.retire_source(user,intent.pk,intent.digest).pk==done.pk
        # Separate source generation with prior confirmed nonempty immutable plan.
        source=source+'-next';sources.append(source)
        cluster=absent_cluster();identifier=cluster.pk
        prior=service.review_source(user,uuid4(),source,identifier)
        digest=prior.digest;manifest=prior.manifest
        cluster.delete()
        done=service.retire_source(user,prior.pk,digest)
        public=_public(prior,done)
        assert done.deleted==[] and public['already_absent']==['cluster:'+str(identifier)]
        prior.refresh_from_db();assert prior.digest==digest and prior.manifest==manifest
        source=source+'-next';sources.append(source)
        # Source-created VM moved out of placement is still found by its claim,
        # even if all custom fields were manually removed. Never delete it here.
        cluster=absent_cluster();identifier=cluster.pk
        vm=create_owned(user,uuid4(),source,'vm',{'name':source+'-detached','cluster':cluster},cluster=identifier)
        objects.append(vm);vm.cluster=None;vm.save();cluster.delete()
        refused(lambda:service.review_source(user,uuid4(),source,identifier))
        assert VirtualMachine.objects.filter(pk=vm.pk).exists()
        # Clearing the active claim must not hide a historically created object.
        CreationClaim.objects.filter(source_instance=source,resource='vm',object_id=vm.pk).delete()
        refused(lambda:service.review_source(user,uuid4(),source,identifier))
        vm.delete()
        print('PASS missing cluster: original OBJECT_MISSING reproduced; global detached claims/identities/history refuse; atomic interruption rollback; same-nonce retry; truthful absent receipt',flush=True)
    finally:
        for obj in reversed(objects):
            if obj.pk:type(obj).objects.filter(pk=obj.pk).delete()
        SourceClosure.objects.filter(source_instance__in=sources).delete()
        RetirementReceipt.objects.filter(intent__source_instance__in=sources).delete()
        RetirementIntent.objects.filter(source_instance__in=sources).delete()
        CreationClaim.objects.filter(source_instance__in=sources).delete()
        CreationReceipt.objects.filter(source_instance__in=sources).delete()
        add.delete();permission.delete();user.delete();kind.delete()
