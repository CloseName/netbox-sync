"""Opt-in source visibility against the disposable netbox_sync_test database only."""

import json
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from tests.auth_support import authenticated_app as create_app
from netbox_sync.api.settings import ApiSettings
from netbox_sync.source_registry import SourceRegistry
from tests.sample_data import sample_source_config
from tests.test_source_registry_postgres import _safe_test_dsn


@pytest.fixture
def source_database():
    dsn = _safe_test_dsn()
    schema = 'netbox_sync_test_' + uuid.uuid4().hex
    registry = SourceRegistry(lambda: psycopg.connect(dsn), schema)
    # Production APIs require the migrated lifecycle schema.
    from sqlalchemy import create_engine
    from tests.test_migrations_postgres import _upgrade
    engine = create_engine('postgresql+psycopg://', creator=lambda: psycopg.connect(dsn))
    _upgrade(registry, engine)
    engine.dispose()
    settings = ApiSettings(registry_dsn=dsn, registry_schema=schema)
    try:
        with TestClient(create_app(settings)) as client:
            yield registry, client
    finally:
        assert schema.startswith('netbox_sync_test_')
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def test_postgres_empty_source_list(source_database):
    _registry, client = source_database
    assert client.get('/api/v1/sources').json() == {'sources': []}


def test_postgres_source_list(source_database):
    registry, client = source_database
    before = registry.create_source(sample_source_config())
    response = client.get('/api/v1/sources')
    assert response.status_code == 200
    assert [source['source_instance'] for source in response.json()['sources']] == [before.config.source_instance]
    assert registry.list_sources() == (before,)


def test_postgres_source_detail(source_database):
    registry, client = source_database
    source = registry.create_source(sample_source_config())
    response = client.get('/api/v1/sources/' + source.config.source_instance)
    assert response.status_code == 200
    assert response.json()['cluster_name'] == source.config.target.cluster_name


def test_postgres_source_not_found(source_database):
    _registry, client = source_database
    response = client.get('/api/v1/sources/missing-source')
    assert response.status_code == 404
    assert response.json()['error']['code'] == 'SOURCE_NOT_FOUND'


def test_postgres_secret_references_excluded(source_database):
    registry, client = source_database
    config = sample_source_config()
    registry.create_source(config)
    body = client.get('/api/v1/sources').text
    fields = json.loads(body)['sources'][0]
    for key in ('credentials', 'username', 'token_id_key', 'token_secret_key', 'settings', 'id'):
        assert key not in fields
    assert config.credentials.token_id.key not in body
    assert config.credentials.token_secret.key not in body
