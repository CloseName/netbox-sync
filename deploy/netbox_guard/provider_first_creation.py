"""Explicit first creation when a provider UUID exists but hardware identity does not."""
import re
from uuid import UUID, uuid5
from django.conf import settings
from django.db import connection, transaction
from .models import ProviderInventory, ProviderInventoryImport
from .provider_policy import digest
from .provider_reconcile import prepare, _create
from .provider_service import review_binding, apply_binding, _read
from .inventory_service import _write_claims
from .selectel_inventory import projection
from .service import _permission


def review(user, account, key):
    _permission(user, 'manage_providerbinding')
    if not isinstance(account, str) or not re.fullmatch(r'[0-9]{1,20}', account):
        raise ValueError('PROVIDER_ACCOUNT_INVALID')
    if settings.PLUGINS_CONFIG.get('netbox_guard', {}).get('selectel_native_reconcile') is not True:
        raise ValueError('PROVIDER_NATIVE_DISABLED')
    report = prepare(user, account)
    plan = next((p for p in report['resources'] if p['key'] == key), None)
    if plan is None:
        raise ValueError('PROVIDER_TARGET_MISSING')
    record = ProviderInventory.objects.get(pk=key, account=account)
    ident = record.snapshot['identity']
    reason = plan['reason']
    eligible = (ident['account'] == account and ident['kind'] == 'dedicated'
                and plan['action'] == 'blocked' and reason == 'hardware_identity_missing'
                and not plan['candidates'])
    try:
        parsed_uuid = UUID(ident['native_id'])
        canonical_uuid = parsed_uuid.int != 0 and str(parsed_uuid) == ident['native_id']
    except (ValueError, TypeError, AttributeError):
        canonical_uuid = False
    if eligible and not canonical_uuid:
        eligible, reason = False, 'provider_uuid_required'
    section = record.snapshot['sections'].get('placement', {})
    data = section.get('data') or {}
    location = data.get('uuid') or data.get('OS-EXT-AZ:availability_zone') if isinstance(data, dict) else None
    label = data.get('name') or data.get('OS-EXT-AZ:availability_zone') if isinstance(data, dict) else None
    if eligible and (section.get('status') != 'collected' or section.get('retained')
                     or not isinstance(location, str) or not location
                     or not isinstance(label, str) or not label):
        eligible, reason = False, 'placement_missing'
    # The UUID is an account resource identity, never a fabricated chassis serial.
    name = plan['native_name']
    if len(plan['name']) > 64 or sum(p['name'].casefold() == plan['name'].casefold() for p in report['resources']) > 1:
        name = plan['name'][:49] + ' [' + digest(key)[:10] + ']'
    return dict(account=account, key=key, name=plan['name'], native_name=name,
                native_id=ident['native_id'], location=label, region=ident.get('region') or '',
                candidates=plan['candidates'], reason=reason, eligible=eligible,
                fingerprint=digest({'operation': 'first_creation_v1', 'key': key,
                                    'state': report['fingerprint'], 'eligible': eligible}),
                writes_performed=False)


@transaction.atomic
def execute(user, account, key, nonce, fingerprint):
    actor = _permission(user, 'manage_providerbinding')
    nonce = UUID(str(nonce))
    request_digest = digest(dict(operation='first_creation_v1', account=account, key=key, fingerprint=fingerprint))
    with connection.cursor() as cursor:
        for prefix in ('selectel-account:', 'selectel-inventory:'):
            cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', [prefix + account])
        cursor.execute('LOCK TABLE dcim_device, virtualization_virtualmachine, ipam_ipaddress, netbox_guard_providerbinding IN SHARE ROW EXCLUSIVE MODE')
    receipt = ProviderInventoryImport.objects.filter(pk=nonce).first()
    if receipt:
        if receipt.actor != actor or receipt.digest != request_digest:
            raise ValueError('PROVIDER_NONCE_CONFLICT')
        return {**receipt.result, 'replayed': True}
    preview = review(user, account, key)
    if not preview['eligible'] or preview['fingerprint'] != fingerprint:
        raise ValueError('PROVIDER_REVIEW_STALE')
    record = ProviderInventory.objects.get(pk=key, account=account)
    plan = next(p for p in prepare(user, account)['resources'] if p['key'] == key)
    plan['native_name'] = preview['native_name']
    target = _create(user, record, plan, placement_updates=False)
    spec = dict(resource='device', object_id=target.pk, identity=record.snapshot['identity'], serial=None,
                reason='Operator confirmed first creation without hardware identity', evidence_digest=record.evidence_digest)
    binding_review = review_binding(user, spec)
    apply_binding(user, uuid5(nonce, 'binding'), spec, binding_review['fingerprint'])
    target, binding, before, claims = _read(user, spec, lock=True)
    claims.update({'custom_fields.' + k: v for k, v in projection(record.snapshot).items()})
    claims.update(name=target.name, site_id=target.site_id)
    claims['custom_fields.selectel_inventory'] = {**record.snapshot, 'native_fields': ['name', 'site_id']}
    _write_claims(target, binding, before, claims, actor, uuid5(nonce, 'projection'),
                  request_digest, record.evidence_digest, spec['reason'])
    result = dict(operation='first_creation_v1', account=account, provider_key=key,
                  object_id=target.pk, object_url=target.get_absolute_url(), name=target.name,
                  writes_performed=True, replayed=False)
    ProviderInventoryImport.objects.create(nonce=nonce, account=account, actor=actor,
                                          digest=request_digest, result=result)
    return result
