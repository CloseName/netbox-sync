from types import SimpleNamespace
import json
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET
from .models import ProviderResourceRegistry, ProviderResourceRegistryChange, ProviderInventory
from .resource_tree import build_tree


@login_required
@require_GET
def registry(request, account=None):
    # Dedicated permission deliberately grants account-wide inventory visibility.
    if not request.user.has_perm('netbox_guard.view_resourceregistry'):
        raise PermissionDenied
    account_ids = set(ProviderResourceRegistry.objects.values_list('account', flat=True))
    account_ids.update(ProviderInventory.objects.values_list('account', flat=True))
    accounts = [dict(account=a) for a in sorted(account_ids)]
    context = {'accounts': accounts}
    if account is not None:
        if account not in account_ids:
            raise Http404
        row = ProviderResourceRegistry.objects.filter(account=account).first()
        row = row or SimpleNamespace(account=account, revision=None,
            snapshot={'resources': {}, 'relations': {}, 'coverage': []})
        snapshot = row.snapshot
        revision = request.GET.get('revision')
        if revision:
            try:
                revision = int(revision)
            except ValueError:
                revision = -1
            change = get_object_or_404(ProviderResourceRegistryChange, registry_id=account, revision=revision)
            snapshot = change.after
        resources, tree = build_tree(snapshot['resources'].values(),
            ProviderInventory.objects.filter(account=account) if not revision else (), revision)
        project = request.GET.get('project')
        q, kind = request.GET.get('q', '')[:256], request.GET.get('kind', '')[:64]
        selected = None
        for r in resources:
            if r['ref'] == request.GET.get('resource'):
                selected = r
        names = {r['key']: r['name'] for r in snapshot['resources'].values()}
        related = []
        if selected:
            related = [{'source': names.get(e['source'], e['source']), 'target': names.get(e['target'], e['target']),
                        'relation': e['relation'], 'present': e['present_in_latest']}
                       for e in snapshot['relations'].values() if selected['key'] in (e['source'], e['target'])]
        filtered = [r for r in resources if project is not None and r['project'] == project and (not kind or r['kind'] == kind) and q.casefold() in r['name'].casefold()]
        context.update(tree=tree, project=project, historical=bool(revision), show_list=project is not None, registry=row, revision=revision or row.revision, q=q, kind=kind,
            page=Paginator(sorted(filtered, key=lambda r: (r['kind'], r['name'], r['key'])), 50).get_page(request.GET.get('page')),
            selected=selected, details=json.dumps(selected, ensure_ascii=False, indent=2, default=str) if selected else '',
            related=related, history=ProviderResourceRegistryChange.objects.filter(registry_id=account).order_by('-revision')[:20],
            coverage=json.dumps(snapshot.get('coverage', []), ensure_ascii=False, indent=2))
    return render(request, 'netbox_guard/resource_registry.html', context)
