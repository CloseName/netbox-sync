"""Opt-in disposable PostgreSQL coverage for durable run history."""

from datetime import datetime, timedelta, timezone
import secrets
import uuid

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
import sqlalchemy as sa

from netbox_sync.run_history import ActionCounts, RunRepository, RunStatus, RunTrigger
from tests.test_source_registry_postgres import _safe_test_dsn


@pytest.fixture
def history_database():
    dsn = _safe_test_dsn()
    schema = 'netbox_sync_test_' + uuid.uuid4().hex
    connect = lambda: psycopg.connect(dsn)
    engine = sa.create_engine('postgresql+psycopg://', creator=connect)
    config = Config('alembic.ini')
    config.attributes['schema'] = schema
    with engine.connect() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, 'head')
    try:
        yield RunRepository(connect, schema), dsn
    finally:
        engine.dispose()
        with connect() as connection:
            connection.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(
                sql.Identifier(schema)))


def test_start_finish_duration_counts_and_snapshot_roundtrip(history_database):
    history_database, _dsn = history_database
    ticks = iter((datetime(2026, 1, 1, tzinfo=timezone.utc),
                  datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=1250)))
    repository = RunRepository(history_database._connection_factory,  # pylint: disable=protected-access
                               history_database.schema, clock=lambda: next(ticks))
    started = repository.start_run('pve-test', 'proxmox', RunTrigger.MANUAL, 'web/manual')
    assert started.status is RunStatus.RUNNING
    finished = repository.finish_run(
        started.run_id, RunStatus.SUCCEEDED, ActionCounts(create=2, update=3),
        'a' * 64, 'web-5a-1',
    )
    assert finished.duration_ms == 1250
    assert finished.counts == ActionCounts(create=2, update=3)
    assert (finished.source_instance, finished.source_type) == ('pve-test', 'proxmox')
    assert repository.get_run(started.run_id) == finished


def test_listing_is_newest_first_filtered_and_bounded(history_database):
    history_database, _dsn = history_database
    first = history_database.start_run('pve-a', 'proxmox', 'scheduled', 'system/scheduler')
    second = history_database.start_run('esxi-b', 'esxi', 'scheduled', 'system/scheduler')
    history_database.finish_run(first.run_id, RunStatus.FAILED,
                                error_code='APPLY_FAILED', error_message_safe='Synchronization failed.')
    history_database.finish_run(second.run_id, RunStatus.LOCKED,
                                error_code='APPLY_LOCKED',
                                error_message_safe='Another synchronization is already running.')
    assert {item.run_id for item in history_database.list_runs(trigger='scheduled')} == {
        first.run_id, second.run_id,
    }
    assert history_database.list_runs(source_type='esxi')[0].run_id == second.run_id
    assert history_database.list_runs(status='LOCKED', limit=1)[0].run_id == second.run_id
    with pytest.raises(ValueError, match='between'):
        history_database.list_runs(limit=201)


def test_repository_surface_has_no_delete_operation():
    assert not hasattr(RunRepository, 'delete_run')


def test_diagnostics_queries_return_latest_and_bounded_stale_runs(history_database):
    repository, _dsn = history_database
    now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
    ticks = iter((now - timedelta(hours=4), now - timedelta(hours=3),
                  now - timedelta(hours=1),
                  now - timedelta(hours=1) + timedelta(seconds=1)))
    diagnostic_repository = RunRepository(
        repository._connection_factory, repository.schema,  # pylint: disable=protected-access
        clock=lambda: next(ticks))
    stale = diagnostic_repository.start_run(
        'pve-test', 'proxmox', RunTrigger.SCHEDULED, 'system/scheduler')
    diagnostic_repository.start_run(
        'esxi-test', 'esxi', RunTrigger.SCHEDULED, 'system/scheduler')
    success = diagnostic_repository.start_run(
        'pve-test', 'proxmox', RunTrigger.MANUAL, 'web/manual')
    diagnostic_repository.finish_run(success.run_id, RunStatus.SUCCEEDED)

    latest = {item.source_instance: item for item in diagnostic_repository.latest_by_source()}
    assert latest['pve-test'].run_id == success.run_id
    assert diagnostic_repository.latest_by_source(status='SUCCEEDED')[0].run_id == success.run_id
    assert diagnostic_repository.latest_by_source(trigger='manual')[0].run_id == success.run_id
    bounded = diagnostic_repository.stale_running(now - timedelta(hours=2), limit=1)
    assert len(bounded) == 1 and bounded[0].run_id == stale.run_id


def test_narrow_run_writer_can_only_insert_and_finalize_history(history_database):
    repository, dsn = history_database
    role = 'netbox_sync_test_run_writer_' + uuid.uuid4().hex
    table = sql.Identifier(repository.schema, 'sync_runs')
    with psycopg.connect(dsn) as connection:
        password = secrets.token_urlsafe(32)
        connection.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role), sql.Literal(password)))
        connection.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(
            sql.Identifier(repository.schema), sql.Identifier(role)))
        connection.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
            table, sql.Identifier(role)))
        connection.execute(sql.SQL('''GRANT INSERT (
            run_id, source_instance, source_type, trigger, started_at, status,
            plan_digest, planner_version, created_by) ON {} TO {}''').format(
                table, sql.Identifier(role)))
        connection.execute(sql.SQL('''GRANT UPDATE (
            finished_at, duration_ms, status, plan_digest, planner_version,
            create_count, update_count, no_change_count, review_required_count,
            blocked_count, ignored_count, unsupported_count, retain_only_count,
            error_code, error_message_safe) ON {} TO {}''').format(
                table, sql.Identifier(role)))
    writer = RunRepository(lambda: psycopg.connect(make_conninfo(dsn, user=role, password=password)),
                           repository.schema)
    try:
        started = writer.start_run('pve-test', 'proxmox', 'manual', 'web/manual')
        assert writer.finish_run(started.run_id, RunStatus.SUCCEEDED).status is RunStatus.SUCCEEDED
        for statement in (sql.SQL('DELETE FROM {}').format(table),
                          sql.SQL('TRUNCATE {}').format(table),
                          sql.SQL('ALTER TABLE {} ADD COLUMN forbidden text').format(table),
                          sql.SQL('UPDATE {} SET enabled=false').format(
                              sql.Identifier(repository.schema, 'sources')),
                          sql.SQL("UPDATE {} SET value='2'").format(
                              sql.Identifier(repository.schema, 'schema_meta'))):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), psycopg.connect(
                    make_conninfo(dsn, user=role, password=password)) as connection:
                connection.execute(statement)
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            connection.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
