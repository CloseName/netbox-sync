"""Authenticated review and CSRF-protected per-resource first creation."""
import hashlib
from uuid import uuid4
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
from .provider_first_creation import review, execute

SALT = 'selectel-first-creation-v1'
REASONS = {
    'hardware_identity_missing': 'Аппаратный идентификатор не получен. Возможные совпадения не найдены, но это не доказывает отсутствие карточки. Проверьте инвентарь перед созданием.',
    'identity_needs_confirmation': 'Найдены возможные совпадения. Сначала проверьте эти карточки: создавать ещё одну пока нельзя.',
    'hardware_identity_conflict': 'Аппаратные идентификаторы противоречат друг другу. Требуется проверка сведений провайдера и NetBox.',
    'fresh_inventory_required': 'Нужен свежий успешный сбор Selectel. Сохранённых сведений недостаточно для создания.',
    'placement_missing': 'Не получена актуальная площадка Selectel. Обновите сбор и проверьте сведения о размещении.',
    'operator_detached': 'Ресурс отсоединён. Создание новой карточки запрещено.',
    'existing_binding': 'Этот ресурс уже связан с карточкой NetBox. Повторное создание не требуется.',
    'provider_uuid_required': 'Не получен корректный UUID ресурса Selectel.',
}


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
@csrf_protect
def first_creation(request, account, ref):
    if not request.user.has_perm('netbox_guard.manage_providerbinding'):
        raise PermissionDenied
    key = next((key for key in ProviderInventory.objects.filter(account=account).values_list('provider_key', flat=True)
                if hashlib.sha256(key.encode()).hexdigest() == ref), None)
    if key is None:
        raise Http404
    context = {'account': account, 'back_url': reverse('plugins:netbox_guard:provider_resource_account',
                                                    kwargs={'account': account})}
    status = 200
    if request.method == 'POST':
        try:
            token = signing.loads(request.POST.get('review_token', ''), salt=SALT, max_age=600)
            if (not isinstance(token, dict) or token.get('actor') != str(request.user.pk)
                    or token.get('account') != account or token.get('key') != key
                    or request.POST.get('confirm_absent') != 'yes'):
                raise ValueError('PROVIDER_CONFIRMATION_REQUIRED')
            context['result'] = execute(request.user, account, key, token['nonce'], token['fingerprint'])
        except (signing.BadSignature, KeyError, ValueError):
            context['error'] = 'Подтверждение устарело или условия изменились. Проверьте сведения ниже и подтвердите заново.'
            status = 409
        except DependencyGuardBlocked:
            raise PermissionDenied
        except ValidationError:
            context['error'] = 'NetBox отклонил создание карточки. Изменения этой операции отменены; проверьте размещение и ограничения полей.'
            status = 409
    if not context.get('result'):
        try:
            preview = review(request.user, account, key)
        except DependencyGuardBlocked:
            raise PermissionDenied
        except ValueError:
            context['error'] = 'Проверка недоступна. Нужны включённый импорт карточек, полный доступ к инвентарю и актуальные сведения аккаунта.'
            status = 409
        else:
            context['preview'] = preview
            context['reason'] = REASONS.get(preview['reason'], 'Создание недоступно: сначала разберите результат сопоставления этого ресурса.')
            if preview['eligible']:
                context['review_token'] = signing.dumps(dict(actor=str(request.user.pk), account=account, key=key,
                    nonce=str(uuid4()), fingerprint=preview['fingerprint']), salt=SALT)
    return render(request, 'netbox_guard/provider_first_creation.html', context, status=status)
