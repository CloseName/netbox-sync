"""Read-only hardware summary: host facts win; provider physical disks stay distinct."""
import re
from decimal import Decimal, InvalidOperation
from .resource_presentation import obj, components

HOST_FIELDS = (('cpu_model', 'Процессор'), ('cpu_sockets', 'Процессоров'),
               ('cpu_cores', 'Ядер'), ('cpu_threads', 'Потоков'),
               ('memory_mb', 'Память по данным хоста'), ('hypervisor_version', 'Гипервизор'))


def memory_gib(value):
    try:
        amount = Decimal(str(value))
        if amount.is_finite() and amount >= 0:
            return format(amount / 1024, '.2f').rstrip('0').rstrip('.').replace('.', ',') + ' ГиБ'
    except InvalidOperation:
        pass
    return str(value)


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
    hardware = dict(obj(snapshot, 'hardware'))
    config = hardware.get('config_name') or obj(snapshot, 'details').get('config_name')
    if config and not any(hardware.get(k) for k in ('cpu', 'ram', 'disk')):
        hardware.update(parse_configuration(str(config)))
    rows = [(label, memory_gib(fields[key]) if key == 'memory_mb' else str(fields[key]))
            for key, label in HOST_FIELDS if fields.get(key) not in (None, '')]
    if not fields.get('cpu_model') and components(hardware.get('cpu')):
        rows.insert(0, ('Процессор', components(hardware['cpu'])))
    if components(hardware.get('ram')):
        rows.append(('Установленная память', components(hardware['ram'])))
    if not fields.get('cpu_model') and not hardware.get('cpu') and hardware.get('cpu_summary'):
        rows.insert(0, ('Процессор', hardware['cpu_summary']))
    if hardware.get('memory_summary'):
        rows.append(('Установленная память', hardware['memory_summary']))
    disks = disk_rows(hardware.get('disk'))
    fallback = hardware.get('config_name') or obj(snapshot, 'details').get('config_name')
    if fallback and not rows and not disks:
        rows.append(('Конфигурация Selectel', fallback))
    if not rows and not disks:
        return None
    cpu_labels = {label for key, label in HOST_FIELDS if key.startswith('cpu_')}
    memory_labels = {'Память по данным хоста', 'Установленная память'}
    return dict(fields=rows, cpu=[r for r in rows if r[0] in cpu_labels],
                memory=[r for r in rows if r[0] in memory_labels],
                other=[r for r in rows if r[0] not in cpu_labels | memory_labels],
                disks=disks, disk_count=sum(d['count'] for d in disks),
                disk_source='Selectel' if disks else '')


def parse_configuration(text):
    """Parse only explicit component quantities; never infer disks from total capacity."""
    result = {}
    parts = [p.strip() for p in re.split(r'[,;]', text) if p.strip()]
    disks, ram = [], []
    for part in parts:
        if re.search(r'(?i)\b(SSD|HDD|NVME)\b', part):
            match = re.match(r'^(\d+)\s*[x×]\s*(.+)$', part)
            if match:
                disks.append(dict(count=int(match[1]), name=match[2]))
        elif re.search(r'(?i)\bDDR[2345]\b', part):
            match = re.match(r'^(\d+)\s*[x×]\s*(.+)$', part)
            # A total capacity without module count remains a total, not one DIMM.
            if match:
                ram.append(dict(count=int(match[1]), name=match[2]))
            else:
                result['memory_summary'] = part
    if parts and re.match(r'(?i)^(Intel|AMD)\b', parts[0]):
        result['cpu_summary'] = parts[0]
    if disks: result['disk'] = disks
    if ram: result['ram'] = ram
    return result
