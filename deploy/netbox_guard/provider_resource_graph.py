"""Permission-filtered, typed Selectel read model for future infrastructure maps."""
import json
from django.apps import apps
from django.core.exceptions import PermissionDenied
from django.http import Http404
from .models import ProviderResourceRegistry, ProviderInventory, ProviderBinding, ProviderAccountFence
from .provider_service import MODELS
from .resource_tree import build_tree


def evidence_state(row):
    if row.get('present_in_latest') is False:
        return 'retained'
    sections = row.get('sections', {}).values()
    if any(s.get('retained') or s.get('latest_status', s.get('status')) not in ('collected', 'empty') for s in sections):
        return 'partial'
    return 'observed'


def document(user, account):
    if not user.has_perm('netbox_guard.view_resourceregistry'):
        raise PermissionDenied
    if ProviderAccountFence.objects.filter(account=account, deleted=True).exists():
        raise Http404
    stored = ProviderResourceRegistry.objects.filter(pk=account).first()
    servers = list(ProviderInventory.objects.filter(account=account))
    if stored is None and not servers:
        raise Http404
    snapshot = stored.snapshot if stored else {'resources': {}, 'relations': {}, 'coverage': []}
    rows, _ = build_tree(snapshot['resources'].values(), servers)
    # Include project/account anchors as well as navigable leaf cards.
    rows.extend(r for r in snapshot['resources'].values() if r['kind'] in ('account', 'project'))
    nodes = {row['key']: dict(id=row['key'], kind=row['kind'], name=row['name'], source='selectel',
                account=account, observed_at=row.get('last_seen'), state=evidence_state(row),
                project=row.get('project', json.loads(row['key'])[2]), region=row.get('region', ''),
                external_id=row['native_id'] if 'native_id' in row else json.loads(row['key'])[6],
                sections=row.get('sections', {})) for row in rows}
    edges = [dict(source=e['source'], target=e['target'], kind=e['relation'],
                  evidence_source='selectel', observed_at=e.get('last_seen'),
                  state='provider_reported' if e.get('present_in_latest') else 'retained')
             for e in snapshot['relations'].values() if e['source'] in nodes and e['target'] in nodes]
    bindings = list(ProviderBinding.objects.filter(account=account))
    for kind, label in MODELS.items():
        targets = {obj.pk: obj for obj in apps.get_model(label).objects.restrict(user, 'view').filter(
            pk__in=[b.object_id for b in bindings if b.resource == kind])}
        for binding in (b for b in bindings if b.resource == kind and b.provider_key in nodes):
            target = targets.get(binding.object_id)
            if target is None or target.created != binding.object_created:
                continue
            native_key = f'netbox:{label.lower()}:{target.pk}:{target.created.isoformat()}'
            nodes[native_key] = dict(id=native_key, kind=label.lower(), name=target.name,
                                    source='netbox', object_id=target.pk, url=target.get_absolute_url(),
                                    observed_at=target.last_updated, state='native')
            edges.append(dict(source=binding.provider_key, target=native_key, kind='bound_to',
                              evidence_source='guard', state='confirmed', observed_at=binding.created_at,
                              revision=binding.revision))
    from .provider_component_graph import extend
    extend(user, account, nodes, edges)
    return dict(schema='netbox-sync.provider-resources.v1', account=account,
                observed_at=stored.observed_at if stored else None,
                nodes=list(nodes.values()), edges=edges, coverage=snapshot.get('coverage', []),
                writes_performed=False,
                limitations=['PROVIDER_ALLOCATION_IS_NOT_INTERFACE_OWNERSHIP',
                             'DNS_VALUES_ARE_NOT_SERVER_BINDINGS', 'TRAFFIC_REACHABILITY_NOT_EVALUATED'])
