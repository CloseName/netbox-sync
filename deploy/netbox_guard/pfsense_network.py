"""Snapshot policy and read-only presentation, independent of Django."""
from datetime import datetime, timezone
from copy import deepcopy

FIELD = 'pfsense_network'
SCHEMA = 'netbox-sync.pfsense.snapshot.v1'


def snapshot_record(preview, previous=None, now=None):
    now = now or datetime.now(timezone.utc)
    if preview.get('schema') != 'netbox-sync.pfsense.preview.v1' or not preview.get('all_interfaces_matched') or preview.get('issues'):
        raise ValueError('All configured interfaces must match before saving')
    value = {key: deepcopy(preview[key]) for key in
             ('vm_id', 'version', 'collected_at', 'interfaces', 'vlans', 'unmapped_runtime_devices', 'unmatched_vm_interfaces')}
    value['schema'] = SCHEMA
    stamp = datetime.fromisoformat(value['collected_at'].replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Snapshot time must include timezone')
    if previous is not None:
        if not isinstance(previous, dict) or previous.get('schema') != SCHEMA or previous.get('vm_id') != value['vm_id']:
            raise ValueError('Existing snapshot has incompatible format or VM identity')
        if previous == value:
            return previous
        old_stamp = datetime.fromisoformat(previous['collected_at'].replace('Z', '+00:00'))
        if stamp <= old_stamp:
            raise ValueError('Snapshot is older than or conflicts with stored data')
    if not -120 <= (now - stamp).total_seconds() <= 900:
        raise ValueError('Collect a fresh snapshot: maximum age is 15 minutes')
    return value


def panel(value):
    if value is None:
        return None
    invalid = dict(message='Формат снимка pfSense не поддерживается.', tables=[], notes=[])
    if not isinstance(value, dict) or value.get('schema') != SCHEMA:
        return invalid
    def cell(item):
        return '—' if item is None or item == '' else str(item)[:2048]
    try:
        rows = []
        for row in value['interfaces'][:512]:
            config, live, match = row['configuration'], row['runtime'], row['match']
            addresses = live['addresses']
            rows.append([cell(config['name']), cell(config['device']), cell(match['name']),
                         cell(live['mac']), cell(live['mtu']),
                         'Включён' if config['enabled'] else 'Выключен', cell(live['status']),
                         ', '.join(a['address'] for a in addresses if ':' not in a['address']) or '—',
                         ', '.join(a['address'] for a in addresses if ':' in a['address']) or '—',
                         cell(config['ipv6_config'])])
        vlans = [[cell(v[key]) for key in ('device', 'parent', 'tag', 'description')] for v in value['vlans'][:512]]
        return dict(message='Снимок от {}. pfSense {}. Адреса показаны как наблюдения; назначения IP в NetBox не изменены.'.format(
            cell(value['collected_at']), cell(value['version'])),
            tables=[dict(title='Интерфейсы', columns=['Назначение', 'pfSense', 'NetBox (на момент сбора)', 'MAC', 'MTU',
                'Настройка', 'Линк', 'IPv4', 'IPv6', 'Режим IPv6'], rows=rows),
                dict(title='VLAN в pfSense', columns=['Устройство', 'Родитель', 'VLAN ID', 'Описание'], rows=vlans)],
            notes=['Обновляется вручную при импорте снимка. Link-local IPv6 показаны только для справки.'])
    except (KeyError, TypeError, AttributeError):
        return invalid
