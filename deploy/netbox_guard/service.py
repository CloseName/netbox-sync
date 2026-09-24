"""Guard service primitives; no production route is installed by Sync.

The Sync-side coordinator must additionally hold its shared lock/source gate and
validate removal intent, registry revision and unfinished operations. These methods
never infer a removal intention from an absent source, name or network address.
"""
import re
from uuid import UUID
from django.apps import apps
from django.db import connection, transaction
from .dependencies import MODELS, DependencySnapshot, DependencyGuardBlocked, _digest, _locked_closure
from .models import CreationClaim, CreationReceipt, RetirementIntent, RetirementReceipt


def _permission(user, action, obj=None):
    if not user.is_authenticated:
        raise DependencyGuardBlocked('PERMISSION_DENIED')
    user = type(user).objects.get(pk=user.pk)
    if not user.has_perm('netbox_guard.' + action, obj):
        raise DependencyGuardBlocked('PERMISSION_DENIED')
    return str(user.pk)


def _add_permission(user, obj):
    user = type(user).objects.get(pk=user.pk)
    permission = f'{obj._meta.app_label}.add_{obj._meta.model_name}'
    if not user.has_perm(permission, obj):
        raise DependencyGuardBlocked('PERMISSION_DENIED')


def _source(source):
    if not isinstance(source, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,127}', source):
        raise DependencyGuardBlocked('INVALID_SOURCE')
    return source


def _scope(resource, obj):
    if resource == 'cluster':
        return obj.pk
    if resource in ('vm', 'device'):
        return obj.cluster_id
    if resource == 'interface':
        return obj.device.cluster_id
    if resource in ('vminterface', 'disk'):
        return obj.virtual_machine.cluster_id
    if resource in ('ip', 'mac'):
        parent = obj.assigned_object
        if parent is not None:
            kind = next((kind for kind in ('interface', 'vminterface')
                         if parent._meta.label_lower == MODELS[kind].lower()), None)
            if kind:
                return _scope(kind, parent)
    raise DependencyGuardBlocked('PLACEMENT_UNPROVEN')


def _owners(obj, source):
    records = getattr(obj, 'custom_field_data', {}).get('sync_identities', [])
    # NetBox fills optional JSON custom fields with null on newly created
    # physical interfaces. Absence is not provenance; the exact creation claim
    # and parent ownership checks below remain mandatory for retirement.
    if records is None:records=[]
    if not isinstance(records, list):
        raise DependencyGuardBlocked('OWNERSHIP_CONFLICT')
    for record in records:
        if (not isinstance(record, dict) or record.get('schema') != 'v2'
                or record.get('instance') != source
                or record.get('type') not in ('esxi', 'proxmox')
                or any(not isinstance(record.get(key), str) or not record[key].strip()
                       for key in ('kind', 'external_id'))):
            raise DependencyGuardBlocked('OWNERSHIP_CONFLICT')


def _parent_owner(resource, obj, source):
    parent = None
    if resource == 'vm': parent = obj.device
    elif resource == 'interface': parent = obj.device
    elif resource in ('vminterface','disk'): parent = obj.virtual_machine
    elif resource in ('ip','mac'): parent = obj.assigned_object
    if parent is None:
        if resource in ('ip','mac'): raise DependencyGuardBlocked('OWNERSHIP_CONFLICT')
        return
    kind = next((kind for kind,label in MODELS.items() if label.lower()==parent._meta.label_lower),None)
    if kind is None: raise DependencyGuardBlocked('OWNERSHIP_CONFLICT')
    _owners(parent,source)
    claim = CreationClaim.objects.filter(resource=kind,object_id=parent.pk).first()
    if claim is not None:
        if claim.source_instance!=source or claim.object_created!=parent.created:
            raise DependencyGuardBlocked('OWNERSHIP_CONFLICT')
        return
    # A retained/adopted parent may be managed by this source without being ours
    # to delete. Empty/manual/foreign provenance does not authorize attachment.
    identities = getattr(parent,'custom_field_data',{}).get('sync_identities',[])
    if not identities: raise DependencyGuardBlocked('OWNERSHIP_CONFLICT')


