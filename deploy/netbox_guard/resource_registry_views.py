"""Provider browsing only; all mutations use reviewed Guard commands."""
from urllib.parse import urlencode
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_GET
from dcim.models import Device
from virtualization.models import VirtualMachine
from .models import ProviderResourceRegistry, ProviderInventory, ProviderBinding
from .resource_tree import build_tree
from .resource_presentation import decorate

CATEGORIES = ('dedicated', 'cloud_vm', 'storage_container', 'dns_zone')


@login_required
@require_GET
def registry(request, account=None):
    if not request.user.has_perm('netbox_guard.view_resourceregistry'):
        raise PermissionDenied
    account_ids = sorted(set(ProviderResourceRegistry.objects.values_list('account', flat=True)) |
                         set(ProviderInventory.objects.values_list('account', flat=True)))
    if account is None and len(account_ids) == 1:
        return redirect('plugins:netbox_guard:provider_resource_account', account=account_ids[0])
    context = {'provider_accounts': account_ids, 'provider_account': account}
    if account is None:
        return render(request, 'netbox_guard/resource_registry.html', context)
    if account not in account_ids:
        raise Http404
    stored = ProviderResourceRegistry.objects.filter(pk=account).first()
    snapshot = stored.snapshot if stored else {'resources': {}, 'relations': {}}
    rows, tree = build_tree(snapshot['resources'].values(), ProviderInventory.objects.filter(account=account))
    names = {p['id']: p['name'] for p in tree if p['name'] != p['id']}
    project = request.GET.get('project', '')
    q = request.GET.get('q', '')[:256]
    kind = request.GET.get('kind', 'dedicated')
    from .resource_tree import LABELS
    if kind not in LABELS:
        raise Http404
    for p in tree:
        p['name'] = names.get(p['id']) or ('Проект · ' + p['id'][:8] if p['id'] else 'Без проекта')
    bindings = {b.provider_key: b for b in ProviderBinding.objects.filter(account=account)}
    targets = {}
    for resource, model in (('device', Device), ('vm', VirtualMachine)):
        ids = [b.object_id for b in bindings.values() if b.resource == resource]
        targets[resource] = {o.pk: o for o in model.objects.restrict(request.user, 'view').filter(pk__in=ids)}
    base = reverse('plugins:netbox_guard:provider_resource_account', kwargs={'account': account})
    selected = None
    for row in rows:
        decorate(row, names)
        row['detail_href'] = base + '?' + urlencode({'kind': row['kind'], 'resource': row['ref']})
        row['href'] = row['detail_href']
        binding = bindings.get(row['key'])
        row['binding_exists'] = binding is not None
        if binding:
            target = targets.get(binding.resource, {}).get(binding.object_id)
            if target and target.created == binding.object_created:
                row['native'] = {'name': target.name, 'url': target.get_absolute_url(), 'kind': binding.resource}
                row['href'] = target.get_absolute_url()
        if row['ref'] == request.GET.get('resource'):
            selected = row
    if request.GET.get('resource') and selected is None:
        raise Http404
    # DNS records are nested under their zone; domains under their bucket.
    children = []
    if selected:
        children = [r for r in rows if r['project'] == selected['project'] and r['region'] == selected['region']
                    and r['parent'] == selected['native_id'] and
                    (selected['kind'], r['kind']) in (('dns_zone', 'dns_rrset'), ('storage_container', 'storage_domain'))]
    filtered = [r for r in rows if r['kind'] == kind and (not project or r['project'] == project)
                and q.casefold() in (r['name'] + ' ' + (r.get('native') or {}).get('name', '')).casefold()]
    tabs = [{'kind': k, 'label': LABELS[k], 'count': sum(r['kind'] == k and (not project or r['project'] == project) for r in rows),
             'href': base + '?' + urlencode({'kind': k, 'project': project})} for k in CATEGORIES]
    context.update(projects=tree, project=project, kind=kind, kind_label=LABELS[kind], q=q, tabs=tabs,
        selected=selected, children=children,
        page=Paginator(sorted(filtered, key=lambda r: (r['name'].casefold(), r['key'])), 50).get_page(request.GET.get('page')),
        page_query=urlencode({'project': project, 'kind': kind, 'q': q}))
    return render(request, 'netbox_guard/resource_registry.html', context)
