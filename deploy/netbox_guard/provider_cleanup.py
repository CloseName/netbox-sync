"""Account-wide cleanup of network projections, using original write receipts."""
import json
from types import SimpleNamespace
from django.apps import apps
from .dependencies import _digest
from .models import ProviderIPAMObject, ProviderIPAMReceipt, ProviderNetworkLink, ProviderInventoryImport
from .selectel_ipam_service import MODELS, state


def scope(key, account):
    try:
        value = json.loads(key)
    except (ValueError, TypeError):
        return False
    return isinstance(value, list) and value[:2] == ['selectel', account]


def proof(obj, key=''):
    return SimpleNamespace(model_label=obj._meta.label_lower, object_id=obj.pk,
                           object_created=obj.created, provider_key=key, pk='receipt:'+str(obj.pk))


def legacy_cards(account, bindings, owned):
    """A successful create receipt plus the original row timestamp proves creation.

    Binding, name, IP and current Selectel fields alone never grant deletion.
    """
    known = {(p.model_label, p.object_id) for p in owned}
    targets = {(b.resource, b.object_id): b for b in bindings}
    result, evidence = [], []
    for receipt in ProviderInventoryImport.objects.filter(account=account).order_by('created_at', 'pk'):
        report = receipt.result
        if report.get('operation') != 'reconcile' or report.get('account') != account:
            continue
        for row in report.get('applied', []):
            binding = targets.get((row.get('resource'), row.get('id')))
            if row.get('action') != 'create' or binding is None:
                continue
            label = {'device':'dcim.device', 'vm':'virtualization.virtualmachine'}[binding.resource]
            obj = apps.get_model(label).objects.filter(pk=binding.object_id).first()
            if (obj is None or (label, obj.pk) in known or obj.created != binding.object_created
                    or obj.created > receipt.created_at):
                continue
            # A receipt older than the binding's object cannot own a replacement.
            result.append(proof(obj, binding.provider_key)); known.add((label, obj.pk))
            evidence.append(('legacy-create', str(receipt.pk), _digest(report), str(obj.created)))
    return result, evidence


def network_plan(user, account, access):
    mappings = [m for m in ProviderIPAMObject.objects.order_by('pk') if scope(m.key, account)]
    ids = [m.pk for m in mappings]
    links = list(ProviderNetworkLink.objects.filter(binding__account=account).order_by('pk'))
    result = dict(mapping_ids=ids, link_ids=[l.pk for l in links], restore=[], evidence=[], blockers=[], retain=[])
    result['evidence'].extend(('link', l.pk, l.binding_id, l.native_id, l.relation, l.evidence) for l in links)
    receipts = list(ProviderIPAMReceipt.objects.order_by('created_at', 'pk'))
    owned = []
    for mapping in mappings:
        result['evidence'].append(('mapping', mapping.pk, mapping.key, mapping.claims, str(mapping.object_created)))
        model = apps.get_model(MODELS[mapping.kind])
        obj = model.objects.filter(pk=mapping.object_id).first()
        item = dict(model=model._meta.label_lower, id=mapping.object_id)
        if obj is None or obj.created != mapping.object_created:
            result['blockers'].append(dict(item, reason='creation_identity_changed')); continue
        access(user, obj, 'view'); access(user, obj, 'change')
        item.update(name=str(obj), url=obj.get_absolute_url())
        result['evidence'].append(('network-native', obj.pk, state(obj)))
        foreign = ProviderNetworkLink.objects.filter(native=mapping).exclude(binding__account=account)
        if foreign.exists():
            result['blockers'].append(dict(item, reason='foreign_dependencies_or_sync_source')); continue
        origin = None
        for receipt in receipts:
            review = receipt.result.get('review', {})
            if review.get('request', {}).get('account') != account or receipt.created_at < obj.created:
                continue
            operations = review.get('operations', [])
            original = next((o for o in operations if o.get('key') == mapping.key and o.get('mapping_id') is None
                             and o.get('action') in ('create', 'adopt')), None)
            committed = next((o for o in receipt.result.get('objects', []) if o.get('kind') == mapping.kind
                              and o.get('id') == obj.pk), None)
            if original and committed and committed.get('action') == original['action']:
                if original['action'] == 'adopt' and (original.get('id') != obj.pk
                        or original.get('before', {}).get('created') != str(obj.created)):
                    continue
                origin = original
                result['evidence'].append(('network-receipt', str(receipt.pk), _digest(receipt.result)))
                break
        if origin is None:
            result['blockers'].append(dict(item, reason='legacy_ipam_provenance_required')); continue
        if origin['action'] == 'create' and origin.get('before') is None and origin.get('id') is None:
            access(user, obj, 'delete'); owned.append(proof(obj, mapping.key))
        else:
            result['retain'].append(item)
            # The legacy writer only changed an adopted prefix's empty VLAN.
            # Restore that exact prior value; do not overwrite later manual edits.
            if origin.get('updates') and mapping.kind == 'prefix':
                old = origin['before'].get('vlan_id')
                if obj.vlan_id != mapping.claims.get('vlan_id'):
                    result['blockers'].append(dict(item, reason='binding_target_changed')); continue
                result['restore'].append(dict(item, field='vlan_id', value=old))
    return result, owned


def release_network(plan):
    """Caller has fenced the account deleted inside the same locked transaction."""
    ProviderNetworkLink.objects.filter(pk__in=plan['link_ids']).delete()
    ProviderIPAMObject.objects.filter(pk__in=plan['mapping_ids']).delete()
    for row in plan['restore']:
        obj = apps.get_model(row['model']).objects.get(pk=row['id'])
        setattr(obj, row['field'], row['value'])
        obj.full_clean(); obj.save(update_fields=[row['field'], 'last_updated'])
