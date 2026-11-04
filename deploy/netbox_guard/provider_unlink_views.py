"""Signed per-resource unlink review, using the existing lifecycle fence."""
import hashlib
from uuid import uuid4
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods
from .dependencies import DependencyGuardBlocked
from .models import ProviderInventory
from .provider_lifecycle import review, execute
from .resource_tree import build_tree

SALT = 'selectel-unlink-v1'


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
@csrf_protect
def unlink(request, account, ref):
    if not request.user.has_perm('netbox_guard.manage_providerbinding'):
        raise PermissionDenied
    record = next((r for r in ProviderInventory.objects.filter(account=account)
                   if hashlib.sha256(r.pk.encode()).hexdigest() == ref), None)
    if record is None:
        raise Http404
    source = build_tree([], [record])[0][0]
    base = reverse('plugins:netbox_guard:provider_resource_account', kwargs={'account': account})
    context = dict(source=source, account=account,
                   back_url=base + '?kind=' + source['kind'] + '&resource=' + ref)
    status = 200
    try:
        if request.method == 'POST':
            token = signing.loads(request.POST.get('review_token', ''), salt=SALT, max_age=600)
            if (not isinstance(token, dict) or token.get('actor') != str(request.user.pk)
                    or token.get('account') != account or token.get('key') != record.pk
                    or request.POST.get('confirm_unlink') != 'yes'):
                raise ValueError('PROVIDER_CONFIRMATION_REQUIRED')
            context['result'] = execute(request.user, account, 'unlink', token['nonce'],
                                        token['fingerprint'], record.pk)
        else:
            plan = review(request.user, account, 'unlink', record.pk)
            context['plan'] = plan
            context['review_token'] = signing.dumps(dict(actor=str(request.user.pk), account=account,
                key=record.pk, nonce=str(uuid4()), fingerprint=plan['fingerprint']), salt=SALT)
    except DependencyGuardBlocked:
        raise PermissionDenied
    except (ValueError, KeyError, signing.BadSignature):
        context['error'] = 'Состояние изменилось или операция недоступна. Вернитесь к сведениям и проверьте сопоставление заново.'
        status = 409
    return render(request, 'netbox_guard/provider_unlink.html', context, status=status)
