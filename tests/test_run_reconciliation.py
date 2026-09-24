"""Administrative baseline decisions preserve historical runs and uncertain evidence."""
from uuid import uuid4
from psycopg import sql
import pytest
from tests.test_source_lifecycle_postgres import lifecycle
from tests.test_migrations_postgres import migration_database
from tests.test_source_registry_postgres import _safe_test_dsn
from netbox_sync.run_history import postgres_run_repository,RunStatus
from netbox_sync.run_reconciliation import RunReconciliation
from netbox_sync.source_lifecycle import LifecycleError

ACK={'old_writes_stopped':True,'outcome_stays_unknown':True,'fresh_plan_required':True}
class Audit:
    def __init__(self,source):self.source=source;self.guard=str(uuid4());self.rows=[];self.calls=[]
    def call(self,action,operation,**values):
        assert action=='audit' and values=={'source_instance':self.source}
        self.calls.append(action)
        return {'guard_instance':self.guard,'result':{'source_instance':self.source,'objects':list(self.rows),'historical_outcome':'UNPROVED'}}

def setup(lifecycle,status='OUTCOME_UNCERTAIN'):
    store,registry,source=lifecycle
    runs=postgres_run_repository(_safe_test_dsn(),store.schema)
    started=runs.start_run(source.source_instance,source.source_type,'manual','fixture')
    old=runs.finish_run(started.run_id,RunStatus(status)) if status!='RUNNING' else started
    remote=Audit(source.source_instance)
    return store,source,runs,old,remote,RunReconciliation(store,remote)

@pytest.mark.parametrize('status',['OUTCOME_UNCERTAIN','PARTIALLY_APPLIED'])
def test_accept_baseline_preserves_run_and_source_credentials_and_never_repeats_write(lifecycle,status):
    store,source,runs,old,remote,control=setup(lifecycle,status)
    assert runs.reconciliation_required(source.source_instance)
    operation=uuid4();review=control.review(source.source_instance,operation)
    assert review['historical_outcome']=='UNPROVED'
    result=control.confirm(source.source_instance,operation,'admin-id',review['digest'],ACK)
    assert result['status']=='BASELINE_ACCEPTED'
    assert not runs.reconciliation_required(source.source_instance)
    assert runs.scheduled_reconciliation_required(source.source_instance)
    assert runs.get_run(old.run_id)==old
    assert not lifecycle[1].get_by_source_instance(source.source_instance).config.sync_enabled
    assert lifecycle[1].get_by_source_instance(source.source_instance).config.credentials==source.credentials
    assert control.confirm(source.source_instance,operation,'admin-id',review['digest'],ACK)==result
    assert remote.calls==['audit','audit']
    after=RunReconciliation(store,remote).review(source.source_instance,uuid4())
    assert not after['runs'] and after['decisions'][0]['actor_id']=='admin-id'
    assert after['decisions'][0]['runs']==[str(old.run_id)]
    assert store.read(source.source_instance)['removal_blocker'] is None
    # Restoration invalidates capabilities without deleting audit or changing history.
    with store.connect() as connection:
        connection.execute(sql.SQL('UPDATE {} SET valid=false').format(store.table('run_reconciliations')))
    assert runs.reconciliation_required(source.source_instance)
    with pytest.raises(LifecycleError):control.confirm(source.source_instance,operation,'admin-id',review['digest'],ACK)
    second=uuid4();fresh=control.review(source.source_instance,second)
    control.confirm(source.source_instance,second,'admin-id',fresh['digest'],ACK)
    with store.connect() as connection:
        assert connection.execute(sql.SQL('SELECT count(*) AS n FROM {}').format(store.table('run_reconciliations'))).fetchone()['n']==2
    assert runs.get_run(old.run_id)==old

@pytest.mark.parametrize('mode',['running','changed','foreign_actor','unchecked','integer_ack'])
def test_baseline_refuses_active_work_changed_inventory_or_unconfirmed_decision(lifecycle,mode):
    store,source,runs,old,remote,control=setup(lifecycle,'RUNNING' if mode=='running' else 'OUTCOME_UNCERTAIN')
    operation=uuid4()
    if mode=='running':
        with pytest.raises(LifecycleError,match='SOURCE_OPERATION_ACTIVE'):control.review(source.source_instance,operation)
        assert not remote.calls
        return
    review=control.review(source.source_instance,operation)
    ack=dict(ACK)
    if mode=='changed':remote.rows=[{'id':1}]
    if mode=='unchecked':ack['old_writes_stopped']=False
    if mode=='integer_ack':ack['old_writes_stopped']=1
    if mode=='foreign_actor':control.confirm(source.source_instance,operation,'original',review['digest'],ack)
    with pytest.raises(LifecycleError):control.confirm(source.source_instance,operation,'another',review['digest'],ack)
    assert runs.get_run(old.run_id)==old
    if mode!='foreign_actor':assert runs.reconciliation_required(source.source_instance)


def test_schedule_requires_new_successful_manual_run_after_baseline(lifecycle):
    store,source,runs,old,remote,control=setup(lifecycle)
    operation=uuid4();review=control.review(source.source_instance,operation)
    control.confirm(source.source_instance,operation,'admin',review['digest'],ACK)
    scheduled=runs.start_run(source.source_instance,source.source_type,'scheduled','fixture')
    runs.finish_run(scheduled.run_id,RunStatus.SUCCEEDED)
    assert runs.scheduled_reconciliation_required(source.source_instance)
    manual=runs.start_run(source.source_instance,source.source_type,'manual','fixture')
    runs.finish_run(manual.run_id,RunStatus.FAILED)
    assert runs.scheduled_reconciliation_required(source.source_instance)
    manual=runs.start_run(source.source_instance,source.source_type,'manual','fixture')
    runs.finish_run(manual.run_id,RunStatus.SUCCEEDED)
    assert not runs.scheduled_reconciliation_required(source.source_instance)
    assert runs.get_run(old.run_id)==old
