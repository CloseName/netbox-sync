"""Read-only pfSense inventory pages; scopes use the native VM view permission."""
from collections import Counter
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET
from . import pfsense_catalog as catalog
from .pfsense_catalog_policy import TABS
from .pfsense_inventory import LABELS, STATE, panel


def search_context(request, params):
    query = params.copy()
    query.pop('page', None)
    appliances = list(catalog.appliances(request.user).order_by('vm__name'))
    sites = {a.vm.site_id: a.vm.site for a in appliances if a.vm.site_id}
    return dict(page=Paginator(list(catalog.results(request.user, params)), 50).get_page(params.get('page')),
                filters=params, page_query=query.urlencode(), appliances=appliances,
                sites=sites.values(), categories=TABS[1:], states=catalog.STATES.items())


@login_required
@require_GET
def overview(request):
    rows = []
    for appliance in catalog.appliances(request.user).order_by('vm__name'):
        counts = Counter(appliance.entries.exclude(state='removed').values_list('category', flat=True))
        rows.append(dict(appliance=appliance, rules=counts['rules'], nat=counts['nat'], aliases=counts['aliases'],
                         partial=any(v.get('collection') != 'ok' for v in appliance.coverage.values())))
    return render(request, 'netbox_guard/pfsense_overview.html', {'rows': rows})


@login_required
@require_GET
def search(request):
    return render(request, 'netbox_guard/pfsense_search.html', search_context(request, request.GET))


@login_required
@require_GET
def appliance(request, pk):
    obj = get_object_or_404(catalog.appliances(request.user), pk=pk)
    tab = request.GET.get('tab', 'overview')
    if tab not in dict(TABS) and tab != 'observations':
        tab = 'overview'
    context = dict(appliance=obj, tab=tab, tabs=[])
    for key, label in TABS + [('observations', 'Наблюдения и пакеты')]:
        params = request.GET.copy()
        params.pop('page', None)
        params['tab'] = key
        context['tabs'].append(dict(key=key, label=label, url='?' + params.urlencode()))
    context['coverage'] = [(LABELS.get(key, 'Интерфейсы'), STATE.get(value.get('collection'), 'Неизвестно')) for key, value in obj.coverage.items()]
    if tab == 'observations':
        context['inventory'] = panel((obj.vm.custom_field_data or {}).get('pfsense_inventory'))
        if context['inventory'] and not context['inventory'].get('invalid'):
            context['inventory']['details'] = []
        context['object'] = obj.vm
    elif tab != 'overview':
        params = request.GET.copy()
        params['appliance'], params['category'] = str(obj.pk), tab
        context.update(search_context(request, params))
    else:
        context['counts'] = [(label, obj.entries.filter(category=key).exclude(state='removed').count(),
                              obj.get_absolute_url() + '?tab=' + key) for key, label in TABS[1:]]
    return render(request, 'netbox_guard/pfsense_appliance.html', context)


@login_required
@require_GET
def detail(request, uid):
    obj = catalog.object_for(request.user, uid)
    return render(request, 'netbox_guard/pfsense_object.html', dict(
        entry=obj, fields=catalog.fields(obj), document=catalog.document(request.user, obj),
        state_label=catalog.STATES[obj.state],
        incoming=obj.referenced_by.select_related('source').exclude(source__state='removed')))
