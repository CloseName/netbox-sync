"""Read-only account/type navigation over the native IPAM projection."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import render
from django.views.decorators.http import require_GET
from .routing_catalog import domains


@login_required
@require_GET
def overview(request):
    if not request.user.has_perm('netbox_guard.view_resourceregistry'):
        raise PermissionDenied
    rows = list(domains(request.user))
    accounts = sorted({r['account'] for r in rows})
    account, kind = request.GET.get('account', ''), request.GET.get('kind', '')
    query = request.GET.get('q', '')[:256]
    filtered = [r for r in rows if (not account or r['account'] == account) and
                (not kind or r['kind'] == kind) and query.casefold() in
                ' '.join(str(r[k]) for k in ('name', 'account', 'project', 'zone')).casefold()]
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'netbox_guard/routing_overview.html', dict(
        page=Paginator(filtered, 50).get_page(request.GET.get('page')), accounts=accounts,
        account=account, kind=kind, q=query, page_query=params.urlencode()))
