"""Additive account/project tenancy; existing resource tenancy is never replaced."""
from tenancy.models import Tenant, TenantGroup
from .models import ProviderCreatedObject, ProviderResourceRegistry
from .provider_policy import digest
from .provider_creation import create_native
from .validation_detail import checked
from .dependencies import DependencyGuardBlocked


def resolve(user, identity, routing=False):
    account, project = identity['account'], identity.get('project') or ''
    def ensure(model, key, fields):
        slug = 'selectel-' + digest(key)[:24]
        matches = list(model.objects.filter(slug=slug))
        if matches:
            result = matches[0]
            if not user.has_perm(f'{model._meta.app_label}.view_{model._meta.model_name}', result):
                raise DependencyGuardBlocked('PERMISSION_DENIED')
            if (model is Tenant and fields['name'] == 'Общие ресурсы аккаунта' and
                    result.name == 'Без проекта / уровень аккаунта' and
                    ProviderCreatedObject.objects.filter(account=account, model_label='tenancy.tenant',
                        object_id=result.pk, object_created=result.created,
                        provider_key='tenancy:' + digest(key)).exists()):
                if not user.has_perm('tenancy.change_tenant', result):
                    raise DependencyGuardBlocked('PERMISSION_DENIED')
                result.name = fields['name']
                checked(result, 'full_clean')
                checked(result, 'save', update_fields=['name', 'last_updated'])
            return result
        result = create_native(user, model(slug=slug, **fields))
        # The shared Selectel root outlives any one account. Child groups and
        # tenants retain provenance and are removed only when unused.
        if key != ['selectel']:
            ProviderCreatedObject.objects.create(account=account, model_label=model._meta.label_lower,
                object_id=result.pk, object_created=result.created, provider_key='tenancy:' + digest(key))
        return result
    root = ensure(TenantGroup, ['selectel'], dict(name='Selectel'))
    group = ensure(TenantGroup, ['selectel', account], dict(name='Аккаунт ' + account, parent=root))
    registry = ProviderResourceRegistry.objects.filter(pk=account).first()
    names = {}
    if registry:
        from .resource_tree import build_tree
        _, projects = build_tree(registry.snapshot['resources'].values())
        names = {p['id']: p['name'] for p in projects}
    if routing:
        legacy_key = ['selectel', account, '']
        if Tenant.objects.filter(slug='selectel-' + digest(legacy_key)[:24]).exists():
            ensure(Tenant, legacy_key, dict(name='Общие ресурсы аккаунта', group=group))
        return ensure(Tenant, ['selectel', account, 'routing', 'account'],
                      dict(name='Глобальный роутинг', group=group))
    name = (names.get(project) or project) if project else 'Общие ресурсы аккаунта'
    return ensure(Tenant, ['selectel', account, project], dict(name=name[:100], group=group))


def apply(user, target, identity):
    if target.tenant_id is not None:
        return
    tenant = resolve(user, identity)
    if not user.has_perm(f'{target._meta.app_label}.change_{target._meta.model_name}', target):
        raise DependencyGuardBlocked('PERMISSION_DENIED')
    target.tenant = tenant
    checked(target, 'full_clean')
    checked(target, 'save', update_fields=['tenant', 'last_updated'])
