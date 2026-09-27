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
