"""Pure DNS/storage read model. No guessed ownership, persistence or writes."""
import copy
import json
from collections import Counter
from html import escape

from .client import sanitize


def key(account, project='', region='', kind='account', native_id='', parent=''):
    return json.dumps(['selectel', str(account), project, region, kind, parent, native_id],
                      ensure_ascii=False, separators=(',', ':'))


def registry(document):
    account = str(document['account'])
    nodes, edges, unresolved = {}, {}, []

    def node(ident, kind, name, observation=None):
        target = nodes.setdefault(ident, {'key': ident, 'kind': kind, 'name': name, 'observations': []})
        if observation is not None and observation not in target['observations']:
            target['observations'].append(copy.deepcopy(observation))
        return ident

    def edge(source, target, relation):
        ident = (source, target, relation)
        edges[ident] = {'source': source, 'target': target, 'relation': relation,
                        'status': 'provider_reported'}

    root = node(key(account), 'account', account)
    datasets = [d for d in document.get('datasets', []) if d.get('service') in
                ('selectel-dns', 'object-store', 'storage')]
    for ds in datasets:
        project, region = ds.get('project', ''), ds.get('region', '')
        if not project:
            unresolved.append({'code': 'PROJECT_SCOPE_MISSING', 'kind': ds.get('kind')})
            continue
        pk = node(key(account, project, kind='project', native_id=project), 'project', project)
        edge(root, pk, 'contains')
        kind = {'zones': 'dns_zone', 'rrsets': 'dns_rrset', 'buckets': 'storage_container'}.get(ds['kind'])
        if not kind:
            continue
        for item in ds.get('items', []):
            native = item.get('name') if kind == 'storage_container' else item.get('id')
            parent = ds.get('resource_id', '') if kind == 'dns_rrset' else ''
            if not native or (kind == 'dns_rrset' and not parent):
                unresolved.append({'code': 'RESOURCE_ID_MISSING', 'project': project, 'kind': kind})
                continue
            ident = key(account, project, region, kind, native, parent)
            node(ident, kind, item.get('name', native),
                 {'section': ds['kind'], 'status': ds['status'], 'data': sanitize(item)})
            if kind == 'dns_rrset':
                edge(key(account, project, region, 'dns_zone', parent), ident, 'contains')
            else:
                edge(pk, ident, 'contains')

    for ds in datasets:
        if ds['kind'] not in ('container_options', 'container_domains') or not ds.get('resource_id'):
            continue
        ident = key(account, ds.get('project', ''), ds.get('region', ''),
                    'storage_container', ds['resource_id'])
        if ident not in nodes:
            unresolved.append({'code': 'CONTAINER_NOT_OBSERVED', 'key': ident, 'section': ds['kind']})
            continue
        observation = {'section': ds['kind'], 'status': ds['status'], 'data': sanitize(ds.get('items', []))}
        node(ident, 'storage_container', ds['resource_id'], observation)
        # A custom domain is an attachment, not proof of DNS-zone or server ownership.
        for item in ds.get('items', []) if ds['kind'] == 'container_domains' else []:
            for domain in item.get('domains', []):
                dk = node(key(account, ds.get('project', ''), ds.get('region', ''),
                              'storage_domain', domain, ds['resource_id']), 'storage_domain', domain)
                edge(ident, dk, 'custom_domain')

    for ident, relation in list(edges.items()):
        if relation['source'] not in nodes or relation['target'] not in nodes:
            unresolved.append({**relation, 'status': 'unconfirmed', 'code': 'PARENT_NOT_OBSERVED'})
            del edges[ident]
    for n in nodes.values():
        sections = {}
        for obs in n['observations']:
            sections.setdefault(obs['section'], set()).add(json.dumps(obs['data'], sort_keys=True))
        n['conflicting_sections'] = sorted(k for k, values in sections.items() if len(values) > 1)
        n['observations'].sort(key=lambda x: json.dumps(x, sort_keys=True))
    return {'schema': 'selectel-resource-registry-v1', 'account': account,
        'observed_at': document.get('finished_at', document.get('observed_at')),
        'writes_performed': False, 'snapshot_only': True,
        'counts': dict(sorted(Counter(n['kind'] for n in nodes.values()).items())),
        'resources': [nodes[k] for k in sorted(nodes)],
        'relations': [edges[k] for k in sorted(edges)],
        'unconfirmed_relations': unresolved,
        'coverage': copy.deepcopy(document.get('coverage', [])),
        'limitations': ['Missing resources do not imply deletion.',
            'DNS address values do not prove server ownership.',
            'Multipart suffixes do not establish container relationships.',
            'No NetBox objects, IP assignments or physical links are created.']}


def registry_html(result):
    rows = []
    names = {n['key']: n['name'] for n in result['resources']}
    for n in result['resources']:
        scope = json.loads(n['key'])
        cells = [n['kind'], n['name'], scope[2], scope[3],
                 ', '.join(n['conflicting_sections']) or '—']
        rows.append('<tr>' + ''.join('<td>' + escape(str(c)) + '</td>' for c in cells) + '</tr>')
    relations = ''.join('<tr>' + ''.join('<td>' + escape(str(v)) + '</td>' for v in
        (names[r['source']], r['relation'], names[r['target']], r['status'])) + '</tr>'
        for r in result['relations'])
    return ('<!doctype html><meta charset="utf-8"><title>Selectel resource registry</title>'
        '<h1>Selectel: DNS / S3</h1><p>Read-only snapshot. Provider-reported relationships; '
        'no inferred server ownership. Full observations and relations: resource-registry.json.</p>'
        '<table border="1" cellpadding="6"><tr><th>Kind</th><th>Name</th><th>Project</th>'
        '<th>Region</th><th>Conflicting sections</th></tr>' + ''.join(rows) + '</table>'
        '<h2>Provider-reported relations</h2><table border="1" cellpadding="6">'
        '<tr><th>From</th><th>Relation</th><th>To</th><th>Evidence</th></tr>' + relations + '</table>')
