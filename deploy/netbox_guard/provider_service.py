"""Explicit acceptance, optimistic review and journaled provider writes.

Ordinary Sync credentials have no manage_providerbinding permission. Possession
of a Selectel token or a matching IP never authorizes this administrative action.
"""
from uuid import UUID
from django.apps import apps
from django.db import transaction
from .dependencies import DependencyGuardBlocked
from .models import ProviderBinding, ProviderFieldClaim, ProviderBindingChange
from .provider_policy import digest, identity, proposed_claims
from .provider_schema import check_schema
from .service import _permission

MODELS = {'device': 'dcim.Device', 'vm': 'virtualization.VirtualMachine'}


def _spec(spec):
    if not isinstance(spec, dict) or set(spec) != {'resource', 'object_id', 'identity', 'serial', 'reason', 'evidence_digest'}:
        raise ValueError('PROVIDER_REQUEST_INVALID')
    identity(spec['identity'], spec['resource'])
    proposed_claims(spec['identity'], spec['resource'], spec['serial'])
    if type(spec['object_id']) is not int or spec['object_id'] <= 0:
        raise ValueError('PROVIDER_TARGET_INVALID')
    if not isinstance(spec['reason'], str) or not spec['reason'].strip() or len(spec['reason']) > 500:
        raise ValueError('PROVIDER_REASON_REQUIRED')
    evidence = spec['evidence_digest']
    if not isinstance(evidence, str) or len(evidence) != 64 or any(c not in '0123456789abcdef' for c in evidence):
        raise ValueError('PROVIDER_EVIDENCE_REQUIRED')


def _read(user, spec, *, lock=False):
    _spec(spec)
    _permission(user, 'manage_providerbinding')
    user = type(user).objects.get(pk=user.pk)
    check_schema()
    model = apps.get_model(MODELS[spec['resource']])
    query = model.objects.select_for_update() if lock else model.objects
    obj = query.filter(pk=spec['object_id']).first()
    if obj is None:
        raise ValueError('PROVIDER_TARGET_MISSING')
    for action in ('view', 'change'):
        if not user.has_perm(f'{obj._meta.app_label}.{action}_{obj._meta.model_name}', obj):
            raise DependencyGuardBlocked('PERMISSION_DENIED')
    key = identity(spec['identity'], spec['resource'])
    from .models import ProviderAccountFence, ProviderDetachedResource
    if ProviderAccountFence.objects.filter(account=spec['identity']['account'], deleted=True).exists():
        raise ValueError('PROVIDER_ACCOUNT_DELETED')
    if ProviderDetachedResource.objects.filter(provider_key=key).exists():
        raise ValueError('PROVIDER_RESOURCE_DETACHED')
    binding = ProviderBinding.objects.filter(resource=spec['resource'], object_id=obj.pk).first()
    if binding and (binding.provider_key != key or binding.object_created != obj.created):
        raise ValueError('PROVIDER_BINDING_CONFLICT')
    if ProviderBinding.objects.filter(provider_key=key).exclude(resource=spec['resource'], object_id=obj.pk).exists():
        raise ValueError('PROVIDER_BINDING_CONFLICT')
    claims = dict(ProviderFieldClaim.objects.filter(binding=binding).values_list('field', 'value')) if binding else {}
    before = {'binding_revision': binding.revision if binding else 0, 'claims': claims,
              'object_created': obj.created.isoformat(),
              'object_updated': obj.last_updated.isoformat() if obj.last_updated else None,
              'custom_fields': obj.custom_field_data, 'name': obj.name,
              'serial': getattr(obj, 'serial', ''), 'site_id': getattr(obj, 'site_id', None),
              'cluster_id': getattr(obj, 'cluster_id', None),
              'status': getattr(obj, 'status', None),
              'vcpus': str(obj.vcpus) if getattr(obj, 'vcpus', None) is not None else None,
              'memory': getattr(obj, 'memory', None)}
    proposed = {**claims, **proposed_claims(spec['identity'], spec['resource'], spec['serial'])}
    return obj, binding, before, proposed


def review_binding(user, spec):
    obj, binding, before, proposed = _read(user, spec)
    return {'fingerprint': digest({'spec': spec, 'before': before}),
            'binding_revision': before['binding_revision'], 'object_id': obj.pk,
            'object_name': obj.name, 'current_claims': before['claims'],
            'current_values': {field: ((obj.custom_field_data or {}).get(field.split('.', 1)[1])
                if field.startswith('custom_fields.') else getattr(obj, field)) for field in proposed},
            'provider_key': identity(spec['identity'], spec['resource']),
            'proposed_claims': proposed, 'writes_performed': False}


@transaction.atomic
def apply_binding(user, nonce, spec, fingerprint):
    _spec(spec)
    actor = _permission(user, 'manage_providerbinding')
    nonce = UUID(str(nonce))
    payload_digest = digest({'spec': spec, 'fingerprint': fingerprint})
    # Lock target before journal/claim work, same order as PostgreSQL row triggers.
    obj, binding, before, proposed = _read(user, spec, lock=True)
    receipt = ProviderBindingChange.objects.filter(pk=nonce).first()
    if receipt:
        if receipt.digest != payload_digest or receipt.actor != actor:
            raise ValueError('PROVIDER_NONCE_CONFLICT')
        return {'nonce': str(nonce), 'revision': receipt.after['revision'], 'replayed': True}
    if digest({'spec': spec, 'before': before}) != fingerprint:
        raise ValueError('PROVIDER_REVIEW_STALE')
    if binding is None:
        binding = ProviderBinding.objects.create(provider_key=identity(spec['identity'], spec['resource']),
            account=spec['identity']['account'], resource=spec['resource'], object_id=obj.pk,
            object_created=obj.created)
    elif proposed != before['claims']:
        binding.revision += 1
        binding.save(update_fields=['revision'])
    cf = dict(obj.custom_field_data or {})
    update = set()
    for field, value in proposed.items():
        ProviderFieldClaim.objects.update_or_create(binding=binding, field=field, defaults={'value': value})
        if field.startswith('custom_fields.'):
            name = field.split('.', 1)[1]
            if cf.get(name) != value:
                cf[name] = value
                update.add('custom_field_data')
        elif field in ('name', 'serial', 'status', 'vcpus', 'memory', 'site_id'):
            if getattr(obj, field) != value:
                setattr(obj, field, value)
                update.add('site' if field == 'site_id' else field)
        else:
            raise ValueError('PROVIDER_FIELD_UNSUPPORTED')
    if update:
        obj.custom_field_data = cf
        obj.full_clean()
        obj.save(update_fields=sorted(update | {'last_updated'}))
    # No raw API payload, token or password belongs in this journal.
    ProviderBindingChange.objects.create(nonce=nonce, binding=binding, actor=actor,
        digest=payload_digest, before={'revision': before['binding_revision'], 'claims': before['claims']},
        after={'revision': binding.revision, 'claims': proposed, 'evidence_digest': spec['evidence_digest']},
        reason=spec['reason'])
    return {'nonce': str(nonce), 'revision': binding.revision, 'replayed': False}
