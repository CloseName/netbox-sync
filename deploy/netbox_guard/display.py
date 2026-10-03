"""Pure presentation of the four managed JSON fields. Never alters stored data."""
FIELD_LABELS = {
    'sync_original_names': 'Исходные имена',
    'sync_network_observations': 'Сетевые наблюдения',
    'physical_disks': 'Физические диски',
    'sync_identities': 'Идентификаторы синхронизации',
}
LABELS = {
    'external_id': 'ID объекта', 'instance': 'Источник', 'kind': 'Тип объекта',
    'schema': 'Версия идентификатора', 'type': 'Тип', 'path': 'Устройство',
    'model': 'Модель', 'serial': 'Серийный номер', 'size_bytes': 'Размер',
    'health': 'Состояние', 'status': 'Статус', 'addresses': 'Спорные IP-адреса',
    'bridge': 'Сеть источника', 'vlan_id': 'VLAN', 'vrf_id': 'ID VRF',
    'mac_addresses': 'Спорные MAC-адреса', 'version': 'Версия формата',
    'ipam_complete': 'Нет исключённых IP-назначений',
    'mac_assignment_complete': 'Нет исключённых MAC-назначений',
    'scope_conflicts': 'Конфликты областей IP', 'mac_conflicts': 'Конфликты MAC',
}
VALUES = {
    'NO_DISPUTED_ADDRESSES': 'Спорных назначений не обнаружено',
    'REVIEW_REQUIRED': 'Требуется проверка; наблюдения не назначены в IPAM',
    'esxi': 'VMware ESXi', 'proxmox': 'Proxmox', 'vm': 'Виртуальная машина',
    'vm-nic': 'Интерфейс VM', 'lxc-nic': 'Интерфейс контейнера',
}


def scalar(value, key=''):
    if value is None or value == '':
        return '—'
    if isinstance(value, bool):
        return 'Да' if value else 'Нет'
    if key == 'size_bytes' and isinstance(value, (int, float)):
        return f'{value / 1024**3:,.2f} GiB ({value:,} байт)'
    text = str(value)
    return VALUES.get(text, text) if key in ('status', 'type', 'kind') else text


def readable_rows(value, prefix='', depth=0):
    # Bounded recursion; unknown keys are retained as readable rows, not discarded.
    if depth > 12:
        return [(prefix, 'Вложенные данные доступны через API')]
    if isinstance(value, dict):
        rows = []
        for key, item in value.items():
            label = LABELS.get(key, str(key).replace('_', ' '))
            path = f'{prefix} / {label}' if prefix else label
            if isinstance(item, (dict, list)):
                rows.extend(readable_rows(item, path, depth + 1))
            else:
                rows.append((path, scalar(item, key)))
        return rows or [(prefix, 'Нет данных')]
    if isinstance(value, list):
        if all(not isinstance(item, (dict, list)) for item in value):
            return [(prefix, '; '.join(scalar(item) for item in value) or 'Нет')]
        rows = []
        for index, item in enumerate(value, 1):
            rows.extend(readable_rows(item, f'{prefix} №{index}'.strip(), depth + 1))
        return rows
    return [(prefix, scalar(value))]


def display_sections(fields):
    if not isinstance(fields, dict):
        return []
    sections = []
    for key, title in FIELD_LABELS.items():
        value = fields.get(key)
        if value is None or value == {} or value == []:
            continue
        if key == 'sync_original_names' and isinstance(value, dict):
            rows = [('Имя в источнике' if len(value) == 1 else source, scalar(name))
                    for source, name in value.items()]
        elif key == 'sync_network_observations' and isinstance(value, dict):
            rows = []
            for source, observation in value.items():
                prefix = '' if len(value) == 1 else source
                if isinstance(observation, dict):
                    # Empty lists and schema versions add no operator information.
                    observation = {k: v for k, v in observation.items()
                                   if k != 'version' and v is not None and v != []}
                rows.extend(readable_rows(observation, prefix))
        else:
            rows = readable_rows(value)
        sections.append({'title': title, 'rows': rows,
                         'technical': key == 'sync_identities'})
    return sections
