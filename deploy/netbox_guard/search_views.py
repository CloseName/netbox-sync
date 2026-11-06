"""NetBox 4.7 search form/backend with direct route results and address-first ordering."""
import re
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.shortcuts import render
from django_tables2 import RequestConfig
from netbox.forms import SearchForm
from netbox.search import LookupTypes
from netbox.search.backends import search_backend
from netbox.tables import SearchTable
from netbox.views import SearchView
from utilities.htmx import htmx_partial
from utilities.paginator import EnhancedPaginator, get_paginate_count
from .network_search import result_rank
from .routing_catalog import routes


class InventorySearchView(SearchView):
    def get(self, request):
        results, route_results, highlight = [], [], None
        pfsense_url = None
        form = SearchForm(request.GET) if 'q' in request.GET else SearchForm()
        if form.is_valid():
            query = form.cleaned_data['q']
            selected = form.cleaned_data['obj_types']
            object_types = [ContentType.objects.get_by_natural_key(*t.split('.')) for t in selected]
            lookup = form.cleaned_data['lookup'] or LookupTypes.PARTIAL
            if not selected and lookup in (LookupTypes.PARTIAL, LookupTypes.EXACT) and request.user.has_perm('virtualization.view_virtualmachine'):
                from .pfsense_catalog import appliances
                from django.urls import reverse
                from urllib.parse import urlencode
                # Keep ordinary NetBox search independent of configuration size.
                if appliances(request.user).exists():
                    pfsense_url = reverse('plugins:netbox_guard:pfsense_search') + '?' + urlencode({'q': query})
            results = search_backend.search(query, user=request.user, object_types=object_types, lookup=lookup)
            if lookup in (LookupTypes.PARTIAL, LookupTypes.EXACT):
                results = sorted(results, key=lambda hit: result_rank(query, hit))
                if not selected or 'ipam.vrf' in selected:
                    route_results = routes(request.user, query, exact=lookup == LookupTypes.EXACT)
            if lookup == LookupTypes.REGEX:
                try:
                    highlight = re.compile(f'({query})', flags=re.IGNORECASE)
                except re.error:
                    pass
            elif lookup != LookupTypes.EXACT:
                highlight = query
        table = SearchTable(results, highlight=highlight)
        RequestConfig(request, {'paginator_class': EnhancedPaginator,
                               'per_page': get_paginate_count(request)}).configure(table)
        context = dict(form=form, table=table, pfsense_url=pfsense_url,
            route_page=Paginator(route_results, 25).get_page(request.GET.get('route_page')))
        params = request.GET.copy()
        params.pop('route_page', None)
        context['route_query'] = params.urlencode()
        if htmx_partial(request):
            return render(request, 'htmx/table.html', context)
        return render(request, 'netbox_guard/search.html', context)
