"""Read-only tables for the allowlisted ESXi network snapshot."""


def cell(value):
    if value is None or value == '':
        return '—'
    if isinstance(value, bool):
        return 'Да' if value else 'Нет'
    if isinstance(value, list):
        return ', '.join(cell(item) for item in value) or '—'
    if isinstance(value, dict):
        return 'Неизвестный формат'
    return str(value)


def network_panel(value):
    if value is None:
        return None
    if not isinstance(value, dict) or value.get('version') != 1:
        return {'message': 'Формат сетевого снимка не поддерживается.', 'tables': [], 'notes': []}
    if value.get('available') is not True:
        return {'message': 'ESXi не предоставил сетевую информацию при последнем сборе.',
                'tables': [], 'notes': []}
    tables = []
    def add(key, title, columns, project):
        entries = value.get(key)
        entries = entries if isinstance(entries, list) else []
        tables.append({'title': title, 'columns': columns,
                       'rows': [[cell(c) for c in project(r)] for r in entries if isinstance(r, dict)]})
    add('physical_nics', 'Физические адаптеры',
        ['Адаптер', 'MAC', 'Линк', 'Скорость, Мбит/с', 'Полный дуплекс', 'Драйвер', 'Стандартные vSwitch'],
        lambda r: [r.get('name'), r.get('mac'),
                   'Up' if r.get('link_up') is True else 'Down' if r.get('link_up') is False else None,
                   r.get('speed_mbps'), r.get('full_duplex'), r.get('driver'), r.get('switches')])
    add('switches', 'Стандартные виртуальные коммутаторы',
        ['vSwitch', 'MTU', 'Физические адаптеры', 'Сети / port groups'],
        lambda r: [r.get('name'), r.get('mtu'), r.get('uplinks'), r.get('port_groups')])
    add('port_groups', 'Сети / port groups', ['Сеть', 'vSwitch', 'VLAN ID'],
        lambda r: [r.get('name'), r.get('switch'), r.get('vlan_id')])
    def kernel(r):
        connection = r.get('port_group')
        if r.get('distributed_switch_uuid'):
            connection = 'DVS: ' + cell(r.get('distributed_switch_uuid'))
            connection += '; port group: ' + cell(r.get('distributed_port_group_key'))
            connection += '; port: ' + cell(r.get('distributed_port_key'))
        return [r.get('name'), connection, r.get('mac'), r.get('ipv4'),
                r.get('subnet_mask'), r.get('ipv6'), r.get('mtu'), r.get('dhcp')]
    add('vmkernel', 'VMkernel-интерфейсы',
        ['Интерфейс', 'Подключение', 'MAC', 'IPv4', 'Маска', 'IPv6', 'MTU', 'DHCP'], kernel)
    notes = []
    for key, label in [('distributed_switch_count', 'Распределённые коммутаторы'),
                       ('opaque_switch_count', 'Opaque-коммутаторы')]:
        count = value.get(key, 0)
        if isinstance(count, int) and count > 0:
            notes.append(f'{label}: {count}. Их полная топология в этом блоке не представлена.')
    return {'message': 'Снимок последнего применённого сбора ESXi. '
                       'Эти сведения не создают интерфейсы, кабели или назначения IP в NetBox.',
            'tables': tables, 'notes': notes}
