"""Reviewed, atomic server inventory import; never creates native infrastructure."""
from uuid import UUID, uuid5
from django.db import connection, transaction
from .models import ProviderBinding, ProviderFieldClaim, ProviderBindingChange, ProviderInventory, ProviderInventoryImport
from .provider_policy import digest
from .provider_schema import check_schema
from .provider_service import _read
from .selectel_inventory import Inventory, merge_snapshot, projection, timestamp
from .service import _permission


def _prepare(user, document, evidence_digest, *, lock=False):
    _permission(user, 'manage_providerbinding')
    check_schema()
    if (not isinstance(evidence_digest, str) or len(evidence_digest) != 64
            or any(c not in '0123456789abcdef' for c in evidence_digest)):
        raise ValueError('PROVIDER_EVIDENCE_REQUIRED')
    inventory = Inventory(document)
    records = inventory.normalize()
    old_records = {r.pk: r for r in ProviderInventory.objects.filter(account=inventory.account)}
    bindings = {b.provider_key: b for b in ProviderBinding.objects.filter(account=inventory.account)}
    plans, state, report = [], [], []
    # Stable target order, matching ordinary Guard's target-before-claim lock order.
    order = sorted(records, key=lambda k: (bindings[k].resource, bindings[k].object_id)
                   if k in bindings else ('unbound', k))
    for key in order:
        old = old_records.get(key)
        observed = timestamp(inventory.observed)
        if old and (observed < old.observed_at or
                    (observed == old.observed_at and old.evidence_digest != evidence_digest)):
            raise ValueError('SELECTEL_SNAPSHOT_STALE_OR_CONFLICTING')
        snapshot = merge_snapshot(old.snapshot if old else None, records[key])
        binding = bindings.get(key)
        obj, before, claims = None, None, None
        if binding:
            spec = dict(resource=binding.resource, object_id=binding.object_id, identity=snapshot['identity'],
                        serial=None, reason='Selectel server inventory import', evidence_digest=evidence_digest)
            obj, actual_binding, before, claims = _read(user, spec, lock=lock)
            if actual_binding is None or actual_binding.pk != binding.pk:
                raise ValueError('PROVIDER_REVIEW_STALE')
            binding = actual_binding
            claims = {**claims, **{'custom_fields.' + k: v for k, v in projection(snapshot).items()}}
        changed = old is None or old.snapshot != snapshot or old.evidence_digest != evidence_digest
        projection_changed = bool(binding and claims != before['claims'])
        state.append({'key': key, 'old': old.snapshot if old else None,
                      'old_digest': old.evidence_digest if old else None, 'target': before})
        report.append({'provider_key': key, 'name': snapshot['sections']['resource']['data'].get('name') or
                       snapshot['sections']['resource']['data'].get('user_desc'),
                       'target': {'resource': binding.resource, 'id': binding.object_id, 'name': obj.name} if binding else None,
                       'registry_changed': changed, 'projection_changed': projection_changed,
                       'sections': {k: {'status': v['status'], 'code': v['code'], 'retained': v['retained']}
                                    for k, v in snapshot['sections'].items()}})
        plans.append((key, snapshot, old, binding, obj, before, claims, changed, projection_changed))
    missing = sorted(set(old_records) - set(records))
    fingerprint = digest({'evidence_digest': evidence_digest, 'account': inventory.account, 'state': state,
                          'missing': missing})
    return inventory, plans, {'fingerprint': fingerprint, 'account': inventory.account,
        'server_count': len(records), 'bound_count': sum(x['target'] is not None for x in report),
        'unmatched_count': sum(x['target'] is None for x in report), 'missing_retained': missing,
        'resources': report, 'writes_performed': False}


def review_inventory(user, document, evidence_digest):
    return _prepare(user, document, evidence_digest)[2]


@transaction.atomic
def apply_inventory(user, nonce, document, evidence_digest, fingerprint):
    actor = _permission(user, 'manage_providerbinding')
    nonce = UUID(str(nonce))
    account = Inventory(document).account
    # Serializes account imports, including first insertion of an unmatched server.
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', ['selectel-inventory:' + account])
    request_digest = digest({'evidence': evidence_digest, 'document': document, 'fingerprint': fingerprint})
    receipt = ProviderInventoryImport.objects.filter(pk=nonce).first()
    if receipt:
        if receipt.actor != actor or receipt.digest != request_digest:
            raise ValueError('PROVIDER_NONCE_CONFLICT')
        return {**receipt.result, 'replayed': True}
    inventory, plans, report = _prepare(user, document, evidence_digest, lock=True)
    if report['fingerprint'] != fingerprint:
        raise ValueError('PROVIDER_REVIEW_STALE')
    updated, registered = [], 0
    for key, snapshot, old, binding, obj, before, claims, changed, projection_changed in plans:
        if changed:
            ProviderInventory.objects.update_or_create(provider_key=key, defaults={
                'account': inventory.account, 'snapshot': snapshot, 'observed_at': timestamp(inventory.observed),
                'evidence_digest': evidence_digest})
            registered += 1
        if not projection_changed:
            continue
        cf = dict(obj.custom_field_data or {})
        for field, value in claims.items():
            # Existing serial claims stay intact; this importer acquires only provider custom fields.
            if field.startswith('custom_fields.'):
                cf[field.split('.', 1)[1]] = value
            ProviderFieldClaim.objects.update_or_create(binding=binding, field=field, defaults={'value': value})
        previous_revision = binding.revision
        binding.revision += 1
        binding.save(update_fields=['revision'])
        obj.custom_field_data = cf
        obj.full_clean()
        obj.save(update_fields=['custom_field_data', 'last_updated'])
        ProviderBindingChange.objects.create(nonce=uuid5(nonce, key), binding=binding, actor=actor,
            digest=request_digest, before={'revision': previous_revision, 'claims': before['claims']},
            after={'revision': binding.revision, 'claims': claims, 'evidence_digest': evidence_digest},
            reason='Selectel server inventory import')
        updated.append({'resource': binding.resource, 'id': obj.pk, 'name': obj.name, 'revision': binding.revision})
    result = {'account': inventory.account, 'server_count': len(plans), 'registry_updated': registered,
              'targets_updated': updated, 'unmatched_count': report['unmatched_count'],
              'missing_retained': report['missing_retained'], 'writes_performed': bool(registered or updated),
              'nonce': str(nonce), 'replayed': False}
    ProviderInventoryImport.objects.create(nonce=nonce, account=inventory.account, actor=actor,
                                          digest=request_digest, result=result)
    return result
