"""Account-scoped placement keyed by provider identifiers, not display labels."""
from .validation_detail import checked
from dcim.models import Site, Region
from .models import ProviderCreatedObject
from .provider_policy import digest
from .provider_creation import create_native
from .dependencies import DependencyGuardBlocked


def resolve(user, snapshot, previous=None, *, allow_updates=True):
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
            elif legacy is not None:
                # V1 created these deterministic slugs before provenance existed.
                # Reuse an exact reference, never infer ownership or rename it.
                if (ProviderCreatedObject.objects.filter(model_label=model._meta.label_lower,
                        object_id=legacy.pk).exists()
                        or any(getattr(legacy, field) != value for field, value in values.items())
                        or (model is Region and legacy.parent_id is not None)):
                    raise ValueError('PROVIDER_NATIVE_SCOPE_CONFLICT')
                if not user.has_perm(f'{model._meta.app_label}.view_{model._meta.model_name}', legacy):
                    raise DependencyGuardBlocked('PERMISSION_DENIED')
                return legacy
            else:
                result=model(slug='selectel-'+digest(key)[:24], **values)
                create_native(user, result)
                ProviderCreatedObject.objects.create(account=account,model_label=model._meta.label_lower,
                    object_id=result.pk,object_created=result.created,provider_key=marker)
        changed = [field for field,value in values.items() if getattr(result,field) != value]
        if changed:
            if not allow_updates:
                raise ValueError('PROVIDER_PLACEMENT_REVIEW_REQUIRED')
            if not user.has_perm(f'{model._meta.app_label}.change_{model._meta.model_name}',result):
                raise DependencyGuardBlocked('PERMISSION_DENIED')
            for field in changed: setattr(result,field,values[field])
            checked(result, 'full_clean'); checked(result, 'save', update_fields=changed+['last_updated'])
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
