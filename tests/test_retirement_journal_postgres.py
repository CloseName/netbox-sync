"""DB-only coordination regression; remote atomicity has separate real NetBox gates."""
from uuid import uuid4
from dataclasses import replace
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb
from tests.test_source_lifecycle_postgres import lifecycle
from tests.test_migrations_postgres import migration_database
from netbox_sync.retirement_coordinator import RetirementCoordinator
from netbox_sync.source_operations import OperationStore,OperationError
from netbox_sync.source_lifecycle import LifecycleError
from netbox_sync.local_control import ControlError

class Remote:
    def __init__(self,source,cluster=2):
        self.instance=str(uuid4());self.source=source;self.cluster=cluster
        self.writes=0;self.result=None;self.lose=False
    def call(self,action,operation,**values):
        if action=='review':
            self.result={'nonce':str(operation),'source_instance':self.source,'status':'REVIEWED','digest':'a'*64,
                'manifest':{'format':2,'cluster_id':self.cluster,'objects':[['vm:4','b'*64]],'roots':[['vm',4]]},'deleted':[]}
        elif action=='execute':
            self.writes+=1
            self.result={**self.result,'status':'SUCCEEDED','deleted':['vm:4']}
            if self.lose:raise ControlError('RETIREMENT_UNCERTAIN')
        return {'guard_instance':self.instance,'result':self.result}

@pytest.fixture
def coordinator(lifecycle):
    store,registry,source=lifecycle
    with store.connect() as connection:
        connection.execute(sql.SQL('UPDATE {} SET settings=%s WHERE source_instance=%s').format(store.table('sources')),
            (Jsonb({'onboarding_mapping':{'references':{'site':{'id':1},'cluster':{'id':2}}}}),source.source_instance))
    remote=Remote(source.source_instance);cleanups=[]
    return RetirementCoordinator(store,remote,cleanups.append),registry,source,remote,cleanups

def prepare(value):
    service,_,source,_,_=value
    source=source.source_instance
    current=service.store.read(source)
    result=service.review(source,uuid4(),'admin-fixture',current['revision'])
    return source,current,result

def execute(service,source,current,review):
    return service.execute(source,review['operation_id'],'admin-fixture',review['digest'],current['display_name'],False)

def test_receipt_before_tombstone_and_idempotent_completion(coordinator):
    service,registry,config,remote,cleanups=coordinator
    source,current,review=prepare(coordinator)
    assert service.store.read(source)['removed_at'] is None
    done=execute(service,source,current,review)
    assert done['state']=='FINALIZED' and remote.writes==1
    assert service.store.read(source)['removed_at'] is not None and not cleanups
    assert execute(service,source,current,review)==done and remote.writes==1
    assert registry.get_by_source_instance(source) is not None

def test_loss_blocks_other_operations_and_recovers_by_get_after_restart(coordinator):
    service,registry,config,remote,_=coordinator
    source,current,review=prepare(coordinator);remote.lose=True
    result=execute(service,source,current,review)
    assert result['state']=='UNCERTAIN' and service.store.read(source)['removed_at'] is None
    assert not registry.get_by_source_instance(source).config.enabled
    with pytest.raises(OperationError,match='SOURCE_RETIREMENT_PENDING'):
        OperationStore(service.store.dsn,service.store.schema).start(source,'PLAN')
    restarted=RetirementCoordinator(service.store,remote,lambda _:None)
    result=execute(restarted,source,current,review)
    assert result['state']=='FINALIZED' and remote.writes==1

def test_other_actor_and_changed_approval_never_write(coordinator):
    service,_,_,remote,_=coordinator
    source,current,review=prepare(coordinator)
    with pytest.raises(LifecycleError,match='RETIREMENT_CONFLICT'):
        service.execute(source,review['operation_id'],'another-admin',review['digest'],current['display_name'],False)
    with pytest.raises(LifecycleError,match='RETIREMENT_CONFLICT'):
        service.execute(source,review['operation_id'],'admin-fixture','f'*64,current['display_name'],False)
    assert remote.writes==0 and service.store.read(source)['removed_at'] is None

