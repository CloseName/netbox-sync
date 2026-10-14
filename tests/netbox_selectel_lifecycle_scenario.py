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
    adopted=VirtualMachine.objects.create(name='adopted-'+account)
    owned=VirtualMachine.objects.create(name='owned-'+account)
    detached=VirtualMachine.objects.create(name='detached-'+account)
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
    owned.description='changed after review'; owned.save()
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
