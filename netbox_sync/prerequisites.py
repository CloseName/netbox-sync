"""Versioned fixed NetBox prerequisite contract. No operator-supplied definitions."""
import hashlib
import json
import re

VERSION = 1
FIELDS = {
    'sync_identities': ('json', ('dcim.device','dcim.interface','virtualization.virtualmachine','virtualization.vminterface')),
    'sync_original_names': ('json', ('dcim.device','dcim.interface','virtualization.virtualmachine','virtualization.vminterface')),
    'hypervisor_version': ('text', ('dcim.device',)),
    'cpu_model': ('text', ('dcim.device',)), 'cpu_vendor': ('text', ('dcim.device',)),
    'cpu_sockets': ('integer', ('dcim.device',)), 'cpu_cores': ('integer', ('dcim.device',)),
    'cpu_threads': ('integer', ('dcim.device',)), 'memory_mb': ('integer', ('dcim.device',)),
    'physical_disks': ('json', ('dcim.device',)),
    'guest_kind': ('text', ('virtualization.virtualmachine',)),
    'guest_architecture': ('text', ('virtualization.virtualmachine',)),
    'guest_os_type': ('text', ('virtualization.virtualmachine',)),
    'swap_mb': ('integer', ('virtualization.virtualmachine',)),
    'source_bridge': ('text', ('virtualization.vminterface',)),
    'source_vlan_id': ('integer', ('virtualization.vminterface',)),
}

LABELS = {
    'sync_identities': ('Source identities', 'Идентификаторы источников'),
    'sync_original_names': ('Original source names', 'Исходные имена'),
    'hypervisor_version': ('Hypervisor version', 'Версия гипервизора'),
    'cpu_model': ('Host CPU model', 'Модель CPU хоста'),
    'cpu_vendor': ('Host CPU vendor', 'Производитель CPU хоста'),
    'cpu_sockets': ('Host CPU sockets', 'Сокеты CPU хоста'),
    'cpu_cores': ('Host CPU cores', 'Ядра CPU хоста'),
    'cpu_threads': ('Host CPU threads', 'Потоки CPU хоста'),
    'memory_mb': ('Host memory (MiB)', 'Память хоста (MiB)'),
    'physical_disks': ('Host physical disks', 'Физические диски хоста'),
    'guest_kind': ('Guest kind', 'Тип гостевой среды'),
    'guest_architecture': ('Guest architecture', 'Архитектура гостевой среды'),
    'guest_os_type': ('Provider guest OS hint', 'Тип ОС по данным провайдера'),
    'swap_mb': ('Container swap (MiB)', 'Swap контейнера (MiB)'),
    'source_bridge': ('Source bridge', 'Мост источника'),
    'source_vlan_id': ('Source VLAN ID', 'VLAN ID источника'),
}
PURPOSES = {
    'sync_identities': ('Stable, source-scoped ownership; never name adoption.', 'Стабильная принадлежность источнику; без присвоения по имени.'),
    'sync_original_names': ('Original names retained independently of display names.', 'Исходные имена отдельно от отображаемых.'),
    'hypervisor_version': ('Observed host hypervisor version.', 'Обнаруженная версия гипервизора хоста.'),
    'cpu_model': ('Observed physical host hardware.', 'Обнаруженное оборудование физического хоста.'),
    'cpu_vendor': ('Observed physical host hardware.', 'Обнаруженное оборудование физического хоста.'),
    'cpu_sockets': ('Physical host topology, not VM vCPUs.', 'Топология физического хоста, не vCPU VM.'),
    'cpu_cores': ('Physical host topology, not VM vCPUs.', 'Топология физического хоста, не vCPU VM.'),
    'cpu_threads': ('Physical host topology, not VM vCPUs.', 'Топология физического хоста, не vCPU VM.'),
    'memory_mb': ('Physical host memory; VM memory uses the standard field.', 'Память физического хоста; для VM используется стандартное поле.'),
    'physical_disks': ('Observed disk inventory, not virtual disk allocation.', 'Обнаруженные диски, не объём виртуальных дисков.'),
    'guest_kind': ('Distinguishes LXC from virtual machines.', 'Отличает LXC от виртуальных машин.'),
    'guest_architecture': ('Provider-reported LXC architecture.', 'Архитектура LXC по данным провайдера.'),
    'guest_os_type': ('Raw LXC OS hint; does not assign an operator Platform.', 'Исходный тип ОС LXC; не назначает Platform оператора.'),
    'swap_mb': ('LXC swap allocation, separate from RAM.', 'Выделенный swap LXC отдельно от RAM.'),
    'source_bridge': ('Provider bridge name, without creating infrastructure.', 'Имя моста провайдера без создания инфраструктуры.'),
    'source_vlan_id': ('Observed tag; does not create or assign a VLAN.', 'Обнаруженный тег; не создаёт и не назначает VLAN.'),
}


