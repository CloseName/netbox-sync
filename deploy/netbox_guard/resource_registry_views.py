import hashlib
import json
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET
from .models import ProviderResourceRegistry, ProviderResourceRegistryChange


@login_required
@require_GET
def registry(request, account=None):
    # Dedicated permission deliberately grants account-wide inventory visibility.
    if not request.user.has_perm('netbox_guard.view_resourceregistry'):
        raise PermissionDenied
    accounts = ProviderResourceRegistry.objects.order_by('account').only('account', 'revision', 'observed_at')
    context = {'accounts': accounts}
    if account is not None:
        row = get_object_or_404(ProviderResourceRegistry, account=account)
        snapshot = row.snapshot
        revision = request.GET.get('revision')
        if revision:
            try:
                revision = int(revision)
            except ValueError:
                revision = -1
            change = get_object_or_404(ProviderResourceRegistryChange, registry=row, revision=revision)
            snapshot = change.after
        resources = list(snapshot['resources'].values())
        q, kind = request.GET.get('q', '')[:256], request.GET.get('kind', '')[:64]
        selected = None
        for r in resources:
            r['ref'] = hashlib.sha256(r['key'].encode()).hexdigest()
            if r['ref'] == request.GET.get('resource'):
                selected = r
        names = {r['key']: r['name'] for r in resources}
        related = []
        if selected:
            related = [{'source': names[e['source']], 'target': names[e['target']],
                        'relation': e['relation'], 'present': e['present_in_latest']}
                       for e in snapshot['relations'].values() if selected['key'] in (e['source'], e['target'])]
        filtered = [r for r in resources if (not kind or r['kind'] == kind) and q.casefold() in r['name'].casefold()]
        context.update(registry=row, revision=revision or row.revision, q=q, kind=kind,
            page=Paginator(sorted(filtered, key=lambda r: (r['kind'], r['name'], r['key'])), 50).get_page(request.GET.get('page')),
            selected=selected, details=json.dumps(selected, ensure_ascii=False, indent=2) if selected else '',
            related=related, history=ProviderResourceRegistryChange.objects.filter(registry=row).order_by('-revision')[:20],
            coverage=json.dumps(snapshot.get('coverage', []), ensure_ascii=False, indent=2))
    return render(request, 'netbox_guard/resource_registry.html', context)