def _claims(snapshot, source, cluster, check_budget=None):
    for key, _ in snapshot.objects:
        if check_budget is not None: check_budget()
        resource, identifier = key.split(':')
        claim = CreationClaim.objects.filter(resource=resource, object_id=int(identifier)).first()
        if claim is None or claim.source_instance != source or claim.cluster_id != cluster:
            raise DependencyGuardBlocked('CREATION_OWNERSHIP_UNPROVEN')
        obj = apps.get_model(MODELS[resource]).objects.get(pk=identifier)
        if obj.created != claim.object_created:
            raise DependencyGuardBlocked('OBJECT_GENERATION_CHANGED')
        if _scope(resource, obj) != cluster:
            raise DependencyGuardBlocked('PLACEMENT_CHANGED')
        _owners(obj, source)
        _parent_owner(resource, obj, source)


def _creation_value(value):
    from django.db.models import Model
    from decimal import Decimal
    from netaddr import IPNetwork, IPAddress, EUI
    from ipaddress import IPv4Address, IPv6Address, IPv4Interface, IPv6Interface
    import math
    if isinstance(value, Model):
        if not value.pk:
            raise DependencyGuardBlocked('UNSAVED_REFERENCE')
        return {'model': value._meta.label_lower, 'id': value.pk}
    if isinstance(value, dict):
        return {key: _creation_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_creation_value(item) for item in value]
    if isinstance(value, Decimal):
        if not value.is_finite(): raise DependencyGuardBlocked('INVALID_CREATE_VALUE')
        return {'decimal': str(value)}
    if isinstance(value, (IPNetwork, IPAddress, EUI, IPv4Address, IPv6Address, IPv4Interface, IPv6Interface)):
        return {'network_value': str(value)}
    if type(value) is float and not math.isfinite(value):
        raise DependencyGuardBlocked('INVALID_CREATE_VALUE')
    if value is None or type(value) in (str, int, bool, float):
        return value
    raise DependencyGuardBlocked('INVALID_CREATE_VALUE')


def create_owned(user, nonce, source, resource, values, *, cluster=None, request_digest=None):
    """Atomic CREATE + claim + receipt. No adoption/update of an existing ID.

    This is an internal service method, not an arbitrary browser payload schema.
    Any future HTTP adapter must enforce fixed serializers and object permissions.
    """
    actor = _permission(user, 'create_creationreceipt')
    source = _source(source); nonce = UUID(str(nonce))
    if resource not in MODELS or not isinstance(values, dict) or any(k in values for k in ('pk','id')):
        raise DependencyGuardBlocked('INVALID_CREATE')
    if resource == 'cluster' and cluster is not None:
        raise DependencyGuardBlocked('INVALID_CREATE')
    if request_digest is not None and (not isinstance(request_digest,str) or not re.fullmatch('[a-f0-9]{64}',request_digest)):
        raise DependencyGuardBlocked('INVALID_CREATE')
    # The authenticated transport hashes its exact validated wire request. This
    # remains stable across a retry even when serializer defaults/uniqueness checks
    # now observe the newly created object. Internal callers hash model values.
    payload = {'wire':request_digest} if request_digest is not None else _creation_value(values)
    digest = _digest([source, resource, payload, cluster])
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '2000ms'")
            cursor.execute("SET LOCAL statement_timeout = '10000ms'")
            cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ['netbox-sync-create:' + str(nonce)])
        receipt = CreationReceipt.objects.filter(nonce=nonce).first()
        if receipt:
            _permission(user, 'create_creationreceipt', receipt)
            if (receipt.actor, receipt.digest) != (actor, digest):
                raise DependencyGuardBlocked('REQUEST_CONFLICT')
            obj = apps.get_model(MODELS[receipt.resource]).objects.filter(pk=receipt.object_id).first()
            claim = CreationClaim.objects.filter(resource=resource, object_id=receipt.object_id, source_instance=source).first()
            if obj is None or claim is None or obj.created != claim.object_created:
                raise DependencyGuardBlocked('CREATED_OBJECT_NO_LONGER_OWNED')
            if resource != 'cluster' and _scope(resource, obj) != cluster:
                raise DependencyGuardBlocked('PLACEMENT_CHANGED')
            _owners(obj, source)
            _parent_owner(resource, obj, source)
            _add_permission(user, obj)
            return obj
        obj = apps.get_model(MODELS[resource])(**values)
        _owners(obj, source)
        obj.full_clean(); obj.save()
        _add_permission(user, obj)
        _parent_owner(resource, obj, source)
        actual_cluster = _scope(resource, obj)
        if resource != 'cluster' and (type(cluster) is not int or cluster != actual_cluster):
            raise DependencyGuardBlocked('PLACEMENT_CHANGED')
        CreationClaim.objects.create(resource=resource, object_id=obj.pk, source_instance=source, cluster_id=actual_cluster, object_created=obj.created)
        receipt = CreationReceipt.objects.create(nonce=nonce, actor=actor, source_instance=source,
                                       resource=resource, object_id=obj.pk, digest=digest)
        _permission(user, 'create_creationreceipt', receipt)
        return obj


