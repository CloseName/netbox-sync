"""Atomic replacement of a creation-proven, unconnected VM generation.

The caller must hold the source gate and rediscover the complete source before
execution. Name reuse is only a candidate; this service independently fences
creation provenance, dependencies, placement and the exact reviewed generation.
"""
from uuid import UUID
from django.apps import apps
from .dependencies import _database_fence, _closure, _digest, DependencyGuardBlocked
from .models import CreationClaim, CreationReceipt, SourceClosure
from .service import _claims, _permission, _source


def _evidence(user, identifier, source, cluster):
    vm = apps.get_model('virtualization.VirtualMachine').objects.get(pk=identifier)
    if not user.has_perm('virtualization.view_virtualmachine', vm):
        raise DependencyGuardBlocked('PERMISSION_DENIED')
    snapshot, _ = _closure([('vm', identifier)])
    _claims(snapshot, source, cluster)
    identities = (vm.custom_field_data or {}).get('sync_identities') or []
    if (len(identities) != 1 or identities[0].get('type') != 'esxi'
            or identities[0].get('kind') != 'vm' or vm.cluster_id != cluster
            or SourceClosure.objects.filter(source_instance=source).exists()):
        raise DependencyGuardBlocked('OWNERSHIP_CONFLICT')
    # A connected firewall's credentials can live on Sync, outside the DB closure.
    names = [vm.name, *(((vm.custom_field_data or {}).get('sync_original_names') or {}).values())]
    if any('pfsense' in str(name).casefold() for name in names) or vm.primary_ip4_id or vm.primary_ip6_id:
        raise DependencyGuardBlocked('PROTECTED_DEPENDENCY')
    allowed = {'vm', 'vminterface', 'disk', 'mac'}
    from .dependencies import MODELS
    for key, _ in snapshot.objects:
        kind, pk = key.split(':')
        if kind not in allowed:
            raise DependencyGuardBlocked('PROTECTED_DEPENDENCY')
        obj = apps.get_model(MODELS[kind]).objects.get(pk=pk)
        if not user.has_perm(f'{obj._meta.app_label}.view_{obj._meta.model_name}', obj):
            raise DependencyGuardBlocked('PERMISSION_DENIED')
        # Provider, firewall and manual custom fields are not silently inherited.
        if any(v not in (None, '', [], {}) for k, v in (obj.custom_field_data or {}).items()
               if k not in ('sync_identities', 'sync_original_names')):
            raise DependencyGuardBlocked('PROTECTED_DEPENDENCY')
        if kind != 'vm' and (getattr(obj, 'description', '') or getattr(obj, 'comments', '')
                             or (hasattr(obj, 'tags') and obj.tags.exists())):
            raise DependencyGuardBlocked('PROTECTED_DEPENDENCY')
    children = [key.split(':') for key, _ in snapshot.objects if key != f'vm:{identifier}']
    return vm, dict(fingerprint=snapshot.fingerprint, old_identity=identities[0],
                   children=[[kind, int(pk)] for kind, pk in children])


def review(user, identifier, source, cluster):
    _source(source)
    with _database_fence():
        _, evidence = _evidence(user, identifier, source, cluster)
        return evidence


def execute(user, identifier, source, cluster, nonce, expected, new_identity, name):
    _source(source)
    actor = _permission(user, 'create_creationreceipt')
    try:
        nonce = UUID(str(nonce))
    except ValueError:
        raise DependencyGuardBlocked('REQUEST_INVALID') from None
    if type(cluster) is not int or cluster <= 0:
        raise DependencyGuardBlocked('REQUEST_INVALID')
    if (not isinstance(expected, dict) or not isinstance(new_identity, dict)
            or set(new_identity) != {'schema', 'type', 'instance', 'kind', 'external_id'}
            or new_identity.get('schema') != 'v2' or new_identity.get('type') != 'esxi'
            or new_identity.get('instance') != source or new_identity.get('kind') != 'vm'
            or not isinstance(new_identity.get('external_id'), str)
            or not 1 <= len(new_identity['external_id']) <= 256
            or not isinstance(name, str) or not 1 <= len(name) <= 64):
        raise DependencyGuardBlocked('REQUEST_INVALID')
    digest = _digest([identifier, source, cluster, expected, new_identity, name])
    with _database_fence():
        prior = CreationReceipt.objects.filter(nonce=nonce).first()
        if prior:
            if (prior.resource != 'vm-replacement' or prior.digest != digest
                    or prior.actor != actor or prior.object_id != identifier):
                raise DependencyGuardBlocked('REQUEST_CONFLICT')
            _permission(user, 'create_creationreceipt', prior)
            vm = apps.get_model('virtualization.VirtualMachine').objects.filter(pk=identifier).first()
            claim = CreationClaim.objects.filter(resource='vm', object_id=identifier,
                source_instance=source, cluster_id=cluster).first()
            if (vm is None or claim is None or vm.created != claim.object_created
                    or vm.cluster_id != cluster or (vm.custom_field_data or {}).get('sync_identities') != [new_identity]
                    or SourceClosure.objects.filter(source_instance=source).exists()
                    or not user.has_perm('virtualization.change_virtualmachine', vm)):
                raise DependencyGuardBlocked('OBJECT_GENERATION_CHANGED')
            return {'id': identifier, 'replayed': True}
        vm, current = _evidence(user, identifier, source, cluster)
        if current != expected:
            raise DependencyGuardBlocked('DEPENDENCIES_CHANGED')
        if (new_identity == current['old_identity'] or vm.name.casefold() != name.casefold()
                or not user.has_perm('virtualization.change_virtualmachine', vm)):
            raise DependencyGuardBlocked('OWNERSHIP_CONFLICT')
        if type(vm).objects.filter(custom_field_data__sync_identities__contains=[new_identity]).exists():
            raise DependencyGuardBlocked('OWNERSHIP_CONFLICT')
        roots = [tuple(row) for row in current['children']]
        if roots:
            child_snapshot, collector = _closure(roots)
            if {key for key, _ in child_snapshot.objects} != {f'{kind}:{pk}' for kind, pk in roots}:
                raise DependencyGuardBlocked('PROTECTED_DEPENDENCY')
            _claims(child_snapshot, source, cluster)
            # This narrow operation can remove only creation-proven unconnected
            # children of the replacement card, never arbitrary object IDs.
            collector.delete()
        vm.custom_field_data = {**vm.custom_field_data, 'sync_identities': [new_identity],
            'sync_original_names': {f'esxi/{source}/vm': name}}
        vm.name = name
        vm.full_clean()
        vm.save()
        receipt = CreationReceipt.objects.create(nonce=nonce, actor=actor, source_instance=source,
            resource='vm-replacement', object_id=identifier, digest=digest)
        _permission(user, 'create_creationreceipt', receipt)
        return {'id': identifier, 'replayed': False}
