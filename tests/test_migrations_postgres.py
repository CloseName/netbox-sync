"""Opt-in migration tests, strictly scoped to a disposable PostgreSQL database."""

import uuid

import psycopg
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from psycopg import sql

from netbox_sync.source_registry import SourceRegistry
from tests.sample_data import sample_source_config
from tests.test_source_registry_postgres import _safe_test_dsn


@pytest.fixture
def migration_database():
    dsn = _safe_test_dsn()
    schema = 'netbox_sync_test_' + uuid.uuid4().hex
    connect = lambda: psycopg.connect(dsn)
    engine = sa.create_engine('postgresql+psycopg://', creator=connect)
    registry = SourceRegistry(connect, schema)
    try:
        yield registry, engine
    finally:
        engine.dispose()
        assert schema.startswith('netbox_sync_test_')
        with connect() as connection:
            connection.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))


def _upgrade(registry, engine):
    config = Config('alembic.ini')
    config.attributes['schema'] = registry.schema
    with engine.connect() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, 'head')


def test_clean_migration_and_legacy_runtime_interoperate(migration_database):
    registry, engine = migration_database
    _upgrade(registry, engine)
    assert registry.schema_version() == 1
    created = registry.create_source(sample_source_config())
    _upgrade(registry, engine)
    registry.initialize()
    assert registry.get_source(created.id) == created


def test_existing_populated_registry_is_preserved(migration_database):
    registry, engine = migration_database
    registry.initialize()
    before = registry.create_source(sample_source_config())
    _upgrade(registry, engine)
    _upgrade(registry, engine)
    assert registry.list_sources() == (before,)
    with engine.connect() as connection:
        marker = sa.Table('alembic_version', sa.MetaData(), schema=registry.schema,
                          autoload_with=connection)
        assert connection.execute(sa.select(marker.c.version_num)).scalar_one() == (
            '0006_auth_policy')
        inspector = sa.inspect(connection)
        assert inspector.has_table('sync_runs', schema=registry.schema)
        assert inspector.get_foreign_keys('sync_runs', schema=registry.schema) == []
        assert {item['name'] for item in inspector.get_indexes(
            'sync_runs', schema=registry.schema)} >= {
                'ix_sync_runs_started_at', 'ix_sync_runs_source_started',
                'ix_sync_runs_status', 'ix_sync_runs_trigger',
            }


def test_unknown_version_rolls_back_version_table(migration_database):
    registry, engine = migration_database
    registry.initialize()
    before = registry.create_source(sample_source_config())
    with engine.begin() as connection:
        meta = sa.Table('schema_meta', sa.MetaData(), schema=registry.schema, autoload_with=connection)
        connection.execute(meta.update().where(meta.c.key == 'schema_version').values(value='99'))
    with pytest.raises(RuntimeError, match='Unsupported'):
        _upgrade(registry, engine)
    with engine.connect() as connection:
        assert not sa.inspect(connection).has_table('alembic_version', schema=registry.schema)
    assert registry.get_source(before.id) == before


def test_partial_schema_is_not_stamped(migration_database):
    registry, engine = migration_database
    with engine.begin() as connection:
        connection.execute(sa.schema.CreateSchema(registry.schema))
        sa.Table('schema_meta', sa.MetaData(), sa.Column('key', sa.Text),
                 schema=registry.schema).create(connection)
    with pytest.raises(RuntimeError, match='Partial'):
        _upgrade(registry, engine)
    with engine.connect() as connection:
        assert set(sa.inspect(connection).get_table_names(schema=registry.schema)) == {'schema_meta'}
