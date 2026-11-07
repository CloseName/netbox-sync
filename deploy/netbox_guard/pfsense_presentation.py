"""Presentation of current configuration objects and their same-appliance references."""
from collections import Counter, defaultdict
from urllib.parse import parse_qsl

from .models import FirewallReference
from .pfsense_catalog import fields
from .pfsense_catalog_policy import ALIAS_FIELDS, rule_groups, tokens
from .pfsense_inventory import COLUMNS
from .pfsense_navigation import object_path, resolve

RULE_FIELDS = ('type', 'interface', 'direction', 'protocol', 'source/any', 'source/network',
               'source/address', 'source/port', 'destination/any', 'destination/network',
               'destination/address', 'destination/port')
ROLE = {**COLUMNS, 'type': 'Действие', 'source/address': 'Адрес источника',
        'destination/address': 'Адрес назначения'}


def interface_label(key, labels):
    return 'Floating' if key == '__floating__' else labels.get(key, key.upper())


def location(obj, labels):
    section, page, leaf, _ = resolve(dict(parse_qsl(object_path(obj.component, obj.table)[1:])))
    parts = [section['label'], page['label']]
    if page is not leaf:
        parts.append(leaf['label'])
    if obj.component == 'firewall':
        parts.extend(interface_label(key, labels) for key in rule_groups(obj.data))
    return ' → '.join(parts)


def configuration(obj, references, detail=False):
    # Keep the established formatting for certificate metadata and uncommon fields.
    formatted = dict(fields(obj))
    keys = list(obj.data) if detail or obj.component != 'firewall' else RULE_FIELDS
    output = []
    for key in keys:
        if key in ('order', 'native_interface_id') or not obj.data.get(key):
            continue
        label = COLUMNS.get(key, key)
        if obj.component == 'firewall':
            label = ROLE.get(key, label)
        if key in ALIAS_FIELDS or key in ('interface', 'sched', 'gateway'):
            values = tokens(obj.data[key])
        else:
            values = [formatted.get(COLUMNS.get(key, key), ', '.join(obj.data[key]))]
        if key.startswith(('source/', 'destination/')) and not key.endswith('/not') and obj.data.get(key.split('/')[0] + '/not'):
            label += ' (исключение)'
        items = [dict(text=value, url=references.get((key, value))) for value in values]
        output.append(dict(label=label, items=items, preview=items[:3], more=items[3:]))
    return output


def decorate(page, appliance, group, labels):
    refs = defaultdict(dict)
    objects = [hit['object'] for hit in page]
    for ref in FirewallReference.objects.filter(source__in=objects).exclude(target__state='removed').select_related('target'):
        for name in ref.target.data.get('name', []):
            refs[ref.source_id][ref.field, name] = ref.target.get_absolute_url()
    positions = defaultdict(dict)
    if any(obj.component == 'firewall' for obj in objects):
        counters = Counter()
        rules = appliance.entries.filter(component='firewall', table='rules').exclude(state='removed')
        for pk, data in rules.values_list('pk', 'data'):
            for key in rule_groups(data):
                counters[key] += 1
                positions[pk][key] = counters[key]
    for hit in page:
        obj = hit['object']
        local = positions.get(obj.pk, {})
        number = local.get(group) or ', '.join(str(n) for n in local.values()) or obj.position
        hit.update(number=number, path=location(obj, labels), cells=configuration(obj, refs[obj.pk]))

