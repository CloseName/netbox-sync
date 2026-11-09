"""Read-only pfSense pages with appliance-local search and native hierarchy."""
from urllib.parse import parse_qsl, urlencode
from ipaddress import ip_address
import re
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET
from dcim.models import Device
from . import pfsense_catalog as catalog
from .pfsense_inventory import LABELS, STATE, panel
from .pfsense_navigation import MENU, resolve, links, object_path
from .pfsense_system import CHILD_FIELDS
from .pfsense_address_search import inspect_address
from .pfsense_catalog_policy import rule_groups, search_hits
from .pfsense_presentation import configuration, decorate, location, reference_links, ROLE
from .pfsense_locale import label as ui_label
from .pfsense_tables import HEADINGS, LAYOUTS, table_cells


def list_params(params):
    keys = ('section', 'view', 'sub', 'group', 'alias_type', 'scope', 'q', 'enabled', 'page')
    return {key: params[key][:256] for key in keys if params.get(key)}


def host_for(user, appliance):
    if not appliance.vm.device_id or not user.has_perm('dcim.view_device'):
        return None
    return Device.objects.restrict(user, 'view').filter(pk=appliance.vm.device_id).first()


@login_required
@require_GET
def overview(request):
    rows = []
    for appliance in catalog.appliances(request.user).order_by('vm__device__name', 'vm__name'):
        rows.append(dict(appliance=appliance, host=host_for(request.user, appliance),
                         partial=any(v.get('collection') != 'ok' for v in appliance.coverage.values())))
    return render(request, 'netbox_guard/pfsense_overview.html', {'rows': rows})


def search_context(request, obj, selected, path):
    params = request.GET.copy()
    # Never let a supplied appliance/site/category escape the firewall being viewed.
    for key in ('appliance', 'site', 'category', 'component', 'table', 'tab'):
        params.pop(key, None)
    params['appliance'] = str(obj.pk)
    for key, value in path.items():
        params[key] = value
    params.pop('state', None)
    term = params.get('q', '').strip()
    whole = bool(term) and params.get('scope') == 'firewall'
    labels = ((obj.vm.custom_field_data or {}).get('pfsense_inventory') or {}).get('interface_labels', {})
    groups = []
    if whole:
        params.pop('group', None)
        params.pop('alias_type', None)
    else:
        params['component'], params['table'] = selected.get('component', ''), selected.get('table', '')
        if selected.get('group_by'):
            entries = obj.entries.filter(component=selected['component'], table=selected['table']).exclude(state='removed')
            keys = set()
            for row in entries.values_list('data', flat=True):
                if selected['component'] == 'firewall':
                    keys.update(rule_groups(row))
                else:
                    keys.update(row.get('interface', []))
            for key in sorted(keys):
                query = {**path, 'group': key}
                groups.append(dict(key=key, label='Floating' if key == '__floating__' else labels.get(key, key.upper()), url='?' + urlencode(query)))
            if keys and params.get('group') not in keys:
                params['group'] = sorted(keys)[0]
        else:
            params.pop('group', None)
    query = params.copy()
    query.pop('page', None)
    try:
        address = ip_address(term)
    except ValueError:
        address = None
    inspection = inspect_address(request.user, obj, address) if address is not None else None
    result = dict(filters=params, page_query=query.urlencode(), groups=groups, whole=whole,
                  inspection=inspection, fragment=bool(re.fullmatch(r'(?:\d{1,3}\.){1,2}\d{0,3}', term)))
    if whole or selected.get('component'):
        page = catalog.page(request.user, params)
        back = list_params(params)
        result['headers'] = decorate(page, obj, params.get('group'), labels, selected, urlencode(back))
        if not whole and selected.get('component') == 'aliases':
            base = {k: v for k, v in back.items() if k not in ('alias_type', 'page')}
            result['alias_tabs'] = [
                dict(label=name, active=params.get('alias_type', '') == key,
                     url='?' + urlencode(dict(base, alias_type=key)))
                for key, name in (('', 'Все'), ('ip', 'IP и сети'), ('ports', 'Порты'), ('urls', 'URL'))]
        result.update(page=page, direct=[hit for hit in page if not hit['covering']],
                      covering=[hit for hit in page if hit['covering']])
    return result


