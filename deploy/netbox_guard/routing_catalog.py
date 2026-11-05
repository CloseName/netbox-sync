"""Permission-filtered navigation over existing routing domains (no new IPAM objects)."""
from hashlib import sha256
from urllib.parse import urlencode
from django.urls import reverse
from ipam.models import VRF
from .models import ProviderCreatedObject, ProviderResourceRegistry, ProviderInventory
from .resource_tree import build_tree
from .routing_browser import card, data
from .routing_presentation import components
from .network_search import route_matches, rank


def detail_url(account, row):
    return reverse('plugins:netbox_guard:provider_resource_account', kwargs={'account': account}) + '?' + urlencode({
        'kind': row['kind'], 'resource': sha256(row['key'].encode()).hexdigest()})


def domains(user, routers_only=False):
    if not user.has_perm('netbox_guard.view_resourceregistry'):
        return
    visible = {v.pk: v for v in VRF.objects.restrict(user, 'view').select_related('tenant')}
    registries = {}
    proofs = ProviderCreatedObject.objects.filter(model_label='ipam.vrf', object_id__in=visible)
    if routers_only:
        proofs = proofs.filter(provider_key__startswith='routing:')
    for proof in proofs.order_by('account', 'object_id'):
        vrf = visible[proof.object_id]
        if vrf.created != proof.object_created:
            continue
        if proof.provider_key.startswith('routing:'):
            if proof.account not in registries:
                registry = ProviderResourceRegistry.objects.filter(pk=proof.account).first()
                registries[proof.account] = registry.snapshot if registry else None
            snapshot = registries[proof.account]
            if not snapshot:
                continue
            rows, _ = build_tree(snapshot['resources'].values())
            router = next((r for r in rows if r['key'] == proof.resource_key and r['kind'] == 'global_router'), None)
            if router:
                children = components(router, rows, snapshot['relations'].values())
                zones = sorted({data(r).get('zone_name') for r in children
                                if r['kind'] == 'routing_network' and data(r).get('zone_name')})
                yield dict(account=proof.account, name=card(router)['name'], kind='Глобальный роутер',
                    url=detail_url(proof.account, router), vrf=vrf, project='Глобальный роутинг',
                    zone=', '.join(zones) or 'Не указано', children=children)
        elif proof.provider_key.startswith('component:'):
            inventory = ProviderInventory.objects.filter(pk=proof.resource_key, account=proof.account).first()
            ident = inventory.snapshot.get('identity', {}) if inventory else {}
            name = vrf.name.removeprefix('Selectel / ' + proof.account + ' / ')
            # Names are labels only; ownership always uses stored IDs and creation time.
            if name.endswith(']') and ' [' in name:
                name = name.rsplit(' [', 1)[0]
            yield dict(account=proof.account, name=name, kind='Облачная сеть', url=vrf.get_absolute_url(), vrf=vrf,
                project=vrf.tenant.name if vrf.tenant else ident.get('project') or 'Общие ресурсы аккаунта',
                zone=ident.get('region') or 'Не указано', children=[])


def routes(user, query, exact=False):
    result = []
    for domain in domains(user, routers_only=True):
        for row in domain['children']:
            if row['kind'] != 'routing_route' or not route_matches(query, data(row), exact):
                continue
            value = card(row)
            value.update(account=domain['account'], router=domain['name'], router_url=domain['url'],
                         href=detail_url(domain['account'], row))
            result.append(value)
    return sorted(result, key=lambda r: (rank(query, r['cidr'], True), r['account'], r['router'], r['name']))