def read_created(user, nonce):
    """Read an existing creation proof; never create or retry a mutation."""
    actor = _permission(user, 'create_creationreceipt')
    with transaction.atomic():
        receipt = CreationReceipt.objects.filter(nonce=UUID(str(nonce))).first()
        if receipt is None:
            raise DependencyGuardBlocked('REQUEST_NOT_FOUND')
        _permission(user, 'create_creationreceipt', receipt)
        if receipt.actor != actor:
            raise DependencyGuardBlocked('PERMISSION_DENIED')
        obj = apps.get_model(MODELS[receipt.resource]).objects.filter(pk=receipt.object_id).first()
        claim = CreationClaim.objects.filter(resource=receipt.resource, object_id=receipt.object_id,
                                             source_instance=receipt.source_instance).first()
        if obj is None or claim is None or obj.created != claim.object_created:
            raise DependencyGuardBlocked('CREATED_OBJECT_NO_LONGER_OWNED')
        if _scope(receipt.resource, obj) != claim.cluster_id:
            raise DependencyGuardBlocked('PLACEMENT_CHANGED')
        _owners(obj, receipt.source_instance)
        _parent_owner(receipt.resource, obj, receipt.source_instance)
        _add_permission(user, obj)
        return receipt, obj


def _cluster_fingerprint(cluster):
    obj = apps.get_model(MODELS['cluster']).objects.filter(pk=cluster).first()
    if obj is None:
        raise DependencyGuardBlocked('OBJECT_MISSING')
    return _digest({field.attname: getattr(obj, field.attname) for field in obj._meta.concrete_fields})


def review(user, nonce, source, cluster, *, root=None):
    if type(cluster) is not int or cluster <= 0:
        raise DependencyGuardBlocked('INVALID_PLACEMENT')
    actor = _permission(user, 'retire_retirementintent')
    source = _source(source); nonce = UUID(str(nonce))
    root = root or ('cluster', cluster)
    previous = RetirementIntent.objects.filter(nonce=nonce).first()
    def existing(row):
        if (row.actor != actor or row.source_instance != source
                or row.manifest.get('cluster_id') != cluster or row.manifest.get('roots') != [list(root)]):
            raise DependencyGuardBlocked('REQUEST_CONFLICT')
        _permission(user, 'retire_retirementintent', row)
        return row
    if previous:
        return existing(previous)
    with _locked_closure([root]) as (snapshot, _collector):
        _claims(snapshot, source, cluster)
        manifest = {'format': 1, 'cluster_id': cluster, 'cluster_fingerprint': _cluster_fingerprint(cluster), 'roots': [list(root)],
                    'objects': [list(row) for row in snapshot.objects],
                    'field_updates': [list(row) for row in snapshot.field_updates],
                    'fingerprint': snapshot.fingerprint}
        digest = _digest([actor, source, manifest])
        previous = RetirementIntent.objects.filter(nonce=nonce).first()
        if previous:
            return existing(previous)
        intent = RetirementIntent.objects.create(nonce=nonce, actor=actor, source_instance=source,
                                               manifest=manifest, digest=digest)
        _permission(user, 'retire_retirementintent', intent)
        return intent


