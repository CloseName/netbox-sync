"""Serialized, reviewed account imports; no Device/IPAM model access."""
from uuid import UUID
from django.db import connection, transaction
from .models import ProviderResourceRegistry, ProviderResourceRegistryChange
from .resource_registry_policy import normalize, merge, stamp, require
from .provider_policy import digest
from .service import _permission


def prepare(user, document):
    _permission(user, 'manage_resourceregistry')
    incoming = normalize(document)
    old = ProviderResourceRegistry.objects.filter(pk=incoming['account']).first()
    evidence = digest(incoming)
    if old:
        require(stamp(incoming['observed_at']) >= old.observed_at, 'PROVIDER_REGISTRY_STALE')
        require(stamp(incoming['observed_at']) != old.observed_at or old.evidence_digest == evidence,
                'PROVIDER_REGISTRY_SAME_TIME_CONFLICT')
    after = merge(old.snapshot if old else None, incoming)
    changed = old is None or old.snapshot != after
    fingerprint = digest({'evidence': evidence, 'previous': old.snapshot if old else None,
                          'revision': old.revision if old else 0})
    report = {'account': incoming['account'], 'fingerprint': fingerprint,
        'changes': int(changed), 'revision': (old.revision if old else 0) + int(changed),
        'resources': len(after['resources']), 'relations': len(after['relations']),
        'retained_resources': sum(not r['present_in_latest'] for r in after['resources'].values()),
        'retained_sections': sum(s.get('retained', False) for r in after['resources'].values()
                                 for s in r['sections'].values()), 'writes_performed': False}
    return old, after, evidence, report


@transaction.atomic
def apply(user, nonce, document, fingerprint):
    actor = _permission(user, 'manage_resourceregistry')
    incoming = normalize(document)
    nonce = UUID(str(nonce))
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
                       ['provider-resource-registry:' + incoming['account']])
    request = digest({'incoming': incoming, 'fingerprint': fingerprint})
    receipt = ProviderResourceRegistryChange.objects.filter(pk=nonce).first()
    if receipt:
        require(receipt.actor == actor and receipt.digest == request, 'PROVIDER_NONCE_CONFLICT')
        return {**receipt.result, 'replayed': True}
    old, after, evidence, report = prepare(user, document)
    require(report['fingerprint'] == fingerprint, 'PROVIDER_REVIEW_STALE')
    if not report['changes']:
        return {**report, 'replayed': False}
    before = old.snapshot if old else None
    row, _ = ProviderResourceRegistry.objects.update_or_create(account=incoming['account'], defaults={
        'snapshot': after, 'revision': report['revision'], 'observed_at': stamp(incoming['observed_at']),
        'evidence_digest': evidence})
    result = {**report, 'writes_performed': True, 'replayed': False}
    ProviderResourceRegistryChange.objects.create(nonce=nonce, registry=row, actor=actor,
        digest=request, revision=row.revision, before=before, after=after, result=result)
    return result
