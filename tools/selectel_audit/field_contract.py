"""Review contract only; neither bindings nor write authority are granted here."""
import json


FIELD_RULES = (
    ('provider_identity', 'Selectel', 'Проверенная связь с ресурсом; sync_identities гипервизора сохраняются'),
    ('provider_status', 'Selectel', 'Состояние услуги отдельно от технического статуса Device'),
    ('provider_location', 'Selectel', 'Location/AZ из API; Site только через подтверждённую карту размещения'),
    ('site_and_cluster_scope', 'Принятая карта размещения', 'Изменение Device, Cluster и настроек источника одним согласованным планом'),
    ('device_name_management_ip', 'ESXi/Proxmox или оператор', 'WAN гостевой VM не становится management IP Device'),
    ('hypervisor_and_guests', 'ESXi/Proxmox', 'Версия, фактические ресурсы и гостевые VM гипервизора'),
    ('cloud_vm_resources', 'Selectel для подтверждённой cloud VM', 'Nova/flavor/Cinder; Device физического сервера не придумывается'),
    ('ip_assignment', 'Подтверждённая карта сетей', 'Account/project/region/network → область NetBox; маска только из subnet'),
    ('manual_fields', 'Оператор', 'Передача отдельных полей источнику требует отдельного решения'),
)

# A schema manifest for the future installer, not a new field per API property.
# The authoritative bindings/claims belong in application/Guard storage, never
# in an editable custom field. These are display projections only.
CUSTOM_FIELDS = (
    {'name': 'selectel_refs', 'type': 'json',
     'object_types': ['dcim.device', 'virtualization.virtualmachine'],
     'group_name': 'Selectel', 'required': False, 'unique': False,
     'ui_visible': 'hidden', 'ui_editable': 'no'},
    {'name': 'selectel_summary', 'type': 'text',
     'object_types': ['dcim.device', 'virtualization.virtualmachine'],
     'group_name': 'Selectel', 'required': False, 'unique': False,
     'ui_visible': 'if-set', 'ui_editable': 'no'},
)


def resource_key(row):
    """Dedicated identity survives project/location moves; cloud scope is explicit."""
    account, native = row.get('account'), row.get('provider_id')
    if not all(isinstance(x, str) and x.strip() for x in (account, native)):
        raise ValueError('Missing resource identity')
    kind = row['kind']
    if kind in ('dedicated_resource', 'other_dedicated_resource'):
        parts = ['selectel', account, 'dedicated', native]
    elif kind == 'cloud_vm':
        project, region = row.get('project'), row.get('region')
        if not all(isinstance(x, str) and x.strip() for x in (project, region)):
            raise ValueError('Cloud scope is incomplete')
        parts = ['selectel', account, project, region, 'cloud_vm', native]
    else:
        raise ValueError('Unsupported resource kind')
    return json.dumps(parts, ensure_ascii=False, separators=(',', ':'))


def schema_plan(existing):
    """Idempotent creation plan; incompatible definitions are never overwritten.

    Input must be a complete schema export. Callers must validate coverage first.
    This function neither calls NetBox nor interprets the absence of an export.
    """
    if not isinstance(existing, list):
        raise ValueError('A complete custom field export is required')
    names = [field['name'] for field in existing]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate custom field name')
    by_name = {f['name']: f for f in existing}
    result = []
    for definition in CUSTOM_FIELDS:
        actual = by_name.get(definition['name'])
        if actual is None:
            action, differences = 'create', []
        else:
            differences = [key for key, value in definition.items()
                           if (set(actual.get(key, [])) != set(value) if key == 'object_types'
                               else actual.get(key) != value)]
            action = 'conflict' if differences else 'unchanged'
        result.append({'name': definition['name'], 'action': action,
                       'definition': json.loads(json.dumps(definition)),
                       'differences': differences})
    return result


def ownership_review(row):
    """Show hierarchy without promoting a candidate to a confirmed owner."""
    kind = row['kind']
    if kind == 'dedicated_resource':
        hierarchy = ['Selectel / аккаунт', 'Выделенный сервер → существующий или новый Device',
                     'Гипервизор / кластер', 'Гостевые VM']
        prerequisite = 'Подтвердить связь с Device и карту размещения; порядок подключения источников не меняет Device ID'
    elif kind == 'cloud_vm':
        hierarchy = ['Selectel / аккаунт', 'Проект / регион', 'Облачная VM']
        prerequisite = 'Подтвердить VM и сетевую область; наличие гипервизора внутри VM не доказано'
    else:
        hierarchy = ['Selectel / аккаунт', 'Услуга провайдера']
        prerequisite = 'Не создавать фиктивный Device или кластер для услуги'
    try:
        key = resource_key(row)
    except ValueError:
        key = None
        prerequisite = 'Не хватает стабильной идентичности или области ресурса'
    return {'provider_key': key, 'hierarchy': hierarchy, 'prerequisite': prerequisite,
            'binding_status': 'not_confirmed', 'write_authorized': False,
            'field_rules': [dict(field=f, authority=a, rule=r) for f, a, r in FIELD_RULES]}
