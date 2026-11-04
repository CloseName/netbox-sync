"""Reviewed association with an existing native object, without adopting ownership."""
from uuid import UUID, uuid5
from django.conf import settings
from django.db import connection, transaction
from .models import ProviderInventory, ProviderInventoryImport, ProviderDetachedResource
from .provider_policy import digest
from .provider_reconcile import prepare
from .provider_service import review_binding, apply_binding, _read
from .service import _permission


ALLOWED_REASONS = frozenset(('identity_needs_confirmation', 'hardware_identity_missing',
                             'placement_missing', 'no_existing_candidate', 'stable_identity'))


def review(user, account, key, object_id):
    _permission(user, 'manage_providerbinding')
    if settings.PLUGINS_CONFIG.get('netbox_guard', {}).get('selectel_native_reconcile') is not True:
        raise ValueError('PROVIDER_NATIVE_DISABLED')
    report = prepare(user, account, resume_key=key)
    plan = next((p for p in report['resources'] if p['key'] == key), None)
    if plan is None or plan['reason'] not in ALLOWED_REASONS:
        raise ValueError('PROVIDER_LINK_UNAVAILABLE')
    strong = {(c['resource'], c['id']) for c in plan['candidates'] if c['evidence']['stable_identity']}
    if strong and strong != {(plan['resource'], object_id)}:
        raise ValueError('PROVIDER_IDENTITY_CONFLICT')
    record = ProviderInventory.objects.get(pk=key, account=account)
    spec = dict(resource=plan['resource'], object_id=object_id,
                identity=record.snapshot['identity'], serial=None,
                reason='Operator confirmed association with existing inventory object',
                evidence_digest=record.evidence_digest)
    binding_review = review_binding(user, spec, allow_detached=True)
    target, binding, _, _ = _read(user, spec, allow_detached=True)
    if binding:
        raise ValueError('PROVIDER_BINDING_CONFLICT')
    prior_refs = (target.custom_field_data or {}).get('selectel_refs') or []
    expected_ref = dict(provider='selectel', **record.snapshot['identity'])
    if prior_refs and prior_refs != [expected_ref]:
        raise ValueError('PROVIDER_BINDING_CONFLICT')
    return dict(account=account, key=key, name=plan['name'], resource=plan['resource'],
                object_id=target.pk, object_name=target.name, object_url=target.get_absolute_url(),
                spec=spec, binding_fingerprint=binding_review['fingerprint'],
                fingerprint=digest(dict(operation='manual_link_v1', state=report['fingerprint'],
                                        binding=binding_review['fingerprint'])), writes_performed=False)


@transaction.atomic
def execute(user, account, key, object_id, nonce, fingerprint):
    actor = _permission(user, 'manage_providerbinding')
    nonce = UUID(str(nonce))
    request_digest = digest(dict(operation='manual_link_v1', account=account, key=key,
                                object_id=object_id, fingerprint=fingerprint))
    with connection.cursor() as cursor:
        for prefix in ('selectel-account:', 'selectel-inventory:'):
            cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', [prefix + account])
        cursor.execute('LOCK TABLE dcim_device, virtualization_virtualmachine, ipam_ipaddress, netbox_guard_providerbinding IN SHARE ROW EXCLUSIVE MODE')
    receipt = ProviderInventoryImport.objects.filter(pk=nonce).first()
    if receipt:
        if receipt.actor != actor or receipt.digest != request_digest:
            raise ValueError('PROVIDER_NONCE_CONFLICT')
        return {**receipt.result, 'replayed': True}
    preview = review(user, account, key, object_id)
    if preview['fingerprint'] != fingerprint:
        raise ValueError('PROVIDER_REVIEW_STALE')
    ProviderDetachedResource.objects.filter(pk=key, account=account).delete()
    apply_binding(user, uuid5(nonce, 'binding'), preview['spec'], preview['binding_fingerprint'])
    result = dict(operation='manual_link_v1', account=account, provider_key=key,
                  object_id=object_id, object_url=preview['object_url'], name=preview['object_name'],
                  writes_performed=True, replayed=False)
    ProviderInventoryImport.objects.create(nonce=nonce, account=account, actor=actor,
                                          digest=request_digest, result=result)
    return result
