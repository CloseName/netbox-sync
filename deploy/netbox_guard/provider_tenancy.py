"""Additive account/project tenancy; existing resource tenancy is never replaced."""
from tenancy.models import Tenant, TenantGroup
from .models import ProviderCreatedObject, ProviderResourceRegistry
from .provider_policy import digest
from .provider_creation import create_native
from .validation_detail import checked
from .dependencies import DependencyGuardBlocked


def resolve(user, identity):
    account, project = identity['account'], identity.get('project') or ''
    def ensure(model, key, fields):
        slug = 'selectel-' + digest(key)[:24]
        matches = list(model.objects.filter(slug=slug))
        if matches:
            result = matches[0]
            if not user.has_perm(f'{model._meta.app_label}.view_{model._meta.model_name}', result):
                raise DependencyGuardBlocked('PERMISSION_DENIED')
            return result
        result = create_native(user, model(slug=slug, **fields))
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
    name = names.get(project) or project or 'Общие ресурсы аккаунта'
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
