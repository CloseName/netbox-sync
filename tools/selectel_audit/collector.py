"""Account inventory, with per-project/region coverage rather than a success boolean."""
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit

from .client import (AuditError, Client, IDENTITY, read_collection, sanitize,
                     field_shapes, validate_url)
from . import VERSION

DEDICATED = 'https://api.selectel.ru/servers/v2'
PROJECTS = 'https://api.selectel.ru/iam/v1/projects'
RESELL = 'https://api.selectel.ru/vpc/resell/v2'
DNS = 'https://api.selectel.ru/domains/v2'

# Only metadata collections; no bucket contents, credentials, console or guest payloads.
SERVICES = {
    'compute': [('servers', 'servers/detail', 'servers'), ('flavors', 'flavors/detail', 'flavors')],
    'network': [(x, 'v2.0/' + x, x) for x in
                ('networks', 'subnets', 'ports', 'floatingips', 'routers', 'security-groups')],
    'volumev3': [('volumes', 'volumes/detail', 'volumes'),
                 ('snapshots', 'snapshots/detail', 'snapshots')],
    'volumev2': [('volumes', 'volumes/detail', 'volumes'),
                 ('snapshots', 'snapshots/detail', 'snapshots')],
    'image': [('images', 'v2/images', 'images')],
    'load-balancer': [('loadbalancers', 'v2/lbaas/loadbalancers', 'loadbalancers')],
    'object-store': [('buckets', '', None)],
    'dns': [('zones', 'v2/zones', 'zones')],
}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def child_url(base, path):
    # Catalog endpoints may already include their API version.
    base = base.rstrip('/')
    for version in ('v2.0', 'v2'):
        if base.endswith('/' + version) and path.startswith(version + '/'):
            path = path[len(version) + 1:]
    return base + ('/' + path if path else '')


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise AuditError('INVALID_RESOURCE_ID')
    return value


class Credentials:
    def __init__(self, account, *, token='', username='', password=''):
        if not re.fullmatch(r'[0-9]{1,20}', account):
            raise AuditError('INVALID_ACCOUNT_NUMBER')
        self.account, self.token = account, token
        self.username, self.password = username, password
        self.secrets = [token, password]
        self.domain_id = None
        self.expires_at = None

    def authenticate(self, client, project=None):
        if project is None and self.token:
            data, _ = client.request(IDENTITY + '/auth/tokens', self.token, subject=True)
            token = self.token
        else:
            if self.password:
                identity = {'methods': ['password'], 'password': {'user': {
                    'name': self.username, 'domain': {'name': self.account}, 'password': self.password}}}
            else:
                identity = {'methods': ['token'], 'token': {'id': self.token}}
            scope = {'project': {'id': project}} if project else {'domain': {'name': self.account}}
            data, token = client.request(IDENTITY + '/auth/tokens', payload={
                'auth': {'identity': identity, 'scope': scope}})
        if not token or not isinstance(data, dict) or not isinstance(data.get('token'), dict):
            raise AuditError('INVALID_AUTH_RESPONSE')
        info = data['token']
        scope_data = info.get('project' if project else 'domain', {})
        domain = scope_data.get('domain', {}) if project else scope_data
        if domain.get('name') != self.account:
            raise AuditError('ACCOUNT_SCOPE_MISMATCH_USE_ACCOUNT_IAM_TOKEN')
        if project and scope_data.get('id') != project:
            raise AuditError('PROJECT_SCOPE_MISMATCH')
        if not domain.get('id'):
            raise AuditError('MISSING_DOMAIN_ID')
        if self.domain_id and self.domain_id != domain['id']:
            raise AuditError('ACCOUNT_DOMAIN_MISMATCH')
        self.domain_id = domain['id']
        self.secrets.append(token)
        if not project:
            self.token = token
            self.expires_at = info.get('expires_at')
        return token, info.get('catalog', [])


