"""Derived evidence states, shared by native panels and the read-only Map API.

Input rows have already been permission-filtered. Never infer a physical edge
from allocation, port name, enabled state, a configured path or a neighbor alone.
"""

PATH_LABELS = {
    'configured': 'Путь по конфигурации найден',
    'incomplete': 'Путь по конфигурации неполный',
    'ambiguous_names': 'Неоднозначные имена интерфейсов',
    'snapshot_missing_or_ambiguous': 'Снимок сети отсутствует или неоднозначен',
    'unsupported_snapshot': 'Версия снимка сети не поддерживается',
}


def evidence_status(row):
    path = row.get('host_path') or {}
    path_code = path.get('status', 'not_established')
    assignment = bool(row.get('assignment'))
    return {
        'provider': {'code': 'recorded', 'label': 'Связь сохранена в Guard'},
        'assignment': {
            'code': 'recorded' if assignment else 'not_established',
            'label': 'Назначение записано в NetBox' if assignment else 'Назначение не установлено или недоступно',
        },
        'host_path': {
            'code': path_code,
            'label': PATH_LABELS.get(path_code, 'Недостаточно данных для пути на этом хосте'),
        },
        'physical': {
            'code': 'unconfirmed', 'confirmed': False,
            'reason': 'NO_VERIFIED_NIC_PORT_IDENTITY',
            'label': 'NIC ↔ порт Selectel: не подтверждено',
            'explanation': 'Нет проверенного соответствия адаптера хоста UUID порта провайдера. '
                           'Совпадения IP, VLAN и имени порта недостаточно.',
        },
    }


def summary(rows):
    return {
        'provider_links': len(rows),
        'interface_assignments': sum(bool(r.get('assignment')) for r in rows),
        'configured_paths': sum((r.get('host_path') or {}).get('status') == 'configured' for r in rows),
        'unconfirmed_port_attachments': sum(r['relation'] == 'attachment' for r in rows),
        'confirmed_physical_links': 0,
    }
