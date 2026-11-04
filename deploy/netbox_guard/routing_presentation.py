"""Readable routing components and coverage; zero requires successful enumeration."""
SECTIONS = {'routers': 'Роутеры', 'networks': 'Сети', 'subnets': 'Подсети',
            'static_routes': 'Статические маршруты', 'zones': 'Зоны и сервисы'}
KINDS = {'global_router': 'routers', 'routing_network': 'networks',
         'routing_subnet': 'subnets', 'routing_route': 'static_routes'}
FIELDS = (('id', 'UUID'), ('status', 'Состояние'), ('enabled', 'Включён'),
          ('router_id', 'UUID роутера'), ('network_id', 'UUID сети'), ('subnet_id', 'UUID подсети'),
          ('zone_id', 'UUID зоны'), ('zone_name', 'Зона'), ('zone_service', 'Сервис'),
          ('cidr', 'Префикс'), ('gateway', 'Шлюз'), ('next_hop', 'Следующий узел'),
          ('vlan', 'VLAN'), ('inner_vlan', 'Внутренний VLAN'), ('vdc_name', 'VDC'),
          ('os_network_id', 'UUID облачной сети'), ('os_subnet_id', 'UUID облачной подсети'),
          ('service_addresses', 'Служебные адреса'), ('vpn_id', 'VPN ID'), ('tags', 'Метки'))


def fields(row):
    section = row['sections'].get(KINDS[row['kind']], {})
    data = section.get('data') or {}
    result = [(label, ', '.join(map(str, data[key])) if isinstance(data[key], list) else data[key])
              for key, label in FIELDS if data.get(key) is not None]
    result.append(('Получение данных', section.get('latest_status', section.get('status', 'NOT_REPORTED'))))
    if section.get('retained') or row.get('present_in_latest') is False:
        result.append(('Актуальность', 'Сохранено ранее; текущий сбор не подтвердил эти сведения'))
    return result


def coverage(snapshot):
    values = [c for c in snapshot.get('coverage', []) if c.get('service') == 'global-router']
    return [dict(label=label, status=', '.join(sorted({c['status'] for c in values if c.get('kind') == kind})) or 'NOT_REPORTED')
            for kind, label in SECTIONS.items()]


def components(selected, rows, relations):
    keys = {selected['key']}
    # Router -> network -> subnet; route references are direct children.
    for _ in range(2):
        keys.update(e['target'] for e in relations if e['source'] in keys and e['relation'] == 'contains')
    return [r for r in rows if r['key'] in keys and r['key'] != selected['key']]