class Collector:
    def __init__(self, credentials, client=None, progress=print, profile='all'):
        if profile not in ('all', 'servers'):
            raise ValueError('INVALID_PROFILE')
        self.profile = profile
        self.credentials = credentials
        self.client = client or Client()
        self.progress = progress
        self.document = {
            'schema': 'selectel-audit-v1', 'collector_version': VERSION, 'started_at': stamp(),
            'account': credentials.account, 'mode': 'read_only', 'profile': profile,
            'scope': 'resources_visible_to_supplied_identity',
            'account_completeness': 'not_proven',
            'coverage': [], 'datasets': [], 'catalog': [], 'projects': [],
            'limitations': [
                'API permissions may hide projects/resources even with HTTP 200.',
                'Collected means enumeration succeeded for this endpoint, not full-account certification.',
                'Catalog presence does not prove that a product has purchased resources.',
                'No S3 objects, DNS record contents, console or guest files are requested; secrets are excluded from exports.',
                'Unsupported products are reported; no writes or automatic NetBox adoption occur.',
            ],
        }

    def collect(self, service, kind, url, token, key='result', mode='links', project='', region=''):
        items, pages, status = read_collection(self.client, url, token, key, mode)
        context = dict(service=service, kind=kind, project=project, region=region)
        self.document['coverage'].append({**context, 'status': status, 'count': len(items),
                                           'endpoint': url, 'pages': len(pages)})
        shapes = field_shapes(pages)
        self.document['datasets'].append({**context, 'status': status,
            'items': sanitize(items, self.credentials.secrets),
            'responses': sanitize(pages, self.credentials.secrets),
            'fields': {k: sorted(v) for k, v in shapes.items()}})
        return items

    def detail(self, kind, url, token, resource_id):
        try:
            data, _ = self.client.request(url, token)
            if not isinstance(data, dict) or not isinstance(data.get('result'), dict):
                raise AuditError('UNEXPECTED_RESPONSE_SHAPE')
            value = data['result']
            if kind == 'operating_system':
                # This endpoint may also return passwords, SSH keys and scripts.
                # Discard them before field discovery, sanitization or export.
                value = {k: v for k, v in value.items() if k in {
                    'arch', 'os_template', 'version', 'template_version', 'raid_type',
                    'partitions', 'partitions_config', 'is_processing',
                    *[prefix + suffix for prefix in ('', 'local_')
                      for suffix in ('ipv4_address', 'ipv4_gateway', 'ipv4_netmask',
                                     'ipv6_address', 'ipv6_gateway', 'ipv6_netmask')]}}
                def scalar_fields(obj, names):
                    return {k: v for k, v in obj.items() if k in names and
                            (v is None or type(v) in (str, int, float, bool))} if isinstance(obj, dict) else {}
                if isinstance(value.get('partitions'), list):
                    value['partitions'] = [scalar_fields(v, ('expand', 'fstype', 'mount', 'size'))
                                           for v in value['partitions']]
                if isinstance(value.get('partitions_config'), dict):
                    value['partitions_config'] = {k: scalar_fields(v, ('type', 'device', 'fstype', 'mount', 'size', 'level'))
                                                  for k, v in value['partitions_config'].items()}
            items, status = [value], 'collected'
        except AuditError as exc:
            items, status = [], str(exc)
        self.document['coverage'].append(dict(service='dedicated', kind=kind, project='',
            region='', status=status, count=len(items), endpoint=url))
        self.document['datasets'].append(dict(service='dedicated', kind=kind, project='',
            region='', resource_id=resource_id, status=status,
            items=sanitize(items, self.credentials.secrets),
            fields={k: sorted(v) for k, v in field_shapes(items).items()}))

    def collect_dedicated(self, token):
        self.progress('Выделенные серверы: ресурсы, размещение, сети и детали…')
        resources = self.collect('dedicated', 'resources', DEDICATED + '/resource', token, mode='page')
        for kind, path, mode in [
            ('locations', '/location', 'single'), ('networks', '/network', 'page'),
            ('ports', '/network/port', 'single'), ('public_ips', '/network/ipam/ip', 'single'),
            ('private_ips', '/network/ipam/local_ip', 'single'),
            ('public_subnets', '/network/ipam/subnet', 'single'),
            ('private_subnets', '/network/ipam/local_subnet', 'single'),
        ]:
            self.collect('dedicated', kind, DEDICATED + path, token, mode=mode)
        for item in resources:
            if self.profile == 'servers' and item.get('service_type') not in ('server', 'serverchip', 'custom', 'colocation'):
                continue
            try:
                ident = safe_id(item.get('uuid'))
            except AuditError:
                continue
            self.detail('resource_detail', DEDICATED + '/resource/' + ident, token, ident)
            resource_type = item.get('service_type')
            if resource_type in ('server', 'serverchip', 'custom', 'colocation', 'network_equipment', 'port'):
                self.detail('resource_info', DEDICATED + '/resource/' + ident + '/info/' + resource_type,
                            token, ident)
            if self.profile == 'servers' and resource_type in ('server', 'serverchip', 'custom'):
                self.detail('operating_system', DEDICATED + '/boot/os/' + ident, token, ident)

    def collect_catalog(self, token, catalog, project):
        seen, types = set(), set()
        modern_regions = set()
        for service in catalog:
            if service.get('type') not in ('volumev3', 'volume'):
                continue
            for ep in service.get('endpoints', []):
                if ep.get('interface') == 'public' and '/v3/' in ep.get('url', ''):
                    try:
                        validate_url(ep['url'])
                    except (AuditError, ValueError):
                        continue
                    modern_regions.add(ep.get('region_id') or ep.get('region') or '')
        for service in catalog:
            catalog_type = service.get('type', '')
            for endpoint in service.get('endpoints', []):
                if endpoint.get('interface') != 'public':
                    continue
                url = endpoint.get('url', '')
                region = endpoint.get('region_id') or endpoint.get('region') or ''
                typ = 'volumev3' if catalog_type == 'volume' and '/v3/' in url else catalog_type
                context = dict(service=typ, project=project, region=region, endpoint=url)
                if self.profile == 'servers' and typ not in ('compute', 'network', 'volumev3', 'volumev2', 'image'):
                    continue
                if (typ, region, url) in seen:
                    self.document['coverage'].append({**context, 'kind': 'catalog',
                        'status': 'SKIPPED_DUPLICATE_ENDPOINT', 'count': 0})
                    continue
                seen.add((typ, region, url))
                types.add(typ)
                self.document['catalog'].append({**context, 'catalog_type': catalog_type})
                if typ == 'volumev2' and region in modern_regions:
                    self.document['coverage'].append({**context, 'kind': 'catalog',
                        'status': 'SKIPPED_LEGACY_API', 'count': 0})
                    continue
                if typ == 'dnsv2':
                    self.document['coverage'].append({**context, 'kind': 'catalog',
                        'status': 'DELEGATED_TO_PROJECT_ADAPTER', 'count': 0})
                    continue
                # Classify unsupported technical endpoints as unsupported; no request is made.
                if typ not in SERVICES:
                    self.document['coverage'].append({**context, 'kind': 'catalog',
                        'status': 'UNSUPPORTED_SERVICE', 'count': 0})
                    continue
                try:
                    validate_url(url)
                except (AuditError, ValueError):
                    self.document['coverage'].append({**context, 'kind': 'catalog',
                        'status': 'UNTRUSTED_OR_INVALID_ENDPOINT', 'count': 0})
                    continue
                for kind, path, key in SERVICES[typ]:
                    actual_key = key.replace('-', '_') if key else None
                    self.collect(typ, kind, child_url(url, path), token, actual_key,
                                 mode='swift' if typ == 'object-store' else 'glance' if typ == 'image' else 'links',
                                 project=project, region=region)
        for typ in (('compute', 'network', 'volumev3', 'image') if self.profile == 'servers'
                    else ('compute', 'network', 'volumev3', 'object-store')):
            if typ not in types and not (typ == 'volumev3' and 'volumev2' in types):
                self.document['coverage'].append(dict(service=typ, project=project, region='',
                    kind='catalog', status='NOT_IN_CATALOG', count=0))

    def run(self):
        token, _ = self.credentials.authenticate(self.client)
        self.document['account_verified'] = True
        self.document['domain_id'] = self.credentials.domain_id
        self.document['authentication_expires_at'] = self.credentials.expires_at
        self.progress('Аккаунт подтверждён. Получаю доступные проекты…')
        projects = self.collect('iam', 'projects', PROJECTS, token, 'projects', 'single')
        resell = self.collect('resell', 'projects', RESELL + '/projects', token, 'projects', 'single')
        self.collect('resell', 'floatingips', RESELL + '/floatingips?detailed=true', token,
                     'floatingips', 'single')
        self.collect('resell', 'subnets', RESELL + '/subnets', token, 'subnets', 'single')
        self.collect_dedicated(token)
        self.collect('global-router', 'routers', 'https://api.selectel.ru/naas/v1/routers',
                     token, None, 'page')
        merged = {}
        for item in projects + resell:
            ident = item.get('id') or item.get('uuid')
            try:
                safe_id(ident)
            except AuditError:
                continue
            merged[ident] = {**merged.get(ident, {}), **item, 'id': ident}
        self.document['projects'] = sanitize(list(merged.values()), self.credentials.secrets)
        for number, (ident, project) in enumerate(merged.items(), 1):
            self.progress(f'Проект {number}/{len(merged)}: {ident} — каталог и ресурсы…')
            try:
                scoped, catalog = self.credentials.authenticate(self.client, ident)
                self.collect_catalog(scoped, catalog, ident)
                if self.profile == 'all':
                    self.collect('selectel-dns', 'zones', DNS + '/zones', scoped, 'result', 'offset', project=ident)
            except AuditError as exc:
                self.document['coverage'].append(dict(service='identity', kind='project_auth',
                    project=ident, region='', status=str(exc), count=0))
        if not merged:
            self.document['limitations'].append('No accessible projects discovered; cloud inventory is unverified.')
        for product in (('managed-kubernetes', 'managed-databases', 'container-registry',
                        'vmware-cloud-director', 'cdn', 'cloud-1c', 'mail', 'mobile-farm') if self.profile == 'all' else ()):
            self.document['coverage'].append(dict(service=product, kind='product', project='',
                region='', status='PRODUCT_ADAPTER_NOT_IMPLEMENTED', count=0))
        self.document['finished_at'] = stamp()
        self.document['requests'] = self.client.requests
        return sanitize(self.document, self.credentials.secrets)


