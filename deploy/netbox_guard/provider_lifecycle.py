"""Reviewed provider detach/removal. Never cascades into unowned infrastructure."""
import re
from uuid import UUID
from django.apps import apps
from django.db import connection
from django.db.models import QuerySet
from django.db.models.deletion import Collector
from .dependencies import _database_fence, _digest, DependencyGuardBlocked
from .service import _permission
from .models import (ProviderBinding, ProviderFieldClaim, ProviderBindingChange,
    ProviderCreatedObject, ProviderNetworkLink, ProviderInventory, ProviderInventoryImport,
    ProviderResourceRegistry, ProviderResourceRegistryChange, ProviderDetachedResource,
    ProviderAccountFence, ProviderLifecycleReceipt)

TARGETS = {'device': 'dcim.device', 'vm': 'virtualization.virtualmachine'}
ORDER = {'virtualization.virtualmachine': 0, 'dcim.device': 1, 'dcim.site': 2,
         'ipam.ipaddress': -4, 'ipam.prefix': -3, 'ipam.vlan': -2, 'ipam.vlangroup': -1,
         'dcim.devicerole': 2, 'dcim.devicetype': 2, 'dcim.manufacturer': 3, 'dcim.region': 4}


def _access(user, obj, action):
    if not user.has_perm(f'{obj._meta.app_label}.{action}_{obj._meta.model_name}', obj):
        raise DependencyGuardBlocked('PERMISSION_DENIED')


def _spec(account, operation, key):
    if not isinstance(account, str) or not re.fullmatch('[0-9]{1,20}', account):
        raise ValueError('PROVIDER_ACCOUNT_INVALID')
    if operation not in ('detach', 'delete', 'activate', 'baseline') or (operation in ('detach', 'baseline') and not isinstance(key, str)):
        raise ValueError('PROVIDER_REQUEST_INVALID')
    if operation in ('delete', 'activate') and key is not None:
        raise ValueError('PROVIDER_REQUEST_INVALID')


