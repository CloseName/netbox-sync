"""Coverage describes requests and visibility, never total account completeness."""
from collections import Counter, defaultdict

CATEGORIES = {
    'collected': 'collected',
    'UNSUPPORTED_SERVICE': 'unsupported',
    'PRODUCT_ADAPTER_NOT_IMPLEMENTED': 'unsupported',
    'UNTRUSTED_OR_INVALID_ENDPOINT': 'blocked_endpoint',
    'NOT_IN_CATALOG': 'not_in_catalog',
    'SKIPPED_LEGACY_API': 'skipped',
    'SKIPPED_DUPLICATE_ENDPOINT': 'skipped',
    'DELEGATED_TO_PROJECT_ADAPTER': 'skipped',
    'HTTP_401': 'access_denied', 'HTTP_403': 'access_denied',
    'HTTP_404': 'unavailable',
}


def category(item):
    status = item['status']
    if status != 'collected' and item.get('pages', 0) and item.get('count', 0):
        return 'partial'
    return CATEGORIES.get(status, 'error')


def summarize(coverage):
    groups = defaultdict(list)
    totals = Counter()
    for item in coverage:
        cat = category(item)
        totals[cat] += 1
        groups[(item['service'], item.get('project', ''), item.get('region', ''))].append(item)
    scopes = []
    for (service, project, region), items in sorted(groups.items()):
        scopes.append({'service': service, 'project': project, 'region': region,
            'categories': dict(Counter(category(x) for x in items)),
            'statuses': dict(Counter(x['status'] for x in items)),
            'all_listed_sections_collected': all(x['status'] == 'collected' for x in items)})
    return {'categories': dict(totals), 'scopes': scopes,
        'account_completeness': 'not_proven',
        'requires_attention': sum(totals[x] for x in ('partial', 'access_denied', 'unavailable', 'error', 'blocked_endpoint'))}


def resource_counts(document):
    """Count records in datasets separately from catalogs and borrowed networks."""
    counts = Counter()
    for ds in document['datasets']:
        service, kind = ds['service'], ds['kind']
        items = ds.get('items', [])
        if service == 'dedicated' and kind == 'resources':
            for obj in items:
                counts['dedicated_servers' if obj.get('service_type') in ('server', 'serverchip', 'custom', 'colocation') else 'other_dedicated_resources'] += 1
        elif service == 'compute' and kind == 'servers':
            counts['cloud_vms'] += len(items)
        elif service == 'network' and kind in ('networks', 'subnets'):
            for obj in items:
                owner = obj.get('project_id') or obj.get('tenant_id')
                scope = 'project_owned' if owner and owner == ds.get('project') else 'other_or_unknown_owner'
                counts[kind + '_' + scope + '_observations'] += 1
        elif service == 'object-store' and kind == 'buckets':
            counts['swift_container_observations'] += len(items)
            counts['swift_multipart_suffix_observations'] += sum(str(x.get('name', '')).endswith('_s3multipartuploads') for x in items)
        elif (service, kind) in (('compute', 'flavors'), ('image', 'images')):
            counts[kind + '_catalog_observations'] += len(items)
        elif service == 'volumev3' or service == 'volumev2':
            counts['cloud_' + kind] += len(items)
        elif service == 'selectel-dns' and kind == 'zones':
            counts['dns_zones'] += len(items)
        elif service == 'selectel-dns' and kind == 'rrsets':
            counts['dns_rrsets'] += len(items)
            counts['dns_records'] += sum(len(item.get('records', [])) for item in items)
    return dict(counts)
