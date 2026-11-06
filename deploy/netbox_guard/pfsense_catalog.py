"""Permission-aware catalog reads shared by UI, search and the graph API."""
from collections import Counter
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from virtualization.models import VirtualMachine, VMInterface
from .models import FirewallAppliance, FirewallObject, NetworkBinding
from .pfsense_catalog_policy import match, TABS, FIELD_LABELS
from .pfsense_inventory import COLUMNS, LABELS, TITLES, FLAGS

STATES = {'current': 'В последнем сборе', 'retained': 'Сохранено ранее · ошибка сбора', 'removed': 'Больше нет в конфигурации'}


def appliances(user):
    if not user.has_perm('virtualization.view_virtualmachine'):
        raise PermissionDenied
    return FirewallAppliance.objects.filter(vm__in=VirtualMachine.objects.restrict(user, 'view')).select_related('vm__site')


def entries(user):
    return FirewallObject.objects.filter(appliance__in=appliances(user)).select_related('appliance__vm__site')


def filtered(user, params):
    selected = appliances(user)
    for param, field in (('appliance', 'pk'), ('site', 'vm__site_id')):
        value = params.get(param, '')
        if value:
            if not str(value).isdigit():
                return FirewallObject.objects.none()
            selected = selected.filter(**{field: value})
    rows = entries(user).filter(appliance__in=selected)
    if params.get('category') in dict(TABS) and params['category'] != 'overview':
        rows = rows.filter(category=params['category'])
    state = params.get('state', '')
    if state in STATES:
        rows = rows.filter(state=state)
    else:
        rows = rows.exclude(state='removed')
    if params.get('enabled') in ('yes', 'no'):
        rows = rows.filter(enabled=params['enabled'] == 'yes')
    return rows


def aliases_for(appliance):
    rows = list(FirewallObject.objects.filter(appliance=appliance, component='aliases').exclude(state='removed'))
    counts = Counter(name for row in rows for name in row.data.get('name', []))
    return {name: row.data.get('address', []) for row in rows for name in row.data.get('name', [])
            if counts[name] == 1 and not row.data.get('content_omitted')}


def results(user, params):
    query = params.get('q', '').strip()[:256]
    aliases, scope = {}, None
    for obj in filtered(user, params).iterator(chunk_size=500):
        if scope != obj.appliance_id:
            scope = obj.appliance_id
            aliases = aliases_for(scope) if query else {}
        reasons = match(query, obj.data, aliases) if query else []
        if not query or reasons or query == str(obj.uid):
            yield {'object': obj, 'reasons': reasons, 'state_label': STATES[obj.state],
                   'kind': LABELS.get(obj.component, 'Интерфейсы') + ' · ' + TITLES.get(obj.table, obj.table)}


def fields(obj):
    result = []
    for key, value in obj.data.items():
        if key == 'native_interface_id':
            continue
        if key == 'order':
            value = str(value)
        elif not value:
            continue
        elif key in FLAGS and value == ['']:
            value = 'Да'
        else:
            value = ', '.join(value)
        result.append((COLUMNS.get(key, FIELD_LABELS.get(key, key)), value))
    return result


def native_interface(user, obj):
    if obj.component != 'interfaces':
        return None
    ids = obj.data.get('native_interface_id', [])
    if len(ids) != 1 or not ids[0].isdigit():
        return None
    interface = VMInterface.objects.restrict(user, 'view').filter(pk=int(ids[0]), virtual_machine_id=obj.appliance.vm_id).first()
    # A deleted/recreated native interface or changed MAC invalidates the link.
    if interface and interface.primary_mac_address_id and str(interface.primary_mac_address.mac_address).casefold() in [m.casefold() for m in obj.data.get('mac', [])]:
        return interface
    return None


def document(user, obj):
    links = []
    for ref in obj.references.select_related('target').all():
        links.append(dict(field=ref.field, target=str(ref.target.uid), name=ref.target.name,
                          url=ref.target.get_absolute_url(), state=ref.target.state))
    native = native_interface(user, obj)
    prefixes = []
    if native:
        from ipam.models import Prefix
        visible = Prefix.objects.restrict(user, 'view')
        bindings = NetworkBinding.objects.filter(vm_id=obj.appliance.vm_id, interface_id=native.pk,
                                                  interface_key__in=obj.data.get('name', []), prefix__in=visible).select_related('prefix')
        prefixes = [dict(id=b.prefix_id, prefix=str(b.prefix.prefix), vrf_id=b.prefix.vrf_id,
                         url=b.prefix.get_absolute_url()) for b in bindings]
    return dict(schema='netbox-sync.firewall-object.v1', id=str(obj.uid), name=obj.name,
        appliance_id=obj.appliance_id, vm_id=obj.appliance.vm_id, url=obj.get_absolute_url(),
        component=obj.component, table=obj.table, category=obj.category, position=obj.position,
        enabled=obj.enabled, state=obj.state, identity_kind=obj.identity_kind,
        first_seen=obj.first_seen, last_seen=obj.last_seen, data=obj.data,
        references=links, native_interface_id=native.pk if native else None,
        native_interface_url=native.get_absolute_url() if native else None, prefixes=prefixes,
        limitations=['CONFIGURATION_REFERENCE_NOT_IP_ASSIGNMENT', 'EFFECTIVE_POLICY_NOT_EVALUATED',
                     'DYNAMIC_ALIAS_CONTENTS_NOT_COLLECTED'])


def object_for(user, uid):
    return get_object_or_404(entries(user), uid=uid)
