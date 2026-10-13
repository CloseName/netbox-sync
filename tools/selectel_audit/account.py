"""Versioned account coverage contract. Pure read model; never adopts resources.

Counts are observations per collection, not a sum of distinct owned resources.
Adapter support, collection outcome and actual resource presence are independent.
"""
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    key: str
    title: str
    services: tuple
    scope: str
    sections: tuple = ()
    roots: tuple = ()
    server_profile: bool = False
    gaps: str = ''
    target: str = 'Реестр ресурсов провайдера'


PRODUCTS = (
    Product('projects', 'Аккаунт и проекты', ('iam',), 'account', ('projects',),
            ('projects',), True, 'Постоянное подключение и расписание ещё не реализованы.'),
    Product('dedicated', 'Выделенные ресурсы', ('dedicated',), 'account',
            ('resources', 'locations', 'networks', 'ports', 'public_ips', 'private_ips',
             'public_subnets', 'private_subnets'), ('resources',), True,
            'Состав деталей зависит от типа ресурса; ОС собирается в профиле servers. '
            'NIC ↔ порт требует независимого подтверждения.', 'Device и IPAM через Guard для принятых привязок'),
    Product('compute', 'Облачные серверы', ('compute',), 'catalog',
            ('servers', 'flavors'), ('servers',), True,
            'Автоматическое создание VM ещё не реализовано.', 'VM, интерфейсы и диски: проекция в разработке'),
    Product('network', 'Облачные сети', ('network',), 'catalog',
            ('networks', 'subnets', 'ports', 'floatingips', 'routers', 'security-groups'),
            ('networks', 'subnets', 'ports', 'floatingips', 'routers', 'security-groups'), True,
            'Видимые сети могут принадлежать другому проекту; полного переноса в IPAM нет.'),
    Product('cloud-allocation', 'Выделенные облачные адреса и подсети', ('resell',), 'account',
            ('projects', 'floatingips', 'subnets'), ('floatingips', 'subnets'), True,
            'Наблюдения Resell и Neutron нельзя складывать как разные ресурсы.'),
    Product('volumes', 'Облачные диски и снимки', ('volumev3', 'volumev2'), 'catalog',
            ('volumes', 'snapshots'), ('volumes', 'snapshots'), True,
            'Multiattach и перенос в VirtualDisk требуют отдельной проекции.'),
    Product('images', 'Образы облачных серверов', ('image',), 'catalog',
            ('images',), ('images',), True, 'Каталог образов включает общедоступные образы.'),
    Product('dns', 'DNS-хостинг', ('selectel-dns', 'dnsv2'), 'project',
            ('zones', 'rrsets'), ('zones',), gaps='Читаются зоны и RRsets; переноса записей в NetBox пока нет.'),
    Product('catalog-dns', 'DNS из каталога проекта', ('dns',), 'catalog',
            ('zones',), ('zones',), gaps='Читаются зоны доступного catalog API; записи ещё не собираются.'),
    Product('s3', 'S3 / Swift', ('object-store', 'storage'), 'catalog',
            ('buckets', 'container_options', 'container_domains'), ('buckets',),
            gaps='Контейнеры Swift, статистика, options и домены. Versioning, lifecycle и S3 policy '
                 'ещё не собираются; содержимое объектов не запрашивается.'),
    Product('load-balancer', 'Балансировщики', ('load-balancer',), 'catalog',
            ('loadbalancers',), ('loadbalancers',), gaps='Listeners, pools и members ещё не собираются.'),
    Product('global-router', 'Глобальный роутер', ('global-router',), 'account',
            ('routers',), ('routers',), True, 'Читается список; подключения и маршруты ещё не собираются.'),
    Product('managed-kubernetes', 'Managed Kubernetes', ('managed-kubernetes',), 'project'),
    Product('managed-databases', 'Управляемые базы данных', ('managed-databases',), 'project'),
    Product('container-registry', 'Container Registry', ('container-registry',), 'project'),
    Product('vmware-cloud-director', 'Облако VMware', ('vmware-cloud-director',), 'project'),
    Product('cdn', 'CDN', ('cdn',), 'project'),
    Product('cloud-1c', 'Готовое облако 1С', ('cloud-1c',), 'project'),
    Product('mail', 'Почтовый сервис', ('mail',), 'project'),
    Product('mobile-farm', 'Мобильная ферма', ('mobile-farm',), 'account'),
)

LABELS = {
    'collected': 'Прочитаны поддерживаемые разделы',
    'empty': 'Поддерживаемые списки ресурсов пусты в доступной области',
    'partial': 'Собрано частично', 'access_denied': 'Нет доступа',
    'authentication_failed': 'Ошибка авторизации', 'unavailable': 'API недоступен',
    'unsupported': 'Сборщик не реализован', 'excluded': 'Исключено профилем сбора',
    'not_checked': 'Не проверено', 'not_in_catalog': 'Нет в доступном каталоге',
    'blocked_endpoint': 'Адрес API не разрешён', 'error': 'Ошибка сбора',
    'no_project_scope': 'Нет доступной области проекта',
}
SKIPPED = {'SKIPPED_LEGACY_API', 'SKIPPED_DUPLICATE_ENDPOINT', 'DELEGATED_TO_PROJECT_ADAPTER'}


