"""Real PostgreSQL races for the bounded operation model; no provider connections."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event
from uuid import uuid4

import pytest
from psycopg import sql

from netbox_sync.application.sync_plan import SyncPlan
from netbox_sync.source_operations import OperationStore, OperationError
from tests.test_migrations_postgres import migration_database, _upgrade
from tests.test_source_registry_postgres import _safe_test_dsn
from tests.sample_data import sample_source_config


@pytest.fixture
def operations(migration_database):
    registry, engine = migration_database
    _upgrade(registry, engine)
    source = sample_source_config()
    registry.create_source(source)
    registry.create_source(replace(source, id='second-source', source_instance='second-source'))
    return OperationStore(_safe_test_dsn(), registry.schema), source.source_instance


def plan(source):
    value = SyncPlan(source, source, 'proxmox', 'source', 'target', 'provider', 'netbox', ())
    return {**value.canonical_dict(), 'digest': value.digest}


def test_simultaneous_starts_create_exactly_one_generation(operations):
    store, source = operations
    barrier = Barrier(8)
    def start():
        barrier.wait()
        return store.start(source, 'PLAN')
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: start(), range(8)))
    assert sum(created for _, created in results) == 1
    assert len({row['operation_id'] for row, _ in results}) == 1


def test_other_source_and_other_kind_remain_independent(operations):
    store, source = operations
    first, _ = store.start(source, 'PLAN')
    second, created = store.start('second-source', 'PLAN')
    third, discovery_created = store.start(source, 'DISCOVERY')
    assert created and discovery_created
    assert len({row['operation_id'] for row in (first, second, third)}) == 3


def test_ready_is_persisted_reopen_and_generation_fenced(operations):
    store, source = operations
    first, _ = store.start(source, 'PLAN')
    store.execute(first, lambda: plan(source))
    reopened = OperationStore(_safe_test_dsn(), store.schema)
    assert reopened.latest(source)[0]['result'] == plan(source)
    assert reopened.current_plan(source, plan(source)['digest']) == str(first['operation_id'])
    second, created = reopened.start(source, 'PLAN')
    assert created
    calls = []
    store.execute(first, lambda: calls.append('old execution'))
    assert not calls
    assert store.latest(source)[0]['operation_id'] == second['operation_id']
    with pytest.raises(OperationError, match='PLAN_STALE'):
        reopened.current_plan(source, plan(source)['digest'])


def test_worker_failure_is_durable_and_sanitized(operations):
    store, source = operations
    row, _ = store.start(source, 'DISCOVERY')
    def fail():
        raise RuntimeError('VERY_SECRET_PROVIDER_EXCEPTION')
    store.execute(row, fail)
    saved = store.latest(source)[0]
    assert saved['status'] == 'FAILED'
    assert saved['safe_error_code'] == 'OPERATION_FAILED'
    assert 'VERY_SECRET' not in str(saved)


def test_discovery_completion_and_duplicate_executor(operations):
    store, source = operations
    row, _ = store.start(source, 'DISCOVERY')
    started, finish = Event(), Event()
    calls = []
    def discover():
        calls.append(1)
        started.set()
        assert finish.wait(5)
        return {'source_instance': source, 'source_type':'proxmox', 'site_slug':'test', 'cluster_name':'Test', 'items': []}
    with ThreadPoolExecutor(2) as pool:
        running = pool.submit(store.execute, row, discover)
        assert started.wait(5)
        duplicate, created = store.start(source, 'DISCOVERY')
        assert not created and duplicate['operation_id'] == row['operation_id']
        store.execute(row, discover)
        finish.set()
        running.result()
    assert calls == [1]
    assert store.latest(source)[0]['status'] == 'SUCCEEDED'


def test_orphan_recovery_does_not_resume_work(operations):
    store, source = operations
    row, _ = store.start(source, 'PLAN')
    with store.connect() as connection:
        connection.execute(sql.SQL("UPDATE {} SET updated_at=clock_timestamp()-interval '4 minutes'")
                           .format(store.table))
    assert store.latest(source)[0]['safe_error_code'] == 'OPERATION_INTERRUPTED'
    calls = []
    store.execute(row, lambda: calls.append(1))
    assert calls == []
    assert store.start(source, 'PLAN')[1]


def test_recovery_never_replaces_still_owned_execution(operations):
    store, source = operations
    row, _ = store.start(source, 'PLAN')
    with store.connect() as owner:
        owner.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',
                      (store.lock_key(source, 'PLAN'),))
        owner.execute(sql.SQL("UPDATE {} SET updated_at=clock_timestamp()-interval '4 minutes'")
                      .format(store.table))
        owner.commit()
        assert store.latest(source)[0]['status'] == 'RUNNING'
        current, created = store.start(source, 'PLAN')
        assert not created and current['operation_id'] == row['operation_id']


def test_bounded_latest_result_expiry(operations):
    store, source = operations
    for _ in range(4):
        row, _ = store.start(source, 'PLAN')
        store.execute(row, lambda: plan(source))
    assert len(store.latest(source)) == 1
    with store.connect() as connection:
        connection.execute(sql.SQL("UPDATE {} SET finished_at=clock_timestamp()-interval '25 hours'")
                           .format(store.table))
    saved = store.latest(source)[0]
    assert saved['status'] == 'STALE' and saved['result'] is None


def test_foreign_result_and_bad_digest_are_rejected(operations):
    store, source = operations
    row, _ = store.start(source, 'PLAN')
    store.execute(row, lambda: plan('second-source'))
    assert store.latest(source)[0]['safe_error_code'] == 'RESULT_INVALID'
    row, _ = store.start(source, 'PLAN')
    store.execute(row, lambda: {**plan(source), 'digest': 'a'*64})
    assert store.latest(source)[0]['safe_error_code'] == 'RESULT_INVALID'


def test_unknown_and_disabled_sources_fail_closed(operations):
    store, source = operations
    with pytest.raises(OperationError, match='SOURCE_NOT_FOUND'):
        store.start('missing-source', 'PLAN')
    with store.connect() as connection:
        connection.execute(sql.SQL('UPDATE {} SET enabled=false WHERE source_instance=%s')
                           .format(sql.Identifier(store.schema, 'sources')), (source,))
    with pytest.raises(OperationError, match='SOURCE_DISABLED'):
        store.start(source, 'PLAN')


def test_stale_invalidation_cannot_touch_replacement(operations):
    store, source = operations
    first, _ = store.start(source, 'PLAN');store.execute(first, lambda: plan(source))
    store.invalidate_plan(source, first['operation_id'])
    assert store.latest(source)[0]['status'] == 'STALE'
    next_row, _ = store.start(source, 'PLAN');store.execute(next_row, lambda: plan(source))
    store.invalidate_plan(source, first['operation_id'])
    assert store.current_plan(source, plan(source)['digest'], next_row['operation_id']) == str(next_row['operation_id'])


def test_late_completion_is_logged_without_replacing_new_state(operations, caplog):
    caplog.set_level('WARNING', logger='netbox_sync.source_operations')
    store, source = operations
    first, _ = store.start(source, 'PLAN')
    replacement = uuid4()
    def late():
        # Simulate a retired generation at the persistence boundary.
        with store.connect() as connection:
            connection.execute(sql.SQL('UPDATE {} SET operation_id=%s WHERE operation_id=%s').format(store.table),
                               (replacement, first['operation_id']))
        return plan(source)
    store.execute(first, late)
    row = store.latest(source)[0]
    assert row['operation_id'] == replacement and row['status'] == 'RUNNING' and row['result'] is None
    assert 'OPERATION_COMPLETION_DISCARDED' in caplog.text
    assert str(first['operation_id']) in caplog.text


def test_consumed_plan_survives_lost_reply_and_new_generation_can_reconcile(operations):
    from netbox_sync.run_history import postgres_run_repository, RunTrigger, RunStatus
    store, source = operations
    runs = postgres_run_repository(_safe_test_dsn(), store.schema)
    row, _ = store.start(source, 'PLAN')
    value = plan(source)
    store.execute(row, lambda: value)
    finished = store.plan_time(source, row['operation_id'])
    run = runs.start_run(source, 'proxmox', RunTrigger.MANUAL, 'test')
    assert not runs.plan_used(source, value['digest'], finished)
    runs.bind_plan(run.run_id, value['digest'], value['planner_version'])
    reopened = postgres_run_repository(_safe_test_dsn(), store.schema)
    assert reopened.plan_used(source, value['digest'], finished)
    assert reopened.plan_run(source, value['digest'], finished) == str(run.run_id)
    assert reopened.get_run(run.run_id).status == RunStatus.RUNNING
    with pytest.raises(ValueError, match='already bound'):
        reopened.bind_plan(run.run_id, value['digest'], value['planner_version'])
    runs.finish_run(run.run_id, RunStatus.OUTCOME_UNCERTAIN,
                    error_code='OUTCOME_UNCERTAIN', error_message_safe='The final NetBox state may be uncertain.')
    assert reopened.plan_used(source, value['digest'], finished)
    fresh, _ = store.start(source, 'PLAN')
    store.execute(fresh, lambda: value)
    assert not reopened.plan_used(source, value['digest'], store.plan_time(source, fresh['operation_id']))


def test_unknown_plan_failure_logs_class_frames_and_phase(operations, caplog):
    import json
    store, source = operations
    row, _ = store.start(source, 'PLAN')
    store.execute(row, lambda: None)
    events=[json.loads(record.message) for record in caplog.records if record.message.startswith('{')]
    failure=next(e for e in events if e.get('event_id')==str(row['operation_id']))
    assert failure['exception_class']=='AttributeError'
    assert failure['frames'] and failure['phase']=='result_validation'
    assert failure['duration_ms']>=0


def test_structured_conflict_survives_worker_reopen(operations):
    import json
    from netbox_sync.application.inventory_conflicts import InventoryConflict, ConflictParticipant
    from netbox_sync.application.sync_plan import SyncPlanItem, SyncAction
    from netbox_sync.api.dto import SyncPlanDTO
    store, source = operations
    conflict = InventoryConflict('VM_IDENTITY', 'uuid', (
        ConflictParticipant('VM A', 'uuid', 'vm-1', 'host'),
        ConflictParticipant('VM B', 'uuid', 'vm-2', 'host')))
    value = SyncPlan(source, source, 'proxmox', 's', 't', 'p', 'n', (
        SyncPlanItem('vm', 'uuid', 'VM', SyncAction.BLOCKED, 'VM_IDENTITY', 'Inventory conflict'),),
        conflicts=(conflict,))
    payload = json.loads(value.canonical_json()) | {'digest': value.digest}
    row, _ = store.start(source, 'PLAN')
    store.execute(row, lambda: payload)
    reopened = OperationStore(_safe_test_dsn(), store.schema)
    saved = reopened.latest(source)[0]
    assert saved['status'] == 'READY' and saved['safe_error_code'] is None
    public = SyncPlanDTO.from_worker(saved['result'])
    assert not public.apply_allowed
    assert {p.provider_object_id for p in public.conflicts[0].participants} == {'vm-1', 'vm-2'}