def source_bindings(obj):
    """Export a narrow identity projection, never arbitrary custom fields."""
    fields = obj.get('custom_fields') or {}
    if not isinstance(fields, dict):
        return {'status': 'invalid_custom_fields_shape'}
    raw = fields.get('sync_identities')
    if raw is None:
        return {'status': 'not_present_in_response', 'identities': []}
    if not isinstance(raw, list):
        return {'status': 'invalid_identities_shape'}
    identities = []
    for value in raw:
        if not isinstance(value, dict):
            return {'status': 'invalid_identity_entry'}
        identities.append({key: value[key] for key in
            ('schema', 'type', 'instance', 'kind', 'external_id')
            if isinstance(value.get(key), (str, int))})
    return {'status': 'exported', 'identities': identities}


def collect_netbox(url, token, ca_file=None, progress=print):
    parts = urlsplit(url.rstrip('/'))
    if parts.path not in ('', '/') or parts.query:
        raise AuditError('NETBOX_URL_MUST_BE_HTTPS_ORIGIN')
    origin = (parts.scheme, parts.netloc.lower())
    validate_url(url.rstrip('/') + '/api/', origin)
    client = Client(ca_file, origin)
    result = {'url': url.rstrip('/'), 'datasets': {}, 'coverage': []}
    routes = {
        'devices': 'dcim/devices/', 'vms': 'virtualization/virtual-machines/',
        'device_interfaces': 'dcim/interfaces/', 'vm_interfaces': 'virtualization/interfaces/',
        'ips': 'ipam/ip-addresses/', 'vrfs': 'ipam/vrfs/',
    }
    for kind, route in routes.items():
        progress('NetBox: ' + kind)
        items, _, status = read_collection(client, result['url'] + '/api/' + route,
                                           token, 'results', 'netbox')
        # Export only fields used by review, not arbitrary custom values or comments.
        keep = ('id', 'name', 'display', 'serial', 'asset_tag', 'status', 'site', 'cluster',
                'device', 'virtual_machine', 'primary_ip4', 'primary_ip6', 'address', 'vrf',
                'assigned_object_type', 'assigned_object_id', 'mac_address', 'primary_mac_address')
        result['datasets'][kind] = [sanitize({**{k: x[k] for k in keep if k in x},
            'source_bindings': source_bindings(x)}, [token]) for x in items]
        result['coverage'].append(dict(kind=kind, status=status, count=len(items)))
    return result
