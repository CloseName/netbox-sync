"""Real PostgreSQL: closing one immutable generation admits a different one."""
from uuid import uuid4
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb
from tests.test_retirement_journal_postgres import coordinator,prepare,execute,Remote
from tests.test_source_lifecycle_postgres import lifecycle
from tests.test_migrations_postgres import migration_database
from netbox_sync.host_registration import HostReservations,HostRegistrationConflict
from netbox_sync.source_operations import OperationStore,OperationError
from netbox_sync.source_lifecycle import LifecycleError
AM='00000000-0000-0000-0000-ac1f6be2c4da'

def claim(service,source,*,observed=False):
    with service.store.connect() as c:
        settings={'onboarding_mapping':{'references':{'site':{'id':1},'cluster':{'id':2}}}}
        if observed:settings['legacy_admission']={'state':'OBSERVED_ENDPOINT','operation_id':str(uuid4()),'observed_uuid':AM}
        else:settings['onboarding_mapping']['hosts']=[{'id':AM}]
        c.execute(sql.SQL("UPDATE {} SET source_type='esxi',legacy_identity_owner=false,settings=%s WHERE source_instance=%s").format(service.store.table('sources')),(Jsonb(settings),source))
        c.execute(sql.SQL("INSERT INTO {} (provider,anchor,source_instance,operation_id,actor_id) VALUES ('esxi',%s,%s,%s,'admin')").format(service.store.table('host_reservations')),(AM,source,uuid4()))

def test_closed_generation_releases_only_active_claim_and_fences_old_work(coordinator):
    service,registry,config,remote,_=coordinator;source=config.source_instance
    claim(service,source)
    source,current,review=prepare(coordinator)
    done=execute(service,source,current,review)
    assert done['state']=='FINALIZED'
    reservations=HostReservations(registry._connect,registry.schema)
    preview={'provider':'esxi','hosts':[{'id':AM}]}
    reservations.check(preview);reservations.reserve(preview,'new-generation',uuid4(),'operator')
    with service.store.connect() as c:
        rows=c.execute(sql.SQL('SELECT source_instance,released_at FROM {} ORDER BY source_instance').format(service.store.table('host_reservations'))).fetchall()
        assert len(rows)==2 and sum(r['released_at'] is None for r in rows)==1
    with pytest.raises(OperationError,match='SOURCE_ARCHIVED'):OperationStore(service.store.dsn,registry.schema).start(source,'PLAN')
    with pytest.raises(HostRegistrationConflict,match='SOURCE_ARCHIVED'):registry.assert_exclusive_host(registry.get_by_source_instance(source).config)
    with pytest.raises(HostRegistrationConflict):reservations.reserve(preview,'third-generation',uuid4(),'operator')
    assert execute(service,source,current,review)==done and remote.writes==1

class ArchiveRemote(Remote):
    def call(self,action,operation,**values):
        if action=='archive_review':
            self.result={'nonce':str(operation),'source_instance':self.source,'status':'REVIEWED','digest':'a'*64,
                'manifest':{'format':4,'purpose':'LEGACY_RETAIN','objects':[],
                    'retained':[{'kind':'device','id':5,'claimed':False,'present':True}], 'historical_outcome':'UNPROVED'},'deleted':[]}
        elif action=='archive_execute':
            self.writes+=1;self.result={**self.result,'status':'SUCCEEDED','generation_closed':True}
            if self.lose:
                from netbox_sync.local_control import ControlError
                raise ControlError('RETIREMENT_UNCERTAIN')
        return {'guard_instance':self.instance,'result':self.result}

def test_exact_observed_am_closes_without_promoting_identity_or_deleting_host_5(coordinator):
    service,registry,config,_,_=coordinator;source=config.source_instance;claim(service,source,observed=True)
    service.remote=ArchiveRemote(source)
    value=service.store.read(source);service.store.remove(source,value['revision'],value['display_name'],False,lambda _:None)
    reservations=HostReservations(registry._connect,registry.schema);preview={'provider':'esxi','hosts':[{'id':AM}]}
    with pytest.raises(HostRegistrationConflict,match='HOST_SOURCE_ARCHIVE_REQUIRED'):reservations.check(preview)
    current=service.retained_context(source)
    review=service.review(source,uuid4(),'admin-fixture',current['revision'],archive=True)
    service.remote.lose=True
    assert execute(service,source,current,review)['state']=='UNCERTAIN'
    service.remote.lose=False
    assert execute(service,source,current,review)['state']=='FINALIZED'
    assert service.store.read(source)['archive_mode']=='LEGACY_RETAIN'
    saved=registry.get_by_source_instance(source).config.settings
    assert 'provider_identity' not in saved and service.remote.result['deleted']==[]
    reservations.check(preview);reservations.reserve(preview,'new-am',uuid4(),'operator')