def _prepare(user, account, operation, key):
    from django.conf import settings
    if settings.PLUGINS_CONFIG.get('netbox_guard', {}).get('selectel_native_reconcile') is not True:
        raise ValueError('PROVIDER_NATIVE_SETUP_REQUIRED')
    _spec(account, operation, key)
    _permission(user, 'manage_providerbinding')
    if operation == 'baseline':
        from .account_baseline import prepare
        return prepare(user, account, key), []
    # Even an empty account must not accept a review from an earlier cycle.
    previous = ProviderLifecycleReceipt.objects.filter(account=account).order_by('-created_at', '-pk').first()
    epoch = str(previous.pk) if previous else None
    if operation == 'activate':
        deleted = ProviderAccountFence.objects.filter(account=account,deleted=True).exists()
        if not deleted:
            raise ValueError('PROVIDER_ACCOUNT_NOT_DELETED')
        return {'fingerprint':_digest([account,'activate',deleted,epoch]),'account':account,'operation':operation,
                'key':None,'delete':[],'retain':[],'blockers':[],'writes_performed':False}, []
    bindings = list(ProviderBinding.objects.filter(account=account).order_by('pk'))
    if operation == 'detach':
        bindings = [b for b in bindings if b.provider_key == key]
        if len(bindings) != 1:
            raise ValueError('PROVIDER_BINDING_REQUIRED')
    owned = list(ProviderCreatedObject.objects.filter(account=account)) if operation == 'delete' else []
    from .provider_cleanup import network_plan, legacy_cards
    removed, retained, blockers, evidence = [], [], [], []
    cleanup = None
    if operation == 'delete':
        recovered, history = legacy_cards(account, bindings, owned)
        owned.extend(recovered); evidence.extend(history)
        cleanup, network_owned = network_plan(user, account, _access)
        known = {(o.model_label, o.object_id) for o in owned}
        owned.extend(o for o in network_owned if (o.model_label, o.object_id) not in known)
        evidence.extend(cleanup['evidence']); blockers.extend(cleanup['blockers'])
        retained.extend(cleanup['retain'])
    owned_keys = {(o.model_label, o.object_id) for o in owned}
    for binding in bindings:
        model = apps.get_model(TARGETS[binding.resource])
        obj = model.objects.filter(pk=binding.object_id).first()
        if obj is None or obj.created != binding.object_created:
            blockers.append({'reason':'binding_target_changed', 'binding':binding.pk})
            continue
        _access(user, obj, 'view'); _access(user, obj, 'change')
        evidence.append((binding.pk, binding.revision, _digest({f.attname:getattr(obj,f.attname) for f in obj._meta.concrete_fields}),
                         list(ProviderFieldClaim.objects.filter(binding=binding).order_by('field').values_list('field','value'))))
        if operation != 'delete' and ProviderNetworkLink.objects.filter(binding=binding).exists():
            blockers.append({'reason':'provider_network_links_present', 'binding':binding.pk})
        retained.append({'model':model._meta.label_lower, 'id':obj.pk, 'name':str(obj), 'url':obj.get_absolute_url(),
                         'provider_key':binding.provider_key})
    retained_catalog = set()
    for proof in sorted(owned, key=lambda o:(ORDER.get(o.model_label,99),o.object_id)):
        if proof.model_label not in ORDER:
            blockers.append({'reason':'unsupported_owned_model'}); continue
        obj = apps.get_model(proof.model_label).objects.filter(pk=proof.object_id).first()
        if obj is None:
            evidence.append(('missing',proof.pk)); continue
        _access(user,obj,'view'); _access(user,obj,'delete')
        if obj.created != proof.object_created:
            blockers.append({'reason':'creation_identity_changed','model':proof.model_label,'id':obj.pk}); continue
        item = {'model':proof.model_label,'id':obj.pk,'name':str(obj),'url':obj.get_absolute_url()}
        evidence.append((proof.pk,_digest({f.attname:getattr(obj,f.attname) for f in obj._meta.concrete_fields})))
        foreign = bool((getattr(obj,'custom_field_data',None) or {}).get('sync_identities'))
        # NetBox primary-IP fields use hidden reverse relations (related_name='+').
        # They still carry live references and must appear in the review, not only
        # be caught later by Collector's final no-external-writes check.
        for rel in obj._meta.get_fields(include_hidden=True):
            if not (rel.auto_created and not rel.concrete and rel.is_relation
                    and rel.related_model is not None):
                continue
            dependents = rel.related_model.objects.filter(**{rel.field.name:obj})
            for dependent in dependents:
                _access(user,dependent,'view')
                evidence.append(('dependency',proof.pk,dependent._meta.label_lower,dependent.pk))
                if cleanup and any(r['model'] == dependent._meta.label_lower and r['id'] == dependent.pk
                                   and r['field'] == rel.field.attname and r['value'] is None for r in cleanup['restore']):
                    continue
                if ((dependent._meta.label_lower,dependent.pk) not in owned_keys
                        or (dependent._meta.label_lower,dependent.pk) in retained_catalog):
                    foreign = True
        if foreign:
            if proof.model_label in TARGETS.values() or proof.model_label.startswith('ipam.'):
                blockers.append({**item,'reason':'foreign_dependencies_or_sync_source'})
            else:
                retained.append({**item,'reason':'shared_catalog_object'})
                retained_catalog.add((proof.model_label,obj.pk))
            continue
        removed.append(item)
    removed_keys={(r['model'],r['id']) for r in removed}
    binding_rows = list(retained)
    retained=[r for r in retained if (r['model'],r['id']) not in removed_keys]
    state = dict(account=account,operation=operation,key=key,evidence=evidence,epoch=epoch,
        registry=list(ProviderResourceRegistry.objects.filter(account=account).values_list('revision','evidence_digest')),
        inventory=list(ProviderInventory.objects.filter(account=account).order_by('pk').values_list('pk','evidence_digest')),
        removed=removed,retained=retained,blockers=blockers)
    return {'fingerprint':_digest(state),'account':account,'operation':operation,'key':key,
            'delete':removed,'retain':retained,'bindings':binding_rows,'blockers':blockers,
            'cleanup':{k:v for k,v in cleanup.items() if k != 'evidence'} if cleanup else None, 'remove_registry':operation == 'delete', 'writes_performed':False}, bindings


