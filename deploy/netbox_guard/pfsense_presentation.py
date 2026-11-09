"""Presentation of current configuration objects and their same-appliance references."""
from collections import Counter, defaultdict
from urllib.parse import parse_qsl, urlencode

from .pfsense_locale import label as ui_label
from .models import FirewallReference
from .pfsense_catalog import fields
from .pfsense_catalog_policy import ALIAS_FIELDS, contains, rule_groups, tokens
from .pfsense_tables import HEADINGS, LAYOUTS, table_cells
from .pfsense_inventory import COLUMNS
from .pfsense_navigation import object_path, resolve

ROLE = {**COLUMNS, 'type': 'Действие', 'source/address': 'Адрес источника',
        'destination/address': 'Адрес назначения', 'associated-rule-id': 'Связанное правило',
        'defaultqueue': 'Очередь', 'ackqueue': 'Очередь ACK', 'nordr': 'Без перенаправления'}


def interface_label(key, labels):
    return 'Floating' if key == '__floating__' else labels.get(key, key.upper())


def location(obj, labels):
    section, page, leaf, _ = resolve(dict(parse_qsl(object_path(obj.component, obj.table)[1:])))
    parts = [ui_label(section['label']), ui_label(page['label'])]
    if page is not leaf:
        parts.append(ui_label(leaf['label']))
    if obj.component == 'firewall':
        parts.extend(interface_label(key, labels) for key in rule_groups(obj.data))
    return ' → '.join(parts)


def configuration(obj, references, term=''):
    # Keep the established formatting for certificate metadata and uncommon fields.
    formatted = dict(fields(obj))
    keys = list(obj.data)
    groups = defaultdict(list)
    for key in keys:
        if key in ('order', 'native_interface_id') or not obj.data.get(key):
            continue
        label = HEADINGS.get(key, COLUMNS.get(key, key))
        if obj.component == 'firewall' or key == 'associated-rule-id':
            label = ROLE.get(key, label)
        if key in ALIAS_FIELDS or key in ('interface', 'sched', 'gateway'):
            values = tokens(obj.data[key])
        elif any((key, value) in references for value in obj.data[key]):
            values = obj.data[key]
        else:
            values = [formatted.get(COLUMNS.get(key, key), ', '.join(obj.data[key]))]
        if key.startswith(('source/', 'destination/')) and not key.endswith('/not') and obj.data.get(key.split('/')[0] + '/not'):
            label += ' (исключение)'
        items = [dict(text=value, url=references.get((key, value)),
                      matched=bool(term and (term.casefold() in value.casefold() or contains(term, value))))
                 for value in values]
        if key.startswith('source/'):
            group = 'Источник'
        elif key.startswith('destination/'):
            group = 'Назначение'
        elif obj.component == 'aliases' and key == 'address':
            group = 'Состав alias'
        elif key in ('tracker', 'refid', 'uid', 'gid', 'ikeid', 'uniqid', 'metadata_state', 'fingerprint_sha256'):
            group = 'Идентификаторы и метаданные'
        else:
            group = 'Параметры'
        groups[group].append(dict(label=label, items=items))
    return [(name, groups[name]) for name in ('Параметры', 'Источник', 'Назначение', 'Состав alias',
                                              'Идентификаторы и метаданные') if groups[name]]


def reference_links(objects):
    refs = defaultdict(dict)
    for ref in FirewallReference.objects.filter(source__in=objects).exclude(target__state='removed').select_related('target'):
        for field in ('name', 'uid', 'refid', 'ikeid', 'associated-rule-id'):
            for value in ref.target.data.get(field, []):
                refs[ref.source_id][ref.field, value] = ref.target.get_absolute_url()
    return refs


def related_values(objects):
    related = defaultdict(lambda: defaultdict(list))
    links = FirewallReference.objects.filter(target__in=objects, field__in=('member', '../name')).exclude(
        source__state='removed').select_related('source').order_by('source__position', 'source_id')
    for link in links:
        source = link.source
        if link.field == 'member':
            key, text = 'memberships', source.name
        else:
            key = 'intervals'
            text = ' · '.join(' '.join(source.data[k]) for k in ('rangedescr', 'day', 'position', 'hour') if source.data.get(k))
        related[link.target_id][key].append(dict(text=text or source.name, url=source.get_absolute_url()))
    return related


def decorate(page, appliance, group, labels, selected, back):
    objects = [hit['object'] for hit in page]
    refs = reference_links(objects)
    related = related_values(objects)
    columns = LAYOUTS.get((selected.get('component'), selected.get('table')), '').split()
    positions = defaultdict(dict)
    optional = {'gateway': ('gateway',), 'queue': ('defaultqueue', 'ackqueue'), 'sched': ('sched',)}
    present = set()
    if any(obj.component == 'firewall' for obj in objects):
        counters = Counter()
        rules = appliance.entries.filter(component='firewall', table='rules').exclude(state='removed')
        for pk, data in rules.values_list('pk', 'data'):
            for key in rule_groups(data):
                counters[key] += 1
                positions[pk][key] = counters[key]
                if key == group:
                    present.update(col for col, fields in optional.items() if any(data.get(f) for f in fields))
    if selected.get('component') == 'firewall':
        columns = [key for key in columns if key not in optional or key in present]
    for hit in page:
        obj = hit['object']
        local = positions.get(obj.pk, {})
        number = local.get(group) or ', '.join(str(n) for n in local.values()) or obj.position
        if obj.component == 'dhcp' and obj.table == 'static_ipv4':
            for address in obj.data.get('ipaddr', []):
                refs[obj.pk]['ipaddr', address] = appliance.get_absolute_url() + '?' + urlencode({
                    'section': 'services', 'view': 'dhcp', 'sub': 'static_ipv4', 'scope': 'firewall', 'q': address})
        hit.update(number=number, path=location(obj, labels),
                   url=obj.get_absolute_url() + '?' + urlencode({'back': back}),
                   columns=table_cells(obj, columns, refs[obj.pk], related[obj.pk], translate=ui_label))
    return [HEADINGS[key] for key in columns]
