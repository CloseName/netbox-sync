"""Atomic, replayable inventory refresh with opt-in native reconciliation."""
import re
from uuid import UUID, uuid5
from django.db import connection, transaction
from django.conf import settings
from .service import _permission
from .provider_policy import digest
from .models import ProviderAccountRun, ProviderAccountFence
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
    from .account_baseline import retired
    if retired(account, nonce):
        raise ValueError('PROVIDER_HISTORICAL_RUN_RETIRED')
    receipt = ProviderAccountRun.objects.filter(pk=nonce).first()
    if receipt:
        if receipt.actor != actor or receipt.digest != evidence:
            raise ValueError('PROVIDER_NONCE_CONFLICT')
        return {**receipt.result, 'replayed': True}
    if ProviderAccountFence.objects.filter(account=account, deleted=True).exists():
        raise ValueError('PROVIDER_ACCOUNT_DELETED')
    review = review_inventory(user, document, digest(document))
    registry_review = prepare(user, registry)[3]
    servers = apply_inventory(user, uuid5(nonce, 'servers'), document, digest(document), review['fingerprint'])
    resources = apply(user, uuid5(nonce, 'registry'), registry, registry_review['fingerprint'])
    native = None
    if settings.PLUGINS_CONFIG.get('netbox_guard', {}).get('selectel_native_reconcile') is True:
        from .provider_reconcile import prepare as native_prepare, apply as native_apply
        native_review = native_prepare(user, account)
        native = native_apply(user, account, uuid5(nonce, 'native'), native_review['fingerprint'])
        # Newly created/adopted cards receive the same authoritative snapshot in
        # this transaction. Any failure rolls back the whole account operation.
        review = review_inventory(user, document, digest(document))
        projection_result = apply_inventory(user, uuid5(nonce, 'native-projection'), document,
                                            digest(document), review['fingerprint'])
        servers['writes_performed'] |= projection_result['writes_performed']
        servers['unmatched_count'] = review['unmatched_count']
        servers['placement_pending'] = projection_result.get('placement_pending', [])
    result = dict(account=account, servers=servers['server_count'],
        matched=review['bound_count'], unmatched=servers['unmatched_count'],
        registry_resources=resources['resources'], retained=resources['retained_resources'],
        placement_pending=servers.get('placement_pending', []),
        replayed=False, writes_performed=servers['writes_performed'] or resources['writes_performed'])
    result['native_mode'] = 'automatic' if native is not None else 'registry_only'
    if native is not None:
        result.update(native_created=sum(row['action'] == 'create' for row in native['applied']),
                      native_adopted=sum(row['action'] == 'bind' for row in native['applied']),
                      native_blocked=len(native['blocked']))
        result['writes_performed'] |= native['writes_performed']
    ProviderAccountRun.objects.create(nonce=nonce, account=account, actor=actor, digest=evidence, result=result)
    return result
