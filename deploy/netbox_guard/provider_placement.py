"""Account-scoped placement keyed by provider identifiers, not display labels."""
from dcim.models import Site, Region
from .models import ProviderCreatedObject
from .provider_policy import digest
from .service import _add_permission
from .dependencies import DependencyGuardBlocked


def resolve(user, snapshot, previous=None):
    ident = snapshot['identity']
    section = snapshot['sections'].get('placement', {})
    data = section.get('data')
    if section.get('status') != 'collected' or section.get('retained') or not isinstance(data, dict):
        return None
    location = data.get('uuid') or data.get('OS-EXT-AZ:availability_zone')
    label = data.get('name') or data.get('OS-EXT-AZ:availability_zone')
    if not isinstance(location, str) or not location or not isinstance(label, str) or not label:
        return None
    account, region_id = ident['account'], ident.get('region') or ''
    def ensure(model, key, values, legacy_slug):
        marker = 'placement:' + digest(key)
        proofs = list(ProviderCreatedObject.objects.filter(account=account, model_label=model._meta.label_lower,
                                                           provider_key=marker))
        if len(proofs) > 1: raise ValueError('PROVIDER_PLACEMENT_CONFLICT')
        result = model.objects.filter(pk=proofs[0].object_id).first() if proofs else None
        if proofs and (result is None or result.created != proofs[0].object_created):
            raise ValueError('PROVIDER_PLACEMENT_IDENTITY_CHANGED')
        if result is None:
            legacy = model.objects.filter(slug=legacy_slug).first()
            proof = ProviderCreatedObject.objects.filter(account=account, model_label=model._meta.label_lower,
                object_id=legacy.pk, object_created=legacy.created, provider_key='').first() if legacy else None
            if proof:
                result=legacy; proof.provider_key=marker; proof.save(update_fields=['provider_key'])
            else:
                result=model(slug='selectel-'+digest(key)[:24], **values)
                _add_permission(user,result); result.full_clean(); result.save()
                ProviderCreatedObject.objects.create(account=account,model_label=model._meta.label_lower,
                    object_id=result.pk,object_created=result.created,provider_key=marker)
        changed = [field for field,value in values.items() if getattr(result,field) != value]
        if changed:
            if not user.has_perm(f'{model._meta.app_label}.change_{model._meta.model_name}',result):
                raise DependencyGuardBlocked('PERMISSION_DENIED')
            for field in changed: setattr(result,field,values[field])
            result.full_clean(); result.save(update_fields=changed+['last_updated'])
        return result
    legacy_label = label
    if isinstance(previous, dict) and previous.get('identity', {}).get('region', '') == region_id:
        old_data = previous.get('sections', {}).get('placement', {}).get('data') or {}
        if isinstance(old_data, dict) and (old_data.get('uuid') or old_data.get('OS-EXT-AZ:availability_zone')) == location:
            legacy_label = old_data.get('name') or old_data.get('OS-EXT-AZ:availability_zone') or label
    old_scope = digest([account, region_id or legacy_label])[:16]
    region = ensure(Region,[account,'region',region_id],{'name':f'Selectel / {account} / {region_id}'[:100]},
                    'selectel-'+old_scope) if region_id else None
    return ensure(Site,[account,'site',region_id,location],
                  {'name':f'Selectel / {account} / {label}'[:100],'region':region},
                  'selectel-'+digest([old_scope,legacy_label])[:16])
