"""Final source purge is exact, atomic, and never grants generic DELETE."""
from uuid import uuid4
from dataclasses import replace
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb
from tests.test_retirement_journal_postgres import coordinator, prepare, execute
from tests.test_source_lifecycle_postgres import lifecycle
from tests.test_migrations_postgres import migration_database
from netbox_sync.retirement_coordinator import RetirementCoordinator
from netbox_sync.source_lifecycle import LifecycleError

TABLES=('sources','source_operations','sync_runs','run_reconciliations','source_recoveries',
        'source_identity_verifications','registration_intents','host_reservations',
        'source_retirements','source_archives','source_tombstones','registration_jobs','source_removal_requests')


def test_full_purge_and_lost_final_response(coordinator):
    service,registry,config,remote,_=coordinator
    other=replace(config,id='preserved-other',source_instance='preserved-other',
        target=replace(config.target,cluster_name='separate'))
    registry.create_source(other)
    source,current,review=prepare(coordinator)
    with service.store.connect() as c:
        c.execute(sql.SQL('UPDATE {} SET value=value || %s WHERE id=1').format(service.store.table('auth_state')),
            (Jsonb({'source_teams':{'version':1,'revision':3,'teams':{'team':{'name':'Keep'}},'assignments':{source:'team',other.source_instance:'team'}}}),))
        for owner in (source,other.source_instance):
            c.execute(sql.SQL('INSERT INTO {} (event) VALUES (%s)').format(service.store.table('auth_audit')),(Jsonb({'source_instance':owner,'event':'fixture'}),))
    result=execute(service,source,current,review)
    assert result['state']=='FINALIZED' and result['purged'] is True
    assert registry.get_by_source_instance(source) is None
    assert registry.get_by_source_instance(other.source_instance).config==other
    with service.store.connect() as c:
        for table in TABLES:
            assert not c.execute(sql.SQL('SELECT 1 FROM {} WHERE source_instance=%s').format(service.store.table(table)),(source,)).fetchone(), table
        auth=c.execute(sql.SQL('SELECT value FROM {} WHERE id=1').format(service.store.table('auth_state'))).fetchone()['value']['source_teams']
        assert auth['assignments']=={other.source_instance:'team'} and auth['teams']=={'team':{'name':'Keep'}}
        assert auth['revision']==4
        assert len(c.execute(sql.SQL('SELECT * FROM {}').format(service.store.table('auth_audit'))).fetchall())==1
    restarted=RetirementCoordinator(service.store,remote,lambda _:pytest.fail('No second credential deletion'))
    assert execute(restarted,source,current,review)==result and remote.writes==1


def test_cleanup_failure_retains_durable_state_until_retry(coordinator):
    service,registry,_,remote,_=coordinator
    source,current,review=prepare(coordinator)
    original=remote.call
    def failing(action,*args,**kwargs):
        if action=='purge_local':raise LifecycleError('SOURCE_CREDENTIAL_CLEANUP_PENDING')
        return original(action,*args,**kwargs)
    remote.call=failing
    with pytest.raises(LifecycleError):execute(service,source,current,review)
    assert registry.get_by_source_instance(source) is not None
    assert service.status(source,review['operation_id'],'admin-fixture')['state']=='SUCCEEDED'
    remote.call=original
    assert execute(service,source,current,review)['purged'] is True and remote.writes==1


def test_function_refuses_unconfirmed_operation_and_public_access(coordinator):
    import psycopg
    service,registry,_,remote,_=coordinator
    source,current,review=prepare(coordinator)
    with service.store.connect() as c:
        with pytest.raises(psycopg.errors.RaiseException,match='SOURCE_PURGE_REFUSED'):
            c.execute(sql.SQL('SELECT {}(%s,%s,%s)').format(service.store.table('purge_retired_source')),
                (source,review['operation_id'],'admin-fixture'))
    assert registry.get_by_source_instance(source) is not None and remote.writes==0
    with service.store.connect() as c:
        fn=c.execute("SELECT prosecdef,proconfig,proacl::text FROM pg_proc WHERE oid=%s::regprocedure",
            (service.store.schema+'.purge_retired_source(text,uuid,text)',)).fetchone()
        assert fn['prosecdef'] and fn['proconfig']==['search_path=pg_catalog']
        # PUBLIC is represented by an empty grantee; it must have no execute ACL.
        assert not c.execute("SELECT 1 FROM pg_proc, LATERAL aclexplode(proacl) a WHERE oid=%s::regprocedure AND a.grantee=0 AND a.privilege_type='EXECUTE'",
            (service.store.schema+'.purge_retired_source(text,uuid,text)',)).fetchone()


