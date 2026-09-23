"""Atomic whole-source retirement inside the same certified NetBox DB fence.

A source-created cluster is removed last. An unclaimed placement cluster is kept.
Any other unclaimed/foreign scoped object blocks the whole transaction. This is
not a query-by-name cleanup and never infers intent from inventory disappearance.
"""
import time
from uuid import UUID
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from .dependencies import (MODELS, MAX_OBJECTS, DependencySnapshot, DependencyGuardBlocked,
                           _database_fence, _closure, _digest)
from .models import CreationClaim, RetirementIntent, RetirementReceipt
from .service import _permission, _source, _claims, _cluster_fingerprint

BUDGET_SECONDS = 30


def _deadline(deadline):
    if time.monotonic() >= deadline:
        raise DependencyGuardBlocked('RETIREMENT_DEADLINE')


def _inventory(source, cluster, deadline):
    """Complete bounded scope from real FK/GFK relations, never name matching."""
    objects = {}
    ids = {}
    def read(kind, query):
        _deadline(deadline)
        rows = apps.get_model(MODELS[kind]).objects.filter(query).order_by('pk')[:MAX_OBJECTS+1]
        ids[kind] = []
        for obj in rows:
            _deadline(deadline)
            ids[kind].append(obj.pk)
            values = {field.attname:getattr(obj,field.attname) for field in obj._meta.concrete_fields}
            objects[f'{kind}:{obj.pk}'] = _digest(values)
            if len(objects)>MAX_OBJECTS:
                raise DependencyGuardBlocked('DEPENDENCY_LIMIT')
    read('device',Q(cluster_id=cluster))
    read('vm',Q(cluster_id=cluster)|Q(device_id__in=ids['device']))
    read('interface',Q(device_id__in=ids['device']))
    read('vminterface',Q(virtual_machine_id__in=ids['vm']))
    read('disk',Q(virtual_machine_id__in=ids['vm']))
    assignment=Q(pk__in=[])
    for kind in ('interface','vminterface'):
        ct=ContentType.objects.get_for_model(apps.get_model(MODELS[kind]))
        assignment |= Q(assigned_object_type_id=ct.pk,assigned_object_id__in=ids[kind])
    read('ip',assignment);read('mac',assignment)
    # A manually selected/shared placement is not a creation claim.
    if CreationClaim.objects.filter(resource='cluster',object_id=cluster).exists():
        read('cluster',Q(pk=cluster))
    else:
        ids['cluster']=[]
    claims=CreationClaim.objects.filter(source_instance=source).values_list('resource','object_id','cluster_id')[:MAX_OBJECTS+1]
    for kind,identifier,placement in claims:
        _deadline(deadline)
        if placement!=cluster or f'{kind}:{identifier}' not in objects:
            raise DependencyGuardBlocked('OWNED_OBJECT_OUTSIDE_PLACEMENT')
    rows=tuple(sorted(objects.items()))
    snapshot=DependencySnapshot(rows,(),_digest(rows))
    _claims(snapshot,source,cluster,lambda:_deadline(deadline))
    _deadline(deadline)
    roots=[['vm',pk] for pk in ids['vm']]+[['device',pk] for pk in ids['device']]+[['cluster',pk] for pk in ids['cluster']]
    return snapshot,roots


def review_source(user, nonce, source, cluster):
    actor=_permission(user,'retire_retirementintent')
    source=_source(source);nonce=UUID(str(nonce))
    if type(cluster) is not int or cluster<=0:
        raise DependencyGuardBlocked('INVALID_PLACEMENT')
    def existing(row):
        _permission(user,'retire_retirementintent',row)
        if (row.actor!=actor or row.source_instance!=source or row.manifest.get('format')!=2
                or row.manifest.get('cluster_id')!=cluster):
            raise DependencyGuardBlocked('REQUEST_CONFLICT')
        return row
    previous=RetirementIntent.objects.filter(nonce=nonce).first()
    if previous: return existing(previous)
    deadline=time.monotonic()+BUDGET_SECONDS
    with _database_fence():
        previous=RetirementIntent.objects.filter(nonce=nonce).first()
        if previous: return existing(previous)
        snapshot,roots=_inventory(source,cluster,deadline)
        manifest={'format':2,'cluster_id':cluster,'cluster_fingerprint':_cluster_fingerprint(cluster),
                  'objects':[list(row) for row in snapshot.objects], 'roots':roots,
                  'fingerprint':snapshot.fingerprint,'retained_cluster':not any(root[0]=='cluster' for root in roots)}
        intent=RetirementIntent.objects.create(nonce=nonce,actor=actor,source_instance=source,
            manifest=manifest,digest=_digest([actor,source,manifest]))
        _permission(user,'retire_retirementintent',intent)
        _deadline(deadline)
        return intent


def retire_source(user, nonce, digest):
    actor=_permission(user,'retire_retirementintent')
    intent=RetirementIntent.objects.get(nonce=UUID(str(nonce)))
    _permission(user,'retire_retirementintent',intent)
    manifest=intent.manifest
    if (intent.actor!=actor or intent.digest!=digest or manifest.get('format')!=2
            or _digest([actor,intent.source_instance,manifest])!=digest):
        raise DependencyGuardBlocked('REQUEST_CONFLICT')
    deadline=time.monotonic()+BUDGET_SECONDS
    with _database_fence():
        _permission(user,'retire_retirementintent',intent)
        previous=RetirementReceipt.objects.filter(intent=intent).first()
        if previous:
            if previous.digest!=digest: raise DependencyGuardBlocked('RECEIPT_CONFLICT')
            return previous
        snapshot,roots=_inventory(intent.source_instance,manifest['cluster_id'],deadline)
        if (list(map(list,snapshot.objects))!=manifest['objects'] or roots!=manifest['roots']
                or snapshot.fingerprint!=manifest['fingerprint']):
            raise DependencyGuardBlocked('DEPENDENCIES_CHANGED')
        if _cluster_fingerprint(manifest['cluster_id'])!=manifest['cluster_fingerprint']:
            raise DependencyGuardBlocked('PLACEMENT_CHANGED')
        remaining=dict(snapshot.objects)
        deleted=[]
        for root in roots:
            _deadline(deadline)
            current,collector=_closure([root])
            # The actual deletion cascade must be a subset of exactly what was
            # reviewed. Any external SET_NULL/unknown relation already refuses.
            if any(remaining.get(key)!=value for key,value in current.objects):
                raise DependencyGuardBlocked('DEPENDENCIES_CHANGED')
            _claims(current,intent.source_instance,manifest['cluster_id'],lambda:_deadline(deadline))
            expected={}
            for key,_ in current.objects:
                label=MODELS[key.split(':')[0]]
                expected[label]=expected.get(label,0)+1
            count,actual=collector.delete()
            if actual!=expected or count!=len(current.objects):
                raise DependencyGuardBlocked('DELETE_EFFECT_MISMATCH')
            for key,_ in current.objects:
                remaining.pop(key);deleted.append(key)
        _deadline(deadline)
        if remaining: raise DependencyGuardBlocked('DELETE_EFFECT_MISMATCH')
        # All phases and the final receipt commit together. Mid-phase failure or
        # process/DB rollback cannot leave a committed partial source retirement.
        return RetirementReceipt.objects.create(intent=intent,digest=digest,deleted=sorted(deleted))
