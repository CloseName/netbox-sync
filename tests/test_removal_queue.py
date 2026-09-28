"""Real DB admission, durable consent and waiting for already admitted work."""
from uuid import uuid4
from contextlib import contextmanager
import pytest
import psycopg
from psycopg import sql
from tests.test_retirement_journal_postgres import coordinator
from tests.test_source_lifecycle_postgres import lifecycle
from tests.test_migrations_postgres import migration_database
from netbox_sync.removal_queue import RemovalQueue
from netbox_sync.source_operations import OperationStore, OperationError
from netbox_sync.source_lifecycle import LifecycleError
from netbox_sync.run_history import postgres_run_repository, RunTrigger, RunStatus


def enqueue(service, source):
    return RemovalQueue(service).enqueue(source,uuid4(),'admin-fixture',service.store.read(source)['revision'],True)


@pytest.mark.parametrize('kind',['PLAN','DISCOVERY'])
def test_waits_for_active_read_and_fences_new_work_across_restart(coordinator,kind):
    service,registry,config,remote,_=coordinator
    source=config.source_instance
    operations=OperationStore(service.store.dsn,service.store.schema)
    active,_=operations.start(source,kind)
    saved=enqueue(service,source)
    assert saved['state']=='WAITING'
    assert not registry.get_source_config(source).sync_enabled
    with pytest.raises(OperationError,match='SOURCE_RETIREMENT_PENDING'):operations.start(source,'PLAN')
    queue=RemovalQueue(service);queue.tick()
    assert remote.writes==0 and queue.status(source,saved['operation_id'],'admin-fixture')['state']=='WAITING'
    # Existing worker finalization remains permitted after admission is paused.
    operations.execute(active,lambda:(_ for _ in ()).throw(RuntimeError('fixture read failed')))
    RemovalQueue(service).tick()
    assert remote.writes==1 and registry.get_by_source_instance(source) is None
    assert RemovalQueue(service).status(source,saved['operation_id'],'admin-fixture')['state']=='FINALIZED'
    with service.store.connect() as c:
        assert not c.execute(sql.SQL('SELECT 1 FROM {}').format(service.store.table('source_removal_requests'))).fetchone()
    RemovalQueue(service).tick()
    assert remote.writes==1


def test_active_apply_finishes_then_deletes_but_unknown_outcome_blocks(coordinator):
    service,registry,config,remote,_=coordinator;source=config.source_instance
    repo=postgres_run_repository(service.store.dsn,service.store.schema)
    run=repo.start_run(source,'proxmox',RunTrigger.MANUAL,'fixture')
    saved=enqueue(service,source)
    actual=service.store.lock
    @contextmanager
    def held(path):raise LifecycleError('SOURCE_APPLY_ACTIVE');yield
    service.store.lock=held
    queue=RemovalQueue(service);queue.tick()
    assert remote.writes==0
    repo.finish_run(run.run_id,RunStatus.SUCCEEDED)
    service.store.lock=actual
    queue.tick()
    assert registry.get_by_source_instance(source) is None and remote.writes==1


def test_lost_apply_result_is_never_assumed_safe(coordinator):
    service,registry,config,remote,_=coordinator;source=config.source_instance
    repo=postgres_run_repository(service.store.dsn,service.store.schema)
    run=repo.start_run(source,'proxmox',RunTrigger.MANUAL,'fixture')
    saved=enqueue(service,source)
    repo.finish_run(run.run_id,RunStatus.OUTCOME_UNCERTAIN)
    queue=RemovalQueue(service);queue.tick()
    status=queue.status(source,saved['operation_id'],'admin-fixture')
    assert status['state']=='BLOCKED' and status['safe_code']=='SOURCE_APPLY_UNCONFIRMED'
    assert remote.writes==0 and registry.get_by_source_instance(source) is not None


def test_consent_actor_revision_and_stale_scheduler_fences(coordinator):
    service,registry,config,remote,_=coordinator;source=config.source_instance
    queue=RemovalQueue(service);revision=service.store.read(source)['revision'];operation=uuid4()
    for bad in (False,1,'true'):
        with pytest.raises(LifecycleError):queue.enqueue(source,operation,'admin-fixture',revision,bad)
    with pytest.raises(LifecycleError):queue.enqueue(source,operation,'admin-fixture','0'*64,True)
    saved=queue.enqueue(source,operation,'admin-fixture',revision,True)
    assert queue.enqueue(source,operation,'admin-fixture',revision,True)==saved
    with pytest.raises(LifecycleError):queue.enqueue(source,operation,'other-actor',revision,True)
    with pytest.raises(LifecycleError):queue.enqueue(source,uuid4(),'admin-fixture',revision,True)
    repo=postgres_run_repository(service.store.dsn,service.store.schema)
    with pytest.raises(psycopg.errors.CheckViolation,match='SOURCE_RUN_REFUSED'):
        repo.start_run(source,'proxmox',RunTrigger.SCHEDULED,'stale snapshot')
    assert remote.writes==0


def test_waiting_fence_still_allows_evidence_reconciliation(coordinator):
    from netbox_sync.source_operations import source_gate
    service,_,config,_,_=coordinator
    source=config.source_instance;enqueue(service,source)
    with service.store.connect() as c,source_gate(c,service.store.schema,source,allow_waiting=True):
        pass
    with pytest.raises(OperationError):
        with service.store.connect() as c,source_gate(c,service.store.schema,source):pass


def test_abandoned_read_requires_expiry_and_actual_owner_unlock(coordinator):
    service,registry,config,remote,_=coordinator;source=config.source_instance
    ops=OperationStore(service.store.dsn,service.store.schema);active,_=ops.start(source,'PLAN')
    enqueue(service,source)
    with service.store.connect() as c:
        c.execute(sql.SQL("UPDATE {} SET updated_at=clock_timestamp()-interval '181 seconds' WHERE operation_id=%s").format(service.store.table('source_operations')),(active['operation_id'],))
    with ops.connect() as owner:
        owner.autocommit=True
        owner.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',(ops.lock_key(source,'PLAN'),))
        RemovalQueue(service).tick()
        assert remote.writes==0
    RemovalQueue(service).tick()
    assert remote.writes==1 and registry.get_by_source_instance(source) is None


def test_uncommitted_removal_pause_serializes_stale_run_admission(coordinator):
    from concurrent.futures import ThreadPoolExecutor
    import time
    service,registry,config,remote,_=coordinator;source=config.source_instance
    repo=postgres_run_repository(service.store.dsn,service.store.schema)
    with service.store.connect() as pending:
        row=pending.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s FOR UPDATE').format(service.store.table('sources')),(source,)).fetchone()
        pending.execute(sql.SQL("INSERT INTO {} (source_instance,operation_id,actor_id,revision,display_name) VALUES (%s,%s,%s,%s,%s)").format(service.store.table('source_removal_requests')),(source,uuid4(),'admin-fixture',service.store.revision(row),row['name']))
        with ThreadPoolExecutor(max_workers=1) as pool:
            run=pool.submit(repo.start_run,source,'proxmox',RunTrigger.SCHEDULED,'stale snapshot')
            time.sleep(.1)
            assert not run.done(), 'Admission must wait for the enqueue transaction'
            pending.commit()
            with pytest.raises(psycopg.errors.CheckViolation,match='SOURCE_RUN_REFUSED'):run.result(timeout=5)
    assert remote.writes==0