def special_matches(context, key, term):
    """Filter the displayed snapshot rows on tabs without catalog objects."""
    needle = term.casefold()
    def matches(values):
        return any(needle in str(value).casefold() for value in values)

    context['coverage'] = [row for row in context['coverage'] if matches(row)]
    inventory = context.get('inventory') or {}
    if key == 'services':
        inventory['summary'] = [row for row in inventory.get('summary', []) if matches(row)]
    if key == 'packages':
        inventory['packages'] = [row for row in inventory.get('packages', []) if matches(row.values())]
    for item in context.get('runtime_rows', []):
        item['rows'] = [row for row in item.get('rows', []) if matches(row)]
        for group in item.get('groups', []):
            group['records'] = [row for row in group['records']
                                if matches(value for _, value in row['fields'])]
        item['groups'] = [group for group in item.get('groups', []) if group['records']]


@login_required
@require_GET
def appliance(request, pk):
    obj = get_object_or_404(catalog.appliances(request.user), pk=pk)
    return render(request, 'netbox_guard/pfsense_appliance.html', appliance_context(request, obj))


def appliance_context(request, obj):
    section, page, selected, path = resolve(request.GET)
    context = dict(appliance=obj, host=host_for(request.user, obj), selected=selected, path=path,
                   sections=links(MENU, {}, 'section'), views=links(section['children'], {'section': section['key']}, 'view'),
                   subviews=links(page.get('children', []), {'section': section['key'], 'view': page['key']}, 'sub'))
    for items, active in ((context['sections'], section['key']), (context['views'], page['key']), (context['subviews'], selected['key'])):
        for item in items:
            item['active'] = item['key'] == active
    context['coverage'] = [(LABELS.get(key, 'Interfaces'), STATE.get(value.get('collection'), 'Неизвестно'), STATE.get(value.get('configuration'), '—')) for key, value in obj.coverage.items()]
    component = obj.coverage.get(selected.get('component'), {})
    context['collection'] = component.get('collection', 'not_collected')
    context['configuration'] = component.get('configuration', 'unknown')
    if selected.get('special'):
        context['inventory'] = panel((obj.vm.custom_field_data or {}).get('pfsense_inventory'))
        if context['inventory'] and not context['inventory'].get('invalid'):
            key = selected['special']
            context['runtime_rows'] = [r for r in context['inventory']['routes'] if (r['key'] == 'pf_nat') == (key == 'nat')]
            for snapshot in context['runtime_rows']:
                snapshot['unparsed'] = 'Вывод' in snapshot['columns']
    if selected.get('component') or request.GET.get('q', '').strip():
        context.update(search_context(request, obj, selected, path))
        if selected.get('special') and not context['whole'] and request.GET.get('q', '').strip():
            special_matches(context, selected['special'], request.GET['q'].strip())
        if selected.get('table') in ('settings', 'webgui', 'defaults', 'mode') and not request.GET.get('q', '').strip():
            context['settings_rows'] = [dict(object=hit['object'], fields=[
                field for field in catalog.fields(hit['object']) if field[0] != '№']) for hit in context['page']]
            context['settings_page'] = True
    return context


@login_required
@require_GET
def detail(request, uid):
    obj = get_object_or_404(catalog.entries(request.user).exclude(state='removed'), uid=uid)
    incoming = list(obj.referenced_by.select_related('source').exclude(source__state='removed'))
    children = [ref for ref in incoming if ref.field in CHILD_FIELDS]
    labels = ((obj.appliance.vm.custom_field_data or {}).get('pfsense_inventory') or {}).get('interface_labels', {})
    document = catalog.document(request.user, obj)
    back = list_params(dict(parse_qsl(request.GET.get('back', '')[:4096])))
    children_rows = []
    child_refs = reference_links([ref.source for ref in children])
    for ref in sorted(children, key=lambda ref: ref.source.position):
        child = ref.source
        columns = LAYOUTS[(child.component, child.table)].split()
        children_rows.append(dict(object=child, headers=[HEADINGS[k] for k in columns],
                                  columns=table_cells(child, columns, child_refs[child.pk], translate=ui_label)))
    refs = reference_links([obj])[obj.pk]
    term = back.get('q', '')
    matches = search_hits(term, obj.data, catalog.aliases_for(obj.appliance_id),
                          interface=obj.component == 'interfaces') if term else []
    return render(request, 'netbox_guard/pfsense_object.html', dict(
        entry=obj, cells=configuration(obj, refs, term), document=document, matches=matches,
        section_url=obj.appliance.get_absolute_url() + object_path(obj.component, obj.table),
        return_url=obj.appliance.get_absolute_url() + '?' + urlencode(back) + '#obj-' + str(obj.uid) if back else '',
        children=children_rows,
        state_label=catalog.STATES[obj.state],
        custom_fields=obj.get_custom_fields(omit_hidden=True),
        incoming=[dict(source=ref.source, path=location(ref.source, labels), role=ROLE.get(ref.field, ref.field))
                  for ref in incoming if ref not in children]))
