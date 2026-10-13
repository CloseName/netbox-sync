"""Allowlisted DNS and storage metadata. Never GET objects, logs or certificates."""
import re
from urllib.parse import quote

from .client import AuditError, field_shapes, read_collection, sanitize, validate_url

DNS = 'https://api.selectel.ru/domains/v2'


def pick(obj, fields):
    if not isinstance(obj, dict):
        raise AuditError('UNEXPECTED_RESPONSE_SHAPE')
    result = {}
    for key, typ in fields.items():
        if key in obj:
            value = obj[key]
            if value is not None and type(value) is not typ:
                raise AuditError('UNEXPECTED_FIELD_TYPE')
            result[key] = value
    return result


def path_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise AuditError('INVALID_RESOURCE_ID')
    return value


def container_path(value):
    if (not isinstance(value, str) or not value or len(value.encode('utf-8')) > 256 or
            value in ('.', '..') or re.search(r'[/\\%?#\x00-\x20\x7f]', value)):
        raise AuditError('UNSAFE_CONTAINER_NAME')
    return quote(value, safe='')


def zone(obj, project=None):
    result = pick(obj, {'id': str, 'name': str, 'status': str, 'project_id': str})
    path_id(result.get('id'))
    if project is not None and result.get('project_id') not in (None, project):
        raise AuditError('DNS_PROJECT_ID_MISMATCH')
    return result


def rrset(obj, zone_id):
    result = pick(obj, {'id': str, 'name': str, 'ttl': int, 'type': str, 'zone_id': str, 'managed_by': str})
    path_id(result.get('id'))
    if result.get('zone_id', zone_id) != zone_id:
        raise AuditError('DNS_ZONE_ID_MISMATCH')
    result['zone_id'] = zone_id
    records = obj.get('records')
    if not isinstance(records, list):
        raise AuditError('UNEXPECTED_RESPONSE_SHAPE')
    result['records'] = []
    for record in records:
        item = pick(record, {'content': str, 'disabled': bool})
        if not isinstance(item.get('content'), str):
            raise AuditError('UNEXPECTED_FIELD_TYPE')
        result['records'].append(item)
    return result


def container(obj):
    result = pick(obj, {'name': str, 'bytes': int, 'count': int, 'last_modified': str})
    container_path(result.get('name'))
    # This suffix is only a hint; it neither proves type nor excludes a resource.
    result['multipart_name_hint'] = result['name'].endswith('_s3multipartuploads')
    return result


def options(obj):
    if not isinstance(obj, dict) or not any(k in obj for k in ('general', 'quota', 'web')):
        raise AuditError('UNEXPECTED_RESPONSE_SHAPE')
    shapes = {'general': {'cache_control': str, 'default_delete_after': int, 'type': str},
              'quota': {'max_bytes_used': int, 'max_object_count': int},
              'web': {'error': str, 'error_status_code': int, 'index': str,
                      'listing_css': str, 'listing_enabled': bool}}
    return {key: pick(obj[key], shape) for key, shape in shapes.items() if key in obj}


def domains(obj):
    if not isinstance(obj, dict) or not isinstance(obj.get('domains'), list):
        raise AuditError('UNEXPECTED_RESPONSE_SHAPE')
    if not all(isinstance(v, str) for v in obj['domains']):
        raise AuditError('UNEXPECTED_FIELD_TYPE')
    return {'domains': obj['domains']}


def save(collector, service, kind, project, region, items, status, *, resource_id=None, pages=0, dependency=None, request_attempted=None):
    context = dict(service=service, kind=kind, project=project, region=region)
    if resource_id is not None:
        context['resource_id'] = resource_id
    if dependency is not None:
        context['dependency'] = dependency
    if request_attempted is not None:
        context['request_attempted'] = request_attempted
    clean = sanitize(items, collector.credentials.secrets)
    collector.document['coverage'].append({**context, 'status': status, 'count': len(clean), 'pages': pages})
    collector.document['datasets'].append({**context, 'status': status, 'items': clean,
        'fields': {k: sorted(v) for k, v in field_shapes(clean).items()}})
    return clean