def test_unsealed_receipt_cannot_release_generation(coordinator):
    service,registry,config,remote,_=coordinator
    source,current,review=prepare(coordinator)
    original=remote.call
    def unsealed(*args,**kwargs):
        result=original(*args,**kwargs)
        result['result'].pop('generation_closed',None)
        return result
    remote.call=unsealed
    with pytest.raises(LifecycleError,match='RETIREMENT_CONFLICT'):execute(service,source,current,review)
    with service.store.connect() as c:assert not c.execute(sql.SQL('SELECT 1 FROM {}').format(service.store.table('source_archives'))).fetchone()


def test_cleanup_failure_keeps_reservation_and_resumes_same_receipt(coordinator):
    service,registry,config,remote,_=coordinator;source=config.source_instance
    claim(service,source)
    with service.store.connect() as c:
        c.execute(sql.SQL("UPDATE {} SET token_id_provider='file',token_secret_provider='file',token_id_key='src-exclusive-123456789',token_secret_key='src-exclusive-123456789' WHERE source_instance=%s").format(service.store.table('sources')),(source,))
    def unavailable(_):raise OSError('fixture broker unavailable')
    service.cleanup=unavailable
    source,current,review=prepare(coordinator)
    done=execute(service,source,current,review)
    assert done['state']=='SUCCEEDED' and done['safe_code']=='SOURCE_CREDENTIAL_CLEANUP_PENDING'
    assert service.store.read(source)['retirement']['state']=='SUCCEEDED'
    with service.store.connect() as c:
        assert c.execute(sql.SQL('SELECT released_at FROM {} WHERE source_instance=%s').format(service.store.table('host_reservations')),(source,)).fetchone()['released_at'] is None
    cleaned=[];service.cleanup=lambda keys:cleaned.extend(keys)
    assert execute(service,source,current,review)['state']=='FINALIZED'
    assert cleaned==['src-exclusive-123456789'] and remote.writes==1


def test_crash_after_local_tombstone_does_not_repeat_netbox_deletion(coordinator,monkeypatch):
    service,registry,config,remote,_=coordinator;source=config.source_instance;claim(service,source)
    source,current,review=prepare(coordinator)
    finish=service.journal.finalized
    def crash(*_):raise RuntimeError('local finalization crash')
    monkeypatch.setattr(service.journal,'finalized',crash)
    with pytest.raises(RuntimeError):execute(service,source,current,review)
    assert service.store.read(source)['removed_at'] and remote.writes==1
    monkeypatch.setattr(service.journal,'finalized',finish)
    assert execute(service,source,current,review)['state']=='FINALIZED' and remote.writes==1


def test_released_claim_does_not_authorize_old_attempt_against_new_generation(coordinator):
    service,registry,config,remote,_=coordinator;source=config.source_instance;claim(service,source)
    source,current,review=prepare(coordinator);execute(service,source,current,review)
    reservations=HostReservations(registry._connect,registry.schema);preview={'provider':'esxi','hosts':[{'id':AM}]}
    operation=uuid4();reservations.reserve(preview,'new-am',operation,'admin')
    with pytest.raises(HostRegistrationConflict):
        with reservations.registration_guard(preview,source,operation,'admin'):pytest.fail('stale generation admitted')
    with service.store.connect() as c:
        assert c.execute(sql.SQL('SELECT source_instance FROM {} WHERE released_at IS NULL').format(service.store.table('host_reservations'))).fetchone()['source_instance']=='new-am'


def test_restored_archive_requires_exact_external_receipt_before_admission(coordinator):
    from netbox_sync.source_archive import recheck
    service,registry,config,remote,_=coordinator;source=config.source_instance;claim(service,source)
    source,current,review=prepare(coordinator);execute(service,source,current,review)
    with service.store.connect() as c:
        c.execute(sql.SQL('UPDATE {} SET verified_at=NULL').format(service.store.table('source_archives')))
    reservations=HostReservations(registry._connect,registry.schema);preview={'provider':'esxi','hosts':[{'id':AM}]}
    with pytest.raises(HostRegistrationConflict,match='HOST_ARCHIVE_RECHECK_REQUIRED'):reservations.check(preview)
    original=remote.result
    remote.result={**original,'generation_closed':False}
    with pytest.raises(LifecycleError,match='RETIREMENT_CONFLICT'):recheck(service.store,remote,source)
    with pytest.raises(HostRegistrationConflict,match='HOST_ARCHIVE_RECHECK_REQUIRED'):reservations.reserve(preview,'new-am',uuid4(),'admin')
    remote.result=original
    assert recheck(service.store,remote,source)['verified']
    reservations.check(preview)
    assert remote.writes==1


