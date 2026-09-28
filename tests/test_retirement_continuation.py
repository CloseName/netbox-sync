"""Actual PostgreSQL journal, restart and consent gates for automatic continuation."""
from tests.test_retirement_journal_postgres import coordinator, prepare, execute
from tests.test_source_lifecycle_postgres import lifecycle
from tests.test_migrations_postgres import migration_database
from netbox_sync.retirement_continuation import RetirementContinuation
from netbox_sync.retirement_coordinator import RetirementCoordinator
from netbox_sync.local_control import ControlError
import pytest


@pytest.mark.parametrize('committed', [False, True])
def test_restart_continues_exact_confirmed_intent(coordinator, committed):
    service, _, _, remote, _ = coordinator
    source, current, review = prepare(coordinator)
    original = remote.call
    def disconnected(action, operation, **fields):
        if action == 'execute':
            if committed:
                original(action, operation, **fields)
            raise ControlError('RETIREMENT_UNCERTAIN')
        return original(action, operation, **fields)
    remote.call = disconnected
    assert execute(service, source, current, review)['state'] == 'UNCERTAIN'
    remote.call = original
    restarted = RetirementCoordinator(service.store, remote, lambda _: None)
    continuation = RetirementContinuation(restarted)
    continuation()
    assert restarted.status(source, review['operation_id'], 'admin-fixture')['state'] == 'FINALIZED'
    assert remote.writes == 1
    continuation()
    assert remote.writes == 1


def test_unconfirmed_review_never_auto_executes(coordinator):
    service, _, _, remote, _ = coordinator
    source, _, review = prepare(coordinator)
    RetirementContinuation(service)()
    assert remote.writes == 0
    assert service.status(source, review['operation_id'], 'admin-fixture')['state'] == 'READY'


def test_changed_receipt_never_auto_executes(coordinator, caplog):
    service, _, _, remote, _ = coordinator
    source, current, review = prepare(coordinator)
    service.journal.begin(source, review['operation_id'], 'admin-fixture', review['digest'], current['display_name'], True)
    remote.result = {**remote.result, 'digest': 'f' * 64}
    RetirementContinuation(service)()
    assert remote.writes == 0
    assert service.status(source, review['operation_id'], 'admin-fixture')['state'] == 'SENDING'
    assert 'RETIREMENT_CONFLICT' in caplog.text


def test_db_failure_does_not_leak_exception_or_stop_server(coordinator, monkeypatch, caplog):
    service, *_ = coordinator
    def unavailable():
        raise RuntimeError('password=NEVER_PRINT_TEST_MARKER')
    monkeypatch.setattr(service.store, 'connect', unavailable)
    RetirementContinuation(service)()
    assert 'LIFECYCLE_UNAVAILABLE' in caplog.text
    assert 'NEVER_PRINT_TEST_MARKER' not in caplog.text


def test_concurrent_continuations_send_one_write(coordinator):
    from concurrent.futures import ThreadPoolExecutor
    service, _, _, remote, _ = coordinator
    source, current, review = prepare(coordinator)
    service.journal.begin(source, review['operation_id'], 'admin-fixture', review['digest'], current['display_name'], True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: RetirementContinuation(service)(), range(2)))
    assert remote.writes == 1
    assert service.status(source, review['operation_id'], 'admin-fixture')['state'] == 'FINALIZED'


def test_busy_namespace_keeps_original_confirmed_operation(coordinator):
    from uuid import uuid4
    from netbox_sync.source_lifecycle import LifecycleError
    service, _, _, remote, _ = coordinator
    source, current, review = prepare(coordinator)
    original = remote.call
    def busy(action, operation, **fields):
        if action == 'execute':raise ControlError('RETIREMENT_SERVER_BUSY')
        return original(action, operation, **fields)
    remote.call = busy
    waiting = execute(service, source, current, review)
    assert waiting['state'] == 'UNCERTAIN'
    assert waiting['safe_code'] == 'RETIREMENT_SERVER_BUSY'
    with pytest.raises(LifecycleError, match='SOURCE_RETIREMENT_PENDING'):
        service.review(source, uuid4(), 'admin-fixture', current['revision'], queued=True)
    assert remote.writes == 0
    remote.call = original
    RetirementContinuation(service)()
    assert service.status(source, review['operation_id'], 'admin-fixture')['state'] == 'FINALIZED'
    assert remote.writes == 1


def test_legacy_busy_refusal_resumes_by_reading_original_receipt(coordinator):
    service, _, _, remote, _ = coordinator
    source, current, review = prepare(coordinator)
    service.journal.begin(source, review['operation_id'], 'admin-fixture', review['digest'], current['display_name'], True)
    # Historical persisted result of SOURCE_NAMESPACE_BUSY before this fix.
    from psycopg import sql
    with service.store.connect() as connection:
        connection.execute(sql.SQL("UPDATE {} SET state='BLOCKED',safe_code='SOURCE_OPERATION_ACTIVE' WHERE operation_id=%s").format(service.store.table('source_retirements')),(review['operation_id'],))
    calls=[];original=remote.call
    def observed(action, operation, **fields):
        calls.append((action,str(operation)))
        return original(action, operation, **fields)
    remote.call=observed
    RetirementContinuation(service)()
    assert calls[0]==('receipt',review['operation_id'])
    assert remote.writes==1
    assert service.status(source,review['operation_id'],'admin-fixture')['state']=='FINALIZED'


@pytest.mark.parametrize('busy_older',[False,True])
def test_two_legacy_nonces_resolve_active_without_second_write(coordinator,busy_older):
    from uuid import uuid4
    from psycopg import sql
    from psycopg.types.json import Jsonb
    service, _, _, remote, _ = coordinator
    source, current, review = prepare(coordinator)
    service.journal.begin(source,review['operation_id'],'admin-fixture',review['digest'],current['display_name'],True)
    with service.store.connect() as connection:
        old=service.journal._record(connection,source,review['operation_id'],'admin-fixture')
        other=uuid4();plan={**old['plan'],'remote':{**old['plan']['remote'],'nonce':str(other)}}
        connection.execute(sql.SQL("INSERT INTO {} (operation_id,source_instance,actor_id,revision,guard_instance,plan,state,safe_code,remove_credentials,created_at) VALUES (%s,%s,%s,%s,%s,%s,'BLOCKED','SOURCE_OPERATION_ACTIVE',true,clock_timestamp()+(%s * interval '1 second'))").format(service.store.table('source_retirements')),(other,source,old['actor_id'],old['revision'],old['guard_instance'],Jsonb(plan),-1 if busy_older else 1))
    calls=[];original=remote.call
    def observed(action,operation,**fields):
        calls.append((action,str(operation)))
        assert str(operation)==review['operation_id']
        return original(action,operation,**fields)
    remote.call=observed
    assert service.store.read(source)['retirement']['operation_id']==review['operation_id']
    from netbox_sync.source_lifecycle import LifecycleError
    with pytest.raises(LifecycleError,match='SOURCE_RETIREMENT_PENDING'):
        service.execute(source,other,'admin-fixture',review['digest'],current['display_name'],True,resume=True)
    assert not calls
    RetirementContinuation(service)()
    assert calls[0]==('receipt',review['operation_id'])
    assert remote.writes==1
    assert service.status(source,review['operation_id'],'admin-fixture')['state']=='FINALIZED'