def review(user, account, operation, key=None):
    with _database_fence():
        return _prepare(user,account,operation,key)[0]


def _release(binding):
    obj = apps.get_model(TARGETS[binding.resource]).objects.get(pk=binding.object_id)
    cf = dict(obj.custom_field_data or {})
    for field in ProviderFieldClaim.objects.filter(binding=binding).values_list('field',flat=True):
        if field.startswith('custom_fields.selectel_'):
            cf.pop(field.split('.',1)[1],None)
    ProviderFieldClaim.objects.filter(binding=binding).delete()
    ProviderBindingChange.objects.filter(binding=binding).delete()
    binding.delete()
    obj.custom_field_data=cf
    obj.full_clean(); obj.save(update_fields=['custom_field_data','last_updated'])


def execute(user, account, operation, nonce, fingerprint, key=None):
    nonce=UUID(str(nonce))
    actor=_permission(user,'manage_providerbinding')
    request_digest=_digest([account,operation,key,fingerprint])
    with _database_fence():
        if operation == 'baseline':
            _spec(account, operation, key)
            from .account_baseline import accept
            return accept(user, account, key, fingerprint)
        receipt=ProviderLifecycleReceipt.objects.filter(pk=nonce).first()
        if receipt:
            if receipt.actor != actor or receipt.digest != request_digest:
                raise ValueError('PROVIDER_NONCE_CONFLICT')
            return {**receipt.result,'replayed':True}
        plan,bindings=_prepare(user,account,operation,key)
        if plan['fingerprint'] != fingerprint:
            raise ValueError('PROVIDER_REVIEW_STALE')
        if plan['blockers']:
            raise ValueError('PROVIDER_DEPENDENCIES_BLOCKED')
        if operation == 'delete':
            from .provider_cleanup import release_network
            ProviderAccountFence.objects.update_or_create(account=account,defaults={'deleted':True})
            release_network(plan['cleanup'])
        for binding in bindings:
            if operation == 'detach':
                ProviderDetachedResource.objects.update_or_create(provider_key=binding.provider_key,defaults={'account':account})
                ProviderCreatedObject.objects.filter(model_label=TARGETS[binding.resource],object_id=binding.object_id,
                                                    object_created=binding.object_created).delete()
            _release(binding)
        if operation == 'activate':
            ProviderAccountFence.objects.update_or_create(account=account,defaults={'deleted':False})
        if operation == 'delete':
            for item in plan['delete']:
                obj=apps.get_model(item['model']).objects.get(pk=item['id'])
                collector=Collector(using=connection.alias)
                collector.collect([obj])
                actual={(o._meta.label_lower,o.pk) for group in collector.data.values() for o in group}
                # Django may queue SET_NULL querysets with no affected rows.
                # Only actual external writes block deletion, not empty query plans.
                updates = any(group.exists() if isinstance(group, QuerySet) else bool(group)
                              for groups in collector.field_updates.values() for group in groups)
                if actual != {(item['model'],item['id'])} or updates or any(q.exists() for q in collector.fast_deletes):
                    raise ValueError('PROVIDER_UNOWNED_CASCADE_BLOCKED')
                collector.delete()
            ProviderCreatedObject.objects.filter(account=account).delete()
            ProviderDetachedResource.objects.filter(account=account).delete()
            ProviderInventory.objects.filter(account=account).delete()
            ProviderInventoryImport.objects.filter(account=account).delete()
            ProviderResourceRegistryChange.objects.filter(registry_id=account).delete()
            ProviderResourceRegistry.objects.filter(account=account).delete()
            ProviderAccountFence.objects.update_or_create(account=account,defaults={'deleted':True})
        result={**plan,'writes_performed':True,'replayed':False}
        ProviderLifecycleReceipt.objects.create(nonce=nonce,account=account,actor=actor,digest=request_digest,result=result)
        return result
