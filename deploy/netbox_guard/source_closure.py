"""Permanent namespace fence. Archive never grants ownership or deletes objects."""
from contextlib import contextmanager
from uuid import UUID,uuid5
from django.db import connection
from .models import SourceClosure,RetirementIntent,RetirementReceipt
from .dependencies import _database_fence,_digest,DependencyGuardBlocked
from .service import _permission,_source,audit_source

@contextmanager
def namespace_fence(source):
    # Taken BEFORE the independent DB dependency transaction. CREATE takes the
    # matching xact lock before touching infrastructure. Session unlock is bounded.
    key='netbox-sync-generation:'+source
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0))',[key])
        if not cursor.fetchone()[0]:raise DependencyGuardBlocked('SOURCE_NAMESPACE_BUSY')
    try:yield
    finally:
        with connection.cursor() as cursor:cursor.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',[key])

def assert_open(source):
    if SourceClosure.objects.filter(source_instance=source).exists():
        raise DependencyGuardBlocked('SOURCE_NAMESPACE_CLOSED')

def seal(intent):
    value,created=SourceClosure.objects.get_or_create(source_instance=intent.source_instance,defaults={'intent':intent})
    if not created and value.intent_id!=intent.pk:raise DependencyGuardBlocked('SOURCE_NAMESPACE_CLOSED')

def snapshot(user,nonce,source):
    return audit_source(user,uuid5(UUID(str(nonce)),'archive-current-inventory'),source)

def review_archive(user,nonce,source):
    actor=_permission(user,'retire_retirementintent');source=_source(source);nonce=UUID(str(nonce))
    with namespace_fence(source),_database_fence():
        prior=RetirementIntent.objects.filter(pk=nonce).first()
        if prior:
            _permission(user,'retire_retirementintent',prior)
            if (prior.actor,prior.source_instance,prior.manifest.get('format'))!=(actor,source,4):raise DependencyGuardBlocked('REQUEST_CONFLICT')
            return prior
        assert_open(source)
        evidence=snapshot(user,nonce,source)
        manifest={'format':4,'purpose':'LEGACY_RETAIN','objects':[], 'retained':evidence['objects'],
                  'inventory_digest':evidence['digest'],'historical_outcome':'UNPROVED','retained_cluster':True}
        intent=RetirementIntent.objects.create(nonce=nonce,actor=actor,source_instance=source,manifest=manifest,digest=_digest([actor,source,manifest]))
        _permission(user,'retire_retirementintent',intent)
        return intent

def archive_source(user,nonce,digest):
    actor=_permission(user,'retire_retirementintent')
    intent=RetirementIntent.objects.get(pk=UUID(str(nonce)))
    _permission(user,'retire_retirementintent',intent)
    if (intent.actor!=actor or intent.digest!=digest or intent.manifest.get('format')!=4
            or _digest([actor,intent.source_instance,intent.manifest])!=digest):raise DependencyGuardBlocked('REQUEST_CONFLICT')
    with namespace_fence(intent.source_instance),_database_fence():
        prior=RetirementReceipt.objects.filter(intent=intent).first()
        if prior:return prior
        assert_open(intent.source_instance)
        current=snapshot(user,nonce,intent.source_instance)
        if current['digest']!=intent.manifest['inventory_digest'] or current['objects']!=intent.manifest['retained']:
            raise DependencyGuardBlocked('DEPENDENCIES_CHANGED')
        seal(intent)
        return RetirementReceipt.objects.create(intent=intent,digest=digest,deleted=[])
