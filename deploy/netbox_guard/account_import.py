"""Atomic, replayable inventory refresh. Never creates/adopts native objects."""
import re
from uuid import UUID, uuid5
from django.db import connection, transaction
from .service import _permission
from .provider_policy import digest
from .models import ProviderAccountRun
from .inventory_service import review_inventory, apply_inventory
from .resource_registry_service import prepare, apply


@transaction.atomic
def import_account(user, payload):
    actor = _permission(user, 'manage_providerbinding')
    _permission(user, 'manage_resourceregistry')
    if not isinstance(payload, dict) or set(payload) != {'account', 'nonce', 'document', 'registry'}:
        raise ValueError('PROVIDER_REQUEST_INVALID')
    account, document, registry = payload['account'], payload['document'], payload['registry']
    if not isinstance(account, str) or not re.fullmatch(r'[0-9]{1,20}', account):
        raise ValueError('PROVIDER_ACCOUNT_INVALID')
    if (document.get('account') != account or registry.get('account') != account
            or document.get('account_verified') is not True
            or document.get('finished_at') != registry.get('observed_at')):
        raise ValueError('PROVIDER_ACCOUNT_MISMATCH')
    nonce = UUID(str(payload['nonce'])); evidence = digest(payload)
    with connection.cursor() as cursor:
        for prefix in ('selectel-account:', 'selectel-inventory:', 'provider-resource-registry:'):
            cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', [prefix + account])
    receipt = ProviderAccountRun.objects.filter(pk=nonce).first()
    if receipt:
        if receipt.actor != actor or receipt.digest != evidence:
            raise ValueError('PROVIDER_NONCE_CONFLICT')
        return {**receipt.result, 'replayed': True}
    review = review_inventory(user, document, digest(document))
    registry_review = prepare(user, registry)[3]
    servers = apply_inventory(user, uuid5(nonce, 'servers'), document, digest(document), review['fingerprint'])
    resources = apply(user, uuid5(nonce, 'registry'), registry, registry_review['fingerprint'])
    result = dict(account=account, servers=servers['server_count'],
        matched=review['bound_count'], unmatched=servers['unmatched_count'],
        registry_resources=resources['resources'], retained=resources['retained_resources'],
        replayed=False, writes_performed=servers['writes_performed'] or resources['writes_performed'])
    ProviderAccountRun.objects.create(nonce=nonce, account=account, actor=actor, digest=evidence, result=result)
    return result