def collection(collector, service, kind, url, token, key, mode, projector, project, region='', resource_id=None):
    raw, pages, status = read_collection(collector.client, url, token, key, mode)
    projected = []
    for obj in raw:
        try:
            projected.append(projector(obj))
        except AuditError as exc:
            # Retain successfully read rows, but never label this collection complete.
            status = str(exc) if status == 'collected' else status
    return save(collector, service, kind, project, region, projected, status,
                resource_id=resource_id, pages=len(pages))


def collect_dns(collector, token, project):
    zones = collection(collector, 'selectel-dns', 'zones', DNS + '/zones', token,
                       'result', 'offset', lambda obj: zone(obj, project), project)
    root_status = collector.document['coverage'][-1]['status']
    if not zones:
        save(collector, 'selectel-dns', 'rrsets', project, '', [],
             'collected' if root_status == 'collected' else 'PARENT_COLLECTION_UNAVAILABLE',
             dependency={'kind': 'zones', 'status': root_status}, request_attempted=False)
    for ident in sorted({z['id'] for z in zones}):
        collection(collector, 'selectel-dns', 'rrsets', DNS + '/zones/' + path_id(ident) + '/rrset',
                   token, 'result', 'offset', lambda obj: rrset(obj, ident), project, resource_id=ident)


def storage_endpoint(catalog, region):
    urls = {ep.get('url', '').rstrip('/') for service in catalog if service.get('type') == 'storage'
            for ep in service.get('endpoints', []) if ep.get('interface') == 'public' and
            (ep.get('region_id') or ep.get('region') or '') == region}
    if not urls:
        raise AuditError('STORAGE_ENDPOINT_NOT_IN_CATALOG')
    if len(urls) != 1:
        raise AuditError('AMBIGUOUS_STORAGE_ENDPOINT')
    url = next(iter(urls))
    try:
        parts = validate_url(url)
    except (AuditError, ValueError):
        raise AuditError('UNTRUSTED_OR_INVALID_ENDPOINT') from None
    if parts.path not in ('', '/v2') or parts.query:
        raise AuditError('UNEXPECTED_STORAGE_ENDPOINT_PATH')
    return url if parts.path == '/v2' else url + '/v2'


def collect_storage_details(collector, token, catalog, project):
    lists = [ds for ds in collector.document['datasets']
             if ds['service'] == 'object-store' and ds['kind'] == 'buckets' and ds['project'] == project]
    seen = set()
    for ds in lists:
        region = ds['region']
        if not ds['items']:
            for kind in ('container_options', 'container_domains'):
                save(collector, 'storage', kind, project, region, [],
                     'collected' if ds['status'] == 'collected' else 'PARENT_COLLECTION_UNAVAILABLE',
                     dependency={'kind': 'buckets', 'status': ds['status']}, request_attempted=False)
            continue
        try:
            base, endpoint_error = storage_endpoint(catalog, region), None
        except AuditError as exc:
            base, endpoint_error = '', str(exc)
        for item in ds['items']:
            name = item.get('name')
            if (region, name) in seen:
                continue
            seen.add((region, name))
            for kind, suffix, projector in (('container_options', 'options', options),
                                            ('container_domains', 'domains', domains)):
                items, status = [], 'collected'
                try:
                    if endpoint_error:
                        raise AuditError(endpoint_error)
                    path = container_path(name)
                    raw, _ = collector.client.request(base + '/containers/' + path + '/' + suffix, token)
                    items = [projector(raw)]
                except AuditError as exc:
                    status = str(exc)
                save(collector, 'storage', kind, project, region, items, status, resource_id=name)


def export(document):
    """Portable child inventory; identity is scoped to account/project/region/parent."""
    return {'schema': 'selectel-dns-storage-v1', 'account': document['account'],
            'observed_at': document.get('finished_at'), 'writes_performed': False,
            'datasets': [ds for ds in document.get('datasets', [])
                         if ds['service'] in ('selectel-dns', 'object-store', 'storage')],
            'coverage': [r for r in document.get('coverage', [])
                         if r['service'] in ('selectel-dns', 'object-store', 'storage')],
            'limitations': ['No object bodies, object listing, logs or certificates are requested.',
                           'S3 versioning, lifecycle and S3 policy API are not collected.',
                           'DNS and bucket metadata are not automatically projected into NetBox.']}