def test_historical_success_without_seal_can_be_closed_without_rewriting_history(coordinator):
    service,registry,config,remote,_=coordinator;source=config.source_instance;claim(service,source,observed=True)
    source,current,old=prepare(coordinator)
    record,_=service.journal.begin(source,old['operation_id'],'admin-fixture',old['digest'],current['display_name'],False)
    proof=remote.call('execute',old['operation_id'])
    proof['result'].pop('generation_closed')
    service.journal.resolve(source,old['operation_id'],'admin-fixture',proof['guard_instance'],proof['result'])
    historical=proof['result'].copy()
    service.remote=ArchiveRemote(source)
    fresh=service.store.read(source)
    review=service.review(source,uuid4(),'admin-fixture',fresh['revision'],archive=True)
    assert execute(service,source,fresh,review)['state']=='FINALIZED'
    with service.store.connect() as c:
        previous=service.journal._record(c,source,old['operation_id'],'admin-fixture')
        assert previous['state']=='SUCCEEDED' and previous['receipt']==historical
        assert str(previous['superseded_by'])==review['operation_id']
    assert service.store.read(source)['archive_mode']=='LEGACY_RETAIN'


def test_legacy_archive_never_bypasses_uncertain_retirement(coordinator):
    service,registry,config,remote,_=coordinator
    source,current,review=prepare(coordinator);remote.lose=True
    assert execute(service,source,current,review)['state']=='UNCERTAIN'
    with pytest.raises(LifecycleError,match='SOURCE_RETIREMENT_PENDING'):
        service.review(source,uuid4(),'admin-fixture',service.store.read(source)['revision'],archive=True)
    assert remote.writes==1


def test_central_review_lists_pending_claims_and_conflicting_sources(coordinator):
    from dataclasses import replace
    from netbox_sync.source_archive import generations
    service,registry,config,_,_=coordinator
    claim(service,config.source_instance)
    registry.create_source(replace(config,id='duplicate',source_instance='duplicate',source_type='esxi',legacy_identity_owner=False,settings={'onboarding_mapping':{'hosts':[{'id':AM}]}}))
    with service.store.connect() as c:
        c.execute(sql.SQL("INSERT INTO {} (provider,anchor,source_instance,operation_id,actor_id) VALUES ('esxi',%s,'pending',%s,'admin')").format(service.store.table('host_reservations')),(str(uuid4()),uuid4()))
    rows={r['source_instance']:r for r in generations(service.store)['sources']}
    assert rows['pending']['state']=='REGISTRATION_PENDING'
    assert rows[config.source_instance]['conflicting_sources']==['duplicate']
    assert rows['duplicate']['conflicting_sources']==[config.source_instance]
    assert all(r['needs_review'] for r in rows.values())


@pytest.mark.parametrize('recovery_state',['PREPARED','CREDENTIALS_PENDING'])
def test_close_cancels_only_recovery_without_credential_dispatch(coordinator,recovery_state):
    service,registry,config,remote,_=coordinator
    source=config.source_instance
    current=service.store.read(source)
    with service.store.connect() as c:
        c.execute(sql.SQL("INSERT INTO {} (operation_id,source_instance,actor_id,revision,plan,state) VALUES (%s,%s,'admin',%s,'{{}}',%s)").format(service.store.table('source_recoveries')),(uuid4(),source,current['revision'],recovery_state))
    if recovery_state=='CREDENTIALS_PENDING':
        with pytest.raises(LifecycleError,match='SOURCE_RECOVERY_OUTCOME_UNCERTAIN'):prepare(coordinator)
        assert remote.writes==0
    else:
        source,current,review=prepare(coordinator)
        assert execute(service,source,current,review)['state']=='FINALIZED'
    with service.store.connect() as c:
        saved=c.execute(sql.SQL('SELECT state FROM {} WHERE source_instance=%s').format(service.store.table('source_recoveries')),(source,)).fetchone()
        assert saved['state']==('ABANDONED' if recovery_state=='PREPARED' else recovery_state)


def test_old_retention_does_not_silently_authorize_credential_cleanup(coordinator):
    service,registry,config,remote,_=coordinator;source=config.source_instance
    claim(service,source)
    with service.store.connect() as c:
        c.execute(sql.SQL("UPDATE {} SET token_id_provider='file',token_secret_provider='file',token_id_key='src-exclusive-123456789',token_secret_key='src-exclusive-123456789' WHERE source_instance=%s").format(service.store.table('sources')),(source,))
    cleanups=[];service.cleanup=lambda keys:cleanups.extend(keys)
    source,current,review=prepare(coordinator)
    held=service.execute(source,review['operation_id'],'admin-fixture',review['digest'],current['display_name'],False)
    assert held['state']=='SUCCEEDED' and not cleanups
    with service.store.connect() as c:
        assert c.execute(sql.SQL('SELECT released_at FROM {} WHERE source_instance=%s').format(service.store.table('host_reservations')),(source,)).fetchone()['released_at'] is None
    assert execute(service,source,current,review)['state']=='FINALIZED'
    assert cleanups==['src-exclusive-123456789'] and remote.writes==1