def test_partial_shared_pair_deletes_only_exclusive_sibling(coordinator):
    from netbox_sync.source_config import SecretReference, SourceCredentials
    service,registry,config,remote,cleanups=coordinator
    other=replace(config,id='shared-peer',source_instance='shared-peer',
        target=replace(config.target,cluster_name='other'),
        credentials=SourceCredentials('peer',config.credentials.token_id,
            SecretReference('file','src-peer-secret-'+'c'*24)))
    registry.create_source(other)
    source,current,review=prepare(coordinator)
    assert execute(service,source,current,review)['purged'] is True
    assert cleanups==[[config.credentials.token_secret.key]]
    assert registry.get_by_source_instance(other.source_instance).config==other


def test_unproven_legacy_file_and_broker_refusal_never_purge(coordinator):
    service,registry,config,remote,_=coordinator
    from netbox_sync.source_config import SecretReference, SourceCredentials
    registry.update_source(config.id,credentials=SourceCredentials('operator',
        SecretReference('file','/untrusted/legacy/path'),config.credentials.token_secret))
    source,current,review=prepare(coordinator)
    service.cleanup=lambda _:pytest.fail('Never send arbitrary paths to broker')
    held=execute(service,source,current,review)
    assert held['state']=='SUCCEEDED' and held['safe_code']=='SOURCE_CREDENTIAL_CLEANUP_PENDING'
    assert registry.get_by_source_instance(source) is not None
    import psycopg
    # Pending retirement also fences replacement of credential references.
    with pytest.raises(psycopg.errors.CheckViolation,match="Credential reference is reserved"):
        registry.update_source(config.id,credentials=config.credentials)


def test_purge_transaction_rolls_back_all_prior_deletes(coordinator):
    import psycopg
    service,registry,_,remote,_=coordinator
    source,current,review=prepare(coordinator)
    # A late database failure must roll back the whole local purge, while retaining
    # the remote receipt so a restart never repeats the completed NetBox write.
    with service.store.connect() as c:
        c.execute(sql.SQL("CREATE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fixture rollback'; END $$").format(service.store.table('reject_purge')))
        c.execute(sql.SQL('CREATE TRIGGER reject_purge BEFORE DELETE ON {} FOR EACH ROW EXECUTE FUNCTION {}()').format(service.store.table('sources'),service.store.table('reject_purge')))
    with pytest.raises(psycopg.errors.RaiseException,match='fixture rollback'):
        execute(service,source,current,review)
    assert registry.get_by_source_instance(source) is not None
    assert service.status(source,review['operation_id'],'admin-fixture')['state']=='SUCCEEDED'
    with service.store.connect() as c:
        assert c.execute(sql.SQL('SELECT 1 FROM {} WHERE source_instance=%s').format(service.store.table('source_tombstones')),(source,)).fetchone()
        c.execute(sql.SQL('DROP TRIGGER reject_purge ON {}').format(service.store.table('sources')))
    assert execute(service,source,current,review)['purged'] is True and remote.writes==1


def test_broker_refusal_retains_source_for_retry(coordinator):
    service,registry,_,remote,_=coordinator
    source,current,review=prepare(coordinator)
    service.cleanup=lambda _:False
    held=execute(service,source,current,review)
    assert held['state']=='SUCCEEDED' and held['safe_code']=='SOURCE_CREDENTIAL_CLEANUP_PENDING'
    assert registry.get_by_source_instance(source) is not None
    service.cleanup=lambda _:True
    assert execute(service,source,current,review)['purged'] is True and remote.writes==1


def test_stale_run_writer_cannot_recreate_history_after_purge(coordinator):
    import psycopg
    from netbox_sync.run_history import postgres_run_repository,RunTrigger
    service,registry,config,_,_=coordinator
    source,current,review=prepare(coordinator)
    assert execute(service,source,current,review)['purged'] is True
    repository=postgres_run_repository(service.store.dsn,service.store.schema)
    with pytest.raises(psycopg.errors.CheckViolation,match='SOURCE_RUN_REFUSED'):
        repository.start_run(source,config.source_type,RunTrigger.SCHEDULED,'stale-scheduler')
    with service.store.connect() as c:
        assert not c.execute(sql.SQL('SELECT 1 FROM {} WHERE source_instance=%s').format(service.store.table('sync_runs')),(source,)).fetchone()