def retire(user, nonce, digest):
    actor = _permission(user, 'retire_retirementintent')
    intent = RetirementIntent.objects.get(nonce=UUID(str(nonce)))
    _permission(user, 'retire_retirementintent', intent)
    if intent.manifest.get('format') != 1 or intent.actor != actor or intent.digest != digest:
        raise DependencyGuardBlocked('REQUEST_CONFLICT')
    def receipt():
        found = RetirementReceipt.objects.filter(intent=intent).first()
        if found and found.digest != digest:
            raise DependencyGuardBlocked('RECEIPT_CONFLICT')
        return found
    previous = receipt()
    if previous:
        return previous
    manifest = intent.manifest
    if _digest([actor, intent.source_instance, manifest]) != digest:
        raise DependencyGuardBlocked('MANIFEST_CORRUPT')
    snapshot = DependencySnapshot(tuple(map(tuple, manifest['objects'])),
                                  tuple(map(tuple, manifest['field_updates'])), manifest['fingerprint'])
    try:
        with _locked_closure(manifest['roots'], expected=snapshot) as (current, collector):
            _permission(user, 'retire_retirementintent', intent)
            if _cluster_fingerprint(manifest['cluster_id']) != manifest['cluster_fingerprint']:
                raise DependencyGuardBlocked('PLACEMENT_CHANGED')
            _claims(current, intent.source_instance, manifest['cluster_id'])
            expected_counts = {}
            for key, _ in current.objects:
                resource = key.split(':')[0]
                label = MODELS[resource]
                expected_counts[label] = expected_counts.get(label, 0) + 1
            count, actual = collector.delete()
            if actual != expected_counts or count != len(current.objects):
                raise DependencyGuardBlocked('DELETE_EFFECT_MISMATCH')
            # Receipt and deletion commit together, including claim invalidation.
            return RetirementReceipt.objects.create(intent=intent, digest=digest,
                                                     deleted=[key for key, _ in current.objects])
    except DependencyGuardBlocked as exc:
        # Another identical request may have completed before our table locks.
        if str(exc) == 'OBJECT_MISSING':
            previous = receipt()
            if previous:
                return previous
        raise


def audit_source(user, nonce, source):
    """Journal a scope-checked audit; never modify infrastructure objects.

    Reuses the existing persisted-intent permission boundary. This audit intent
    cannot be passed to either retirement executor.
    """
    from django.db.models import Q
    _source(source)
    try:actor = _permission(user, 'audit_retirementintent')
    except DependencyGuardBlocked:raise DependencyGuardBlocked('GUARD_AUDIT_PERMISSION_REQUIRED') from None
    nonce = UUID(str(nonce))
    with transaction.atomic():
        intent, _created = RetirementIntent.objects.get_or_create(nonce=nonce, defaults={
            'actor':actor, 'source_instance':source, 'manifest':{'format':3,'purpose':'AUDIT_ONLY'},
            'digest':_digest([actor,source,{'format':3,'purpose':'AUDIT_ONLY'}])})
        try:_permission(user, 'audit_retirementintent', intent)
        except DependencyGuardBlocked:raise DependencyGuardBlocked('GUARD_SOURCE_SCOPE_DENIED') from None
        if (intent.actor != actor or intent.source_instance != source or intent.manifest != {'format':3,'purpose':'AUDIT_ONLY'}):
            raise DependencyGuardBlocked('REQUEST_CONFLICT')
    user=type(user).objects.get(pk=user.pk)
    rows=[]
    with transaction.atomic():
        claims=list(CreationClaim.objects.filter(source_instance=source).order_by('resource','object_id')[:10001])
        if len(claims)>10000:raise DependencyGuardBlocked('DEPENDENCY_LIMIT')
        indexed={(claim.resource,claim.object_id):claim for claim in claims}
        seen=set()
        for kind,label in MODELS.items():
            model=apps.get_model(label)
            objects=model.objects.filter(Q(pk__in=[claim.object_id for claim in claims if claim.resource==kind])|Q(custom_field_data__sync_identities__contains=[{'instance':source}])).order_by('pk')
            for obj in objects[:10001]:
                if not user.has_perm(f'{obj._meta.app_label}.view_{obj._meta.model_name}',obj):
                    raise DependencyGuardBlocked('GUARD_OBJECT_VIEW_DENIED')
                seen.add((kind,obj.pk));claim=indexed.get((kind,obj.pk))
                rows.append({'kind':kind,'id':obj.pk,'present':True,'claimed':bool(claim and claim.object_created==obj.created),
                    'fingerprint':_digest({field.attname:getattr(obj,field.attname) for field in obj._meta.concrete_fields})})
                if len(rows)>10000:raise DependencyGuardBlocked('DEPENDENCY_LIMIT')
        for key,claim in indexed.items():
            if key not in seen:rows.append({'kind':key[0],'id':key[1],'present':False,'claimed':True,'fingerprint':_digest(str(claim.object_created))})
        if len(rows)>10000:raise DependencyGuardBlocked('DEPENDENCY_LIMIT')
    result={'source_instance':source,'objects':sorted(rows,key=lambda row:(row['kind'],row['id'])),
            'historical_outcome':'UNPROVED','legacy_unattributed_objects':'NOT_PROVEN'}
    result['digest']=_digest(result)
    return result