def definition(name):
    kind, models = FIELDS[name]
    return {'name': name, 'type': kind, 'object_types': list(models),
            'label': LABELS[name][0], 'description': PURPOSES[name][0],
            'group_name': 'NetBox Sync', 'required': False, 'unique': False}


def choice(value):
    return value.get('value') if isinstance(value, dict) else value


def mismatch_details(differences, row, kind, models, count):
    """Bounded operator evidence, never raw validation regex/schema or response bodies."""
    row = row or {}
    known_types = {'text','longtext','integer','decimal','boolean','date','datetime','url','json','select','multiselect','object','multiobject'}
    actual_type = choice(row.get('type'))
    actual_models = row.get('object_types')
    valid_models = (isinstance(actual_models,list) and len(actual_models)<=32 and
                    all(isinstance(m,str) and len(m)<=96 and re.fullmatch(r'[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*',m) for m in actual_models))
    model_text = (', '.join(sorted(actual_models)) or 'none') if valid_models else 'unrecognized'
    pairs = {
        'type': (kind, actual_type if isinstance(actual_type,str) and actual_type in known_types else 'unrecognized'),
        'models': (', '.join(models), model_text),
        'duplicate': ('1', str(count)),
        'required': ('false', 'true' if row.get('required') is True else 'unrecognized'),
        'unique': ('false', 'true' if row.get('unique') is True else 'unrecognized'),
        'lifecycle': ('active', 'deleting' if choice(row.get('status')) == 'deleting' else 'unrecognized'),
    }
    for key in ('validation_minimum','validation_maximum'):
        value = row.get(key)
        pairs[key] = ('none', str(value)[:40] if type(value) in (int,float) else 'unrecognized')
    for key in ('validation_regex','validation_schema'):pairs[key] = ('none','configured')
    return [{'property': key, 'expected': pairs[key][0], 'actual': pairs[key][1]} for key in differences]


def reconcile(rows):
    result = []
    for name, (kind, models) in FIELDS.items():
        matches = [r for r in rows if isinstance(r, dict) and r.get('name') == name]
        row = matches[0] if len(matches) == 1 else None
        differences = []
        if len(matches) > 1: differences.append('duplicate')
        if row is not None:
            if choice(row.get('type')) != kind: differences.append('type')
            if not isinstance(row.get('object_types'), list) or not set(models).issubset(set(row['object_types'])): differences.append('models')
            for key in ('required', 'unique'):
                if row.get(key) is not None and row.get(key) is not False:differences.append(key)
            for key in ('validation_minimum', 'validation_maximum'):
                if row.get(key) is not None:differences.append(key)
            if row.get('validation_regex') not in (None, ''):differences.append('validation_regex')
            if row.get('validation_schema') not in (None, {}):differences.append('validation_schema')
        status = 'missing' if not matches else 'conflict' if differences else 'ready'
        if row is not None and not differences:
            lifecycle = choice(row.get('status', 'active'))
            if lifecycle == 'provisioning':status = 'provisioning'
            elif lifecycle != 'active':status = 'conflict';differences.append('lifecycle')
        result.append({'name': name, 'type': kind, 'models': list(models), 'status': status,
                       'differences': differences, 'mismatch_details': mismatch_details(differences, row, kind, models, len(matches)), 'id': row['id'] if row and type(row.get('id')) is int and row['id'] > 0 else None,
                       'label': {'en': LABELS[name][0], 'ru': LABELS[name][1]},
                       'purpose': {'en': PURPOSES[name][0], 'ru': PURPOSES[name][1]}})
    return result


def digest(revision, url, fields):
    return hashlib.sha256(json.dumps({'version': VERSION, 'revision': revision, 'url': url,
        'fields': fields, 'create': [definition(f['name']) for f in fields if f['status']=='missing']},
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
