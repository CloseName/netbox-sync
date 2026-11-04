"""Choose an existing card, then confirm a signed, short-lived association review."""
import hashlib
from uuid import uuid4
from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods
from .dependencies import DependencyGuardBlocked
from .models import ProviderInventory
from .provider_manual_link import review, execute
from .provider_service import MODELS

SALT = 'selectel-manual-link-v1'


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
@csrf_protect
def manual_link(request, account, ref):
    if not request.user.has_perm('netbox_guard.manage_providerbinding'):
        raise PermissionDenied
    key = next((key for key in ProviderInventory.objects.filter(account=account).values_list('provider_key', flat=True)
                if hashlib.sha256(key.encode()).hexdigest() == ref), None)
    if key is None:
        raise Http404
    record = ProviderInventory.objects.get(pk=key, account=account)
    kind = 'device' if record.snapshot['identity']['kind'] == 'dedicated' else 'vm'
    context = dict(account=account, resource=kind,
                   back_url=reverse('plugins:netbox_guard:provider_resource_account', kwargs={'account': account}))
    status = 200
    try:
        if request.method == 'POST':
            token = signing.loads(request.POST.get('review_token', ''), salt=SALT, max_age=600)
            if (not isinstance(token, dict) or token.get('actor') != str(request.user.pk)
                    or token.get('account') != account or token.get('key') != key
                    or request.POST.get('confirm_same') != 'yes'):
                raise ValueError('PROVIDER_CONFIRMATION_REQUIRED')
            context['result'] = execute(request.user, account, key, token['object_id'],
                                        token['nonce'], token['fingerprint'])
        elif request.GET.get('object_id'):
            preview = review(request.user, account, key, int(request.GET['object_id']))
            context['preview'] = preview
            context['review_token'] = signing.dumps(dict(actor=str(request.user.pk), account=account,
                key=key, object_id=preview['object_id'], nonce=str(uuid4()), fingerprint=preview['fingerprint']), salt=SALT)
    except DependencyGuardBlocked:
        raise PermissionDenied
    except (ValueError, KeyError, signing.BadSignature, ValidationError):
        context['error'] = 'Связывание недоступно или проверка устарела. Обновите сбор и проверьте права, аппаратные идентификаторы и существующие привязки.'
        status = 409
    if not context.get('result') and not context.get('preview'):
        q = request.GET.get('q', '')[:128]
        model = apps.get_model(MODELS[kind])
        targets = model.objects.restrict(request.user, 'view').restrict(request.user, 'change')
        if q:
            targets = targets.filter(name__icontains=q)
        # Bounded search also permits choosing a card which has no heuristic candidate.
        context.update(q=q, targets=list(targets.order_by('name', 'pk')[:50]))
    return render(request, 'netbox_guard/provider_manual_link.html', context, status=status)
