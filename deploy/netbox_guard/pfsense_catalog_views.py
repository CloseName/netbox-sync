"""Read-only pfSense pages with appliance-local search and native hierarchy."""
from urllib.parse import urlencode
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET
from dcim.models import Device
from . import pfsense_catalog as catalog
from .pfsense_inventory import LABELS, STATE, panel
from .pfsense_navigation import MENU, resolve, links, object_path
from .pfsense_system import CHILD_FIELDS


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
    whole = bool(params.get('q', '').strip()) and (params.get('scope') == 'firewall' or not selected.get('component'))
    groups = []
    if whole:
        params.pop('group', None)
    else:
        params['component'], params['table'] = selected.get('component', ''), selected.get('table', '')
        if selected.get('group_by'):
            entries = obj.entries.filter(component=selected['component'], table=selected['table']).exclude(state='removed')
            labels = ((obj.vm.custom_field_data or {}).get('pfsense_inventory') or {}).get('interface_labels', {})
            keys = set()
            for row in entries.values_list('data', flat=True):
                if selected['component'] == 'firewall' and row.get('floating') in ([''], ['yes'], ['true'], ['1']):
                    keys.add('__floating__')
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
    return dict(page=catalog.page(request.user, params), filters=params, page_query=query.urlencode(),
                states=catalog.STATES.items(), groups=groups, whole=whole)


@login_required
@require_GET
def appliance(request, pk):
    obj = get_object_or_404(catalog.appliances(request.user), pk=pk)
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
    if selected.get('component') or request.GET.get('q', '').strip():
        context.update(search_context(request, obj, selected, path))
        if selected.get('component') in ('general', 'users') and selected.get('table') in ('settings', 'webgui') and not context.get('whole'):
            context['settings_rows'] = [dict(object=hit['object'], fields=catalog.fields(hit['object'])) for hit in context['page']]
            context['settings_page'] = True
    return render(request, 'netbox_guard/pfsense_appliance.html', context)


@login_required
@require_GET
def detail(request, uid):
    obj = catalog.object_for(request.user, uid)
    incoming = list(obj.referenced_by.select_related('source').exclude(source__state='removed'))
    children = [ref for ref in incoming if ref.field in CHILD_FIELDS]
    return render(request, 'netbox_guard/pfsense_object.html', dict(
        entry=obj, fields=catalog.fields(obj), document=catalog.document(request.user, obj),
        section_url=obj.appliance.get_absolute_url() + object_path(obj.component, obj.table), children=children,
        state_label=catalog.STATES[obj.state],
        custom_fields=obj.get_custom_fields(omit_hidden=True),
        incoming=[ref for ref in incoming if ref not in children]))
