"""Permission-aware links between provider routing and standard IPAM cards."""
from hashlib import sha256
from urllib.parse import urlencode
from django.apps import apps
from django.urls import reverse
from .models import ProviderCreatedObject, ProviderResourceRegistry
from .resource_tree import build_tree
from .routing_presentation import components
from .routing_browser import context as routing_context


def decorate(user, account, rows):
    index = {r['key']: r for r in rows}
    for row in rows:
        row['detail_href'] = reverse('plugins:netbox_guard:provider_resource_account', kwargs={'account': account}) + '?' + urlencode({
            'kind': row['kind'], 'resource': sha256(row['key'].encode()).hexdigest()})
    for proof in ProviderCreatedObject.objects.filter(account=account, provider_key__startswith='routing:'):
        model = apps.get_model(proof.model_label)
        native = model.objects.restrict(user, 'view').filter(pk=proof.object_id, created=proof.object_created).first()
        if native is None: continue
        row = index.get(proof.resource_key)
        if row and proof.model_label in ('ipam.prefix', 'ipam.vlan', 'ipam.vrf'):
            row['native_href'] = native.get_absolute_url()
        elif proof.model_label == 'ipam.ipaddress':
            for source in rows:
                if proof.resource_key.startswith(source['key'] + ':'):
                    source.setdefault('ip_links', {})[str(native.address.ip)] = native.get_absolute_url()


def panel(user, obj):
    if not user.has_perm('netbox_guard.view_resourceregistry'):
        return None
    proof = ProviderCreatedObject.objects.filter(model_label=obj._meta.label_lower, object_id=obj.pk,
        object_created=obj.created, provider_key__startswith='routing:').first()
    if proof is None: return None
    registry = ProviderResourceRegistry.objects.filter(pk=proof.account).first()
    if registry is None: return None
    rows, _ = build_tree(registry.snapshot['resources'].values())
    decorate(user, proof.account, rows)
    key = proof.resource_key
    source = next((r for r in rows if r['key'] == key or key.startswith(r['key'] + ':')), None)
    if source is None: return None
    relations = list(registry.snapshot['relations'].values())
    router = next((r for r in rows if r['kind'] == 'global_router' and (r['key'] == source['key'] or
        any(c['key'] == source['key'] for c in components(r, rows, relations)))), None)
    if router is None: return None
    value = routing_context(rows, relations, router, '', registry.snapshot)
    value['router_url'] = router['detail_href']
    value['account'] = proof.account
    if source['kind'] != 'global_router':
        value['networks'] = [n for n in value['networks'] if n['key'] == source['key'] or any(s['key'] == source['key'] for s in n['subnets'])]
        value['routes'] = [r for r in value['routes'] if r['key'] == source['key']]
    value['routes'] = sorted(value['routes'], key=lambda r: -int(r['cidr'].rsplit('/', 1)[-1]) if '/' in r['cidr'] else 0)
    return value
