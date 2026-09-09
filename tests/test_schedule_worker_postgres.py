"""Disposable PostgreSQL proof for the column-limited schedule writer."""

import secrets
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from netbox_sync.schedule_worker import ScheduleStore, ScheduleWorkerError
from netbox_sync.source_registry import SourceRegistry
from tests.sample_data import sample_source_config
from tests.test_source_registry_postgres import _safe_test_dsn


def test_schedule_writer_column_privileges_and_optimistic_update():
    dsn = _safe_test_dsn()
    schema = 'netbox_sync_test_' + uuid.uuid4().hex
    role = 'netbox_sync_schedule_' + uuid.uuid4().hex
    registry = SourceRegistry(lambda: psycopg.connect(dsn), schema)
    registry.initialize()
    registry.create_source(sample_source_config())
    try:
        with psycopg.connect(dsn) as connection:
            cursor = connection.cursor()
            password = secrets.token_urlsafe(32)
            cursor.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role),sql.Literal(password)))
            cursor.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(
                sql.Identifier(schema), sql.Identifier(role)))
            cursor.execute(sql.SQL('GRANT SELECT (source_instance, sync_enabled, '
                                   'sync_interval_seconds) ON {}.sources TO {}').format(
                sql.Identifier(schema), sql.Identifier(role)))
            cursor.execute(sql.SQL('GRANT UPDATE (sync_enabled, sync_interval_seconds) '
                                   'ON {}.sources TO {}').format(
                sql.Identifier(schema), sql.Identifier(role)))
            cursor.execute(sql.SQL('CREATE TABLE {}.sync_runs (id INTEGER)').format(
                sql.Identifier(schema)))
        role_dsn = make_conninfo(dsn, user=role, password=password)
        store = ScheduleStore(role_dsn, schema)
        result = store.update(dict(source_instance='pve-infra-test', sync_enabled=False,
                                   sync_interval_seconds=300, expected_sync_enabled=True,
                                   expected_sync_interval_seconds=600))
        assert result['sync_enabled'] is False and result['sync_interval_seconds'] == 300
        with pytest.raises(ScheduleWorkerError, match='SCHEDULE_CONFLICT'):
            store.update(dict(source_instance='pve-infra-test', sync_enabled=True,
                              sync_interval_seconds=600, expected_sync_enabled=True,
                              expected_sync_interval_seconds=600))
        with pytest.raises(ScheduleWorkerError, match='SOURCE_NOT_FOUND'):
            store.update(dict(source_instance='missing-source', sync_enabled=True,
                              sync_interval_seconds=600, expected_sync_enabled=False,
                              expected_sync_interval_seconds=600))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with psycopg.connect(role_dsn) as connection:
                connection.execute(sql.SQL('UPDATE {}.sources SET enabled=FALSE').format(
                    sql.Identifier(schema)))
        for statement in ('DELETE FROM {}.sources', 'TRUNCATE {}.sources',
                          "UPDATE {}.sources SET source_instance='x'",
                          "UPDATE {}.sources SET username='x'",
                          "UPDATE {}.sources SET token_secret_key='x'",
                          "UPDATE {}.sources SET settings='{{}}'::jsonb",
                          "INSERT INTO {}.sources(id) VALUES ('x')",
                          "INSERT INTO {}.schema_meta VALUES ('x','x')",
                          'INSERT INTO {}.sync_runs VALUES (1)',
                          'CREATE TABLE {}.forbidden (id INTEGER)'):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with psycopg.connect(role_dsn) as connection:
                    connection.execute(sql.SQL(statement).format(sql.Identifier(schema)))
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
            connection.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))
