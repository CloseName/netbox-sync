"""Allowlisted human-readable provider cards; no raw snapshot in HTML."""
from .resource_tree import LABELS


def data(row, name):
    return row.get('sections', {}).get(name, {}).get('data')


def obj(row, name):
    value = data(row, name)
    return value if isinstance(value, dict) else {}


def items(row, name):
    value = data(row, name)
    return value if isinstance(value, list) else []


def size(value):
    if not isinstance(value, (int, float)):
        return 'Не указано'
    for suffix in ('Б', 'КиБ', 'МиБ', 'ГиБ', 'ТиБ'):
        if abs(value) < 1024 or suffix == 'ТиБ':
            return f'{value:,.1f} {suffix}'
        value /= 1024


def components(value):
    if not isinstance(value, list):
        return None
    return '; '.join(str(part.get('count') or 1) + ' × ' + str(part.get('name') or part.get('type') or 'Компонент')
                     for part in value if isinstance(part, dict))


def decorate(row, project_names):
    row['project_name'] = project_names.get(row['project']) or ('Без проекта' if not row['project'] else 'Проект · ' + row['project'][:8])
    row['kind_label'] = LABELS.get(row['kind'], row['kind'])
    placement = obj(row, 'placement')
    row['location'] = placement.get('name') or placement.get('OS-EXT-AZ:availability_zone') or row['region'] or 'Не указано'
    resource = obj(row, 'resource')
    row['state'] = resource.get('status') or resource.get('state') or ''
    fields = [('Проект', row['project_name']), ('Регион / площадка', row['location'])]
    from . import routing_presentation
    if row['kind'] in routing_presentation.KINDS:
        fields += routing_presentation.fields(row)
        row['routing'] = True
    elif row['kind'] == 'storage_container':
        bucket = obj(row, 'buckets')
        options = next(iter(items(row, 'container_options')), {})
        general = options.get('general') or {}
        quota = options.get('quota') or {}
        access = {'private': 'Приватный', 'public': 'Публичный'}.get(general.get('type'), 'Не указано')
        row.update(capacity=size(bucket.get('bytes')), object_count=bucket.get('count'), access=access)
        fields += [('Доступ', access), ('Занято', row['capacity']), ('Объектов', bucket.get('count')),
                   ('Последнее изменение', bucket.get('last_modified')),
                   ('Лимит объёма', size(quota['max_bytes_used']) if quota.get('max_bytes_used') is not None else 'Не указан'),
                   ('Лимит объектов', quota.get('max_object_count'))]
        row['domains'] = [domain for entry in items(row, 'container_domains') for domain in entry.get('domains', [])]
    elif row['kind'] in ('dns_zone', 'dns_rrset'):
        record = obj(row, 'rrsets')
        row.update(record_type=record.get('type'), ttl=record.get('ttl'),
                   records=record.get('records') or [])
        fields += [('Тип записи', record.get('type')), ('TTL, секунд', record.get('ttl'))] if record else [('Статус', obj(row, 'zones').get('status'))]
    elif row.get('server'):
        hardware = obj(row, 'hardware')
        operating = obj(row, 'operating_system')
        fields += [('Состояние в Selectel', row['state']),
            ('Конфигурация', hardware.get('config_name') or obj(row, 'details').get('config_name')),
            ('vCPU', hardware.get('vcpus')),
            ('Модули памяти' if isinstance(hardware.get('ram'), list) else 'Память, МиБ',
             components(hardware['ram']) if isinstance(hardware.get('ram'), list) else hardware.get('ram')),
            ('Физические диски' if isinstance(hardware.get('disk'), list) else 'Локальный диск, ГиБ',
             components(hardware['disk']) if isinstance(hardware.get('disk'), list) else hardware.get('disk')),
            ('Образ ОС', operating.get('name') or operating.get('os_template'))]
        row['addresses'] = sorted({str(v.get('ip')) for section in ('public_ips', 'private_ips')
                                  for v in items(row, section) if v.get('ip')})
        for values in obj(row, 'addresses').values():
            row['addresses'] += [v['addr'] for v in values if isinstance(v, dict) and v.get('addr')]
        row['volumes'] = items(row, 'volumes')
    fields += [('Последнее получение данных', row.get('last_seen'))]
    row['fields'] = [(label, value) for label, value in fields if value is not None and value != '']
    return row