def test_shared_current_placement_refuses_review(coordinator):
    service,registry,config,remote,_=coordinator
    other=replace(config,id='other-source',source_instance='other-source')
    registry.create_source(other)
    with service.store.connect() as connection:
        connection.execute(sql.SQL('UPDATE {} SET settings=(SELECT settings FROM {} WHERE source_instance=%s) WHERE source_instance=%s').format(
            service.store.table('sources'),service.store.table('sources')),(config.source_instance,'other-source'))
    with pytest.raises(LifecycleError,match='RETIREMENT_BLOCKED'):prepare(coordinator)
    assert remote.result is None and remote.writes==0

def test_wrong_remote_receipt_does_not_finalize(coordinator):
    service,_,_,remote,_=coordinator
    source,current,review=prepare(coordinator);remote.lose=True
    execute(service,source,current,review)
    remote.result={**remote.result,'deleted':[]}
    with pytest.raises(LifecycleError,match='RETIREMENT_CONFLICT'):
        execute(service,source,current,review)
    assert service.store.read(source)['removed_at'] is None and remote.writes==1


def test_confirmed_refusal_is_idempotent_and_does_not_dispatch_again(coordinator):
    service,_,_,remote,_=coordinator
    source,current,review=prepare(coordinator)
    original=remote.call
    def refused(action,operation,**values):
        if action=='execute':
            remote.writes+=1
            raise ControlError('RETIREMENT_BLOCKED')
        return original(action,operation,**values)
    remote.call=refused
    result=execute(service,source,current,review)
    assert result['state']=='BLOCKED'
    assert execute(service,source,current,review)==result and remote.writes==1
    assert service.store.read(source)['removed_at'] is None


def test_durable_success_is_rechecked_before_local_finalization(coordinator):
    service,_,_,remote,_=coordinator
    source,current,review=prepare(coordinator)
    record,dispatch=service.journal.begin(source,review['operation_id'],'admin-fixture',review['digest'],current['display_name'],False)
    assert dispatch
    evidence=remote.call('execute',review['operation_id'],digest=review['digest'])
    service.journal.resolve(source,review['operation_id'],'admin-fixture',evidence['guard_instance'],evidence['result'])
    # Model a separately restored/stale NetBox receipt after the Sync journal
    # committed success but before its source tombstone transaction.
    remote.result={**remote.result,'status':'REVIEWED','deleted':[]}
    with pytest.raises(LifecycleError,match='RETIREMENT_CONFLICT'):
        execute(service,source,current,review)
    assert service.store.read(source)['removed_at'] is None and remote.writes==1
    remote.result=evidence['result']
    assert execute(service,source,current,review)['state']=='FINALIZED'
    assert remote.writes==1


@pytest.mark.parametrize('changed', [False, True])
def test_not_delivered_execute_requires_explicit_same_intent_resume(coordinator, changed):
    service,_,_,remote,_=coordinator
    source,current,review=prepare(coordinator)
    original=remote.call
    def disconnected(action,operation,**values):
        if action=='execute':raise ControlError('RETIREMENT_UNCERTAIN')
        return original(action,operation,**values)
    remote.call=disconnected
    assert execute(service,source,current,review)['state']=='UNCERTAIN'
    remote.call=original
    # Ordinary status/retry never writes, even though NetBox still says REVIEWED.
    assert execute(service,source,current,review)['state']=='UNCERTAIN'
    assert remote.writes==0
    if changed:
        remote.result={**remote.result,'digest':'f'*64}
        with pytest.raises(LifecycleError,match='RETIREMENT_CONFLICT'):
            service.execute(source,review['operation_id'],'admin-fixture',review['digest'],current['display_name'],False,resume=True)
        assert remote.writes==0 and service.store.read(source)['removed_at'] is None
    else:
        restarted=RetirementCoordinator(service.store,remote,lambda _:None)
        from netbox_sync.lifecycle_protocol import handle_lifecycle
        result=handle_lifecycle(restarted.store,None,dict(action='retirement_resume',source_instance=source,
            operation_id=review['operation_id'],actor_id='admin-fixture',digest=review['digest'],
            confirmed_source=current['display_name'],remove_credentials=False),retirement=restarted)
        assert result['state']=='FINALIZED' and remote.writes==1
        assert restarted.execute(source,review['operation_id'],'admin-fixture',review['digest'],current['display_name'],False,resume=True)==result
        assert remote.writes==1
