"""Read-only hardware summary: host facts win; provider physical disks stay distinct."""
import re
from .resource_presentation import obj, components

HOST_FIELDS = (('cpu_model', 'Процессор'), ('cpu_sockets', 'Процессоров'),
               ('cpu_cores', 'Ядер'), ('cpu_threads', 'Потоков'),
               ('memory_mb', 'Память по данным хоста'), ('hypervisor_version', 'Гипервизор'))


def disk_rows(parts):
    grouped = {}
    for part in parts if isinstance(parts, list) else []:
        if not isinstance(part, dict):
            continue
        name = str(part.get('name') or part.get('type') or '')
        sizes = re.findall(r'(?i)(\d+(?:[.,]\d+)?)\s*(TB|GB|ТБ|ГБ)\b', name)
        capacity = ' '.join(sizes[0]).upper() if len(sizes) == 1 else 'Не указан'
        kind = 'SSD' if re.search(r'(?i)\b(SSD|NVME)\b', name) else 'HDD' if re.search(r'(?i)\bHDD\b', name) else 'Неизвестно'
        count = part.get('count', 1)
        if type(count) is not int or count < 1:
            continue
        # Unknown capacities must not collapse unrelated hardware into one group.
        key = (capacity, kind, name if capacity == 'Не указан' or kind == 'Неизвестно' else '')
        grouped[key] = grouped.get(key, 0) + count
    return [dict(count=count, capacity=key[0], kind=key[1]) for key, count in grouped.items()]


def panel(fields):
    fields = fields or {}
    snapshot = fields.get('selectel_inventory') or {}
    hardware = obj(snapshot, 'hardware')
    rows = [(label, str(fields[key]) + (' МиБ' if key == 'memory_mb' else ''))
            for key, label in HOST_FIELDS if fields.get(key) not in (None, '')]
    if not fields.get('cpu_model') and components(hardware.get('cpu')):
        rows.insert(0, ('Процессор', components(hardware['cpu'])))
    if components(hardware.get('ram')):
        rows.append(('Установленная память', components(hardware['ram'])))
    disks = disk_rows(hardware.get('disk'))
    fallback = hardware.get('config_name') or obj(snapshot, 'details').get('config_name')
    if fallback and not hardware.get('cpu') and not hardware.get('ram') and not disks:
        rows.append(('Конфигурация Selectel', fallback))
    if not rows and not disks:
        return None
    return dict(fields=rows, disks=disks, disk_count=sum(d['count'] for d in disks),
                disk_source='Selectel' if disks else '')