def outcome(row):
    status = row.get('status', 'NOT_CHECKED')
    if status == 'collected':
        return 'collected'
    if row.get('count', 0) > 0:
        return 'partial'
    return {
        'HTTP_401': 'authentication_failed', 'HTTP_403': 'access_denied',
        'HTTP_404': 'unavailable', 'UNSUPPORTED_SERVICE': 'unsupported',
        'PRODUCT_ADAPTER_NOT_IMPLEMENTED': 'unsupported',
        'NOT_IN_CATALOG': 'not_in_catalog', 'NOT_CHECKED': 'not_checked',
        'PARENT_COLLECTION_UNAVAILABLE': 'not_checked',
        'UNTRUSTED_OR_INVALID_ENDPOINT': 'blocked_endpoint',
    }.get(status, 'error')


def combine(states):
    unique = set(states)
    if not unique:
        return 'not_checked'
    return next(iter(unique)) if len(unique) == 1 else 'partial'


def scope_result(product, project, region, rows):
    relevant = [r for r in rows if r.get('status') not in SKIPPED]
    sections = []
    for row in relevant:
        sections.append({'kind': row.get('kind', ''), 'code': row.get('status', 'NOT_CHECKED'),
                         'state': outcome(row), 'observations': row.get('count', 0)})
    # Missing collections must not become a green product because one request worked.
    # A scope-wide failure already explains why its collections were not attempted.
    scope_failure = any(r.get('kind') in ('catalog', 'project_auth') and
                        r.get('status') != 'collected' for r in relevant)
    if not scope_failure:
        seen = {r.get('kind') for r in relevant}
        sections.extend({'kind': kind, 'code': 'NOT_CHECKED', 'state': 'not_checked',
                         'observations': 0} for kind in product.sections if kind not in seen)
    # Dependent sections were not requested; keep their diagnostics without
    # counting the parent's failure a second time.
    state = combine(x['state'] for x in sections if x['code'] != 'PARENT_COLLECTION_UNAVAILABLE')
    roots = [r for r in relevant if r.get('kind') in product.roots]
    if state == 'collected' and roots and not any(r.get('count', 0) for r in roots):
        state = 'empty'
    counts = Counter()
    for row in roots:
        counts[row['kind']] += row.get('count', 0)
    return {'project': project, 'region': region, 'state': state,
            'observations_by_collection': dict(sorted(counts.items())), 'sections': sections}


def account_overview(document):
    """Expose only coverage metadata; never copy API responses, credentials or endpoints."""
    coverage = document.get('coverage', [])
    projects = sorted({p['id'] for p in document.get('projects', []) if p.get('id')})
    project_auth = {r.get('project'): r for r in coverage
                    if r.get('service') == 'identity' and r.get('kind') == 'project_auth'}
    products = []
    for product in PRODUCTS:
        supported = bool(product.sections)
        enabled = document.get('profile', 'all') == 'all' or product.server_profile
        rows = [r for r in coverage if r.get('service') in product.services]
        scopes = []
        if not enabled:
            state = 'excluded'
        elif not supported:
            state = 'unsupported'
        elif product.scope == 'account':
            # Project catalogs repeat IAM/Resell endpoints. Their unimplemented
            # catalog adapters are not failures of the explicit account requests.
            account_rows = [r for r in rows if not r.get('project') and r.get('kind') != 'catalog']
            scopes = [scope_result(product, '', '', account_rows)]
            state = scopes[0]['state']
        else:
            scope_projects = sorted(set(projects) | {r.get('project') for r in rows if r.get('project')})
            for project in scope_projects:
                project_rows = [r for r in rows if r.get('project') == project]
                if project in project_auth:
                    project_rows.append(project_auth[project])
                regions = (sorted({r.get('region', '') for r in project_rows
                                   if r.get('status') not in SKIPPED}) or ['']) if product.scope == 'catalog' else ['']
                for region in regions:
                    scopes.append(scope_result(product, project, region,
                                  [r for r in project_rows if product.scope == 'project' or
                                   r.get('region', '') == region]))
            # Empty and populated successfully read scopes can coexist without a failure.
            states = [s['state'] for s in scopes]
            state = ('collected' if states and set(states) <= {'collected', 'empty'} and
                     'collected' in states else combine(states)) if scopes else 'no_project_scope'
        counts = Counter()
        for scope in scopes:
            counts.update(scope['observations_by_collection'])
        products.append({'product': product.key, 'title': product.title,
            'adapter': 'partial' if supported else 'not_implemented',
            'enabled': enabled, 'state': state, 'state_label': LABELS[state],
            'observations_by_collection': dict(sorted(counts.items())),
            'scopes': scopes, 'limitations': product.gaps or 'Адаптер ещё не реализован.',
            'netbox_target': product.target, 'auto_apply': False})
    known = {s for p in PRODUCTS for s in p.services} | {'identity'}
    unknown = sorted({r.get('service') for r in coverage
                      if r.get('service') and r['service'] not in known})
    return {'schema': 'selectel-account-overview-v1', 'capability_version': 3,
        'account': document.get('account'), 'account_verified': document.get('account_verified', False),
        'profile': document.get('profile', 'all'), 'observed_at': document.get('finished_at'),
        'projects_visible': len(projects), 'account_completeness': 'not_proven',
        'writes_performed': False, 'products': products,
        'states': dict(sorted(Counter(p['state'] for p in products).items())),
        'unmapped_catalog_services': unknown,
        'limitations': [
            'Счётчики — наблюдения отдельных списков, а не число уникальных ресурсов аккаунта.',
            'Пустой ответ, отсутствие каталога и отсутствие сборщика не доказывают отсутствие услуги.',
            'Наличие сервиса в каталоге не доказывает наличие купленных ресурсов.',
            'Сбор не создаёт объекты NetBox и не изменяет принятые привязки.',
        ]}
