"""Read-only API and health adapter tests; no external services are contacted."""

import json
import logging
from contextlib import AbstractContextManager
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from tests.auth_support import authenticated_app as create_app
from netbox_sync.api.database import PostgresHealthProbe
from netbox_sync.api.settings import ApiSettings
from netbox_sync.application.health import SystemHealthService

SECRET = 'FAKE_SECRET_MUST_NEVER_BE_RETURNED'


class FakeConnection(AbstractContextManager):
    """Connection/cursor spy proving the adapter performs SELECTs only."""

    def __init__(self, *, version='1', fail_registry=False):
        self.version = version
        self.fail_registry = fail_registry
        self.queries = []
        self.read_only = False
        self.closed = False

    def __exit__(self, *_args):
        self.closed = True

    def cursor(self):
        return self

    def execute(self, query):
        query = query if isinstance(query, str) else query.as_string()
        assert self.read_only
        assert query.startswith('SELECT ')
        self.queries.append(query)
        if self.fail_registry and 'schema_meta' in query:
            raise RuntimeError(SECRET)

    def fetchone(self):
        return (1,) if self.queries[-1] == 'SELECT 1' else (self.version,)


def _client(connection=None, connector=None, *, configured=True):
    settings = ApiSettings(registry_dsn=SECRET, registry_schema='netbox_sync_test',
                           netbox_configured=configured)
    probe = PostgresHealthProbe(settings, connector=connector or (lambda *_args, **_kw: connection))
    service = SystemHealthService(probe, netbox_configured=configured)
    return TestClient(create_app(settings, service))


def test_liveness_does_not_connect_and_version_is_safe():
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Liveness must not connect')
    with _client(connector=forbidden) as client:
        assert client.get('/api/v1/health').json() == {'status': 'healthy'}
        version = client.get('/api/v1/version').json()
        assert version['name'] == 'NetBox Sync'
        assert isinstance(version['version'], str)
        assert SECRET not in json.dumps(version)


def test_healthy_database_and_unbaselined_registry():
    connection = FakeConnection()
    received = []
    def connector(*args, **kwargs):
        received.append((args, kwargs))
        return connection
    with _client(connector=connector) as client:
        response = client.get('/api/v1/system/health')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'healthy'
    assert set(data['components']) == {'api', 'application', 'database', 'registry', 'netbox'}
    assert data['components']['database']['status'] == 'healthy'
    assert data['components']['registry']['status'] == 'healthy'
    assert data['components']['netbox']['status'] == 'unknown'
    assert connection.closed
    assert len(connection.queries) == 3
    assert not any('alembic' in query or 'token' in query for query in connection.queries)
    assert received[0][1]['connect_timeout'] == 3
    assert 'default_transaction_read_only=on' in received[0][1]['options']


def test_database_failure_has_no_secret_or_raw_exception(caplog):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError(SECRET)
    with caplog.at_level(logging.INFO, logger='netbox_sync.api'), _client(connector=unavailable) as client:
        response = client.get('/api/v1/system/health')
    assert response.json()['status'] == 'unavailable'
    assert response.json()['components']['database']['error_code'] == 'REGISTRY_UNAVAILABLE'
    assert SECRET not in response.text
    assert SECRET not in caplog.text


@pytest.mark.parametrize('connection', [FakeConnection(version='99'), FakeConnection(fail_registry=True)])
def test_registry_failure_does_not_mark_database_unreachable(connection):
    with _client(connection) as client:
        data = client.get('/api/v1/system/health').json()
    assert data['components']['database']['status'] == 'healthy'
    assert data['components']['registry']['status'] == 'unavailable'
    assert SECRET not in json.dumps(data)


def test_absent_configuration_is_degraded_without_connecting():
    with TestClient(create_app(ApiSettings())) as client:
        data = client.get('/api/v1/system/health').json()
    assert data['status'] == 'degraded'
    assert data['components']['database']['status'] == 'unknown'


def test_request_id_is_server_generated_distinct_from_run_id(caplog):
    with caplog.at_level(logging.INFO, logger='netbox_sync.api'), _client() as client:
        first = client.get('/api/v1/health', headers={'X-Request-ID': SECRET})
        second = client.get('/api/v1/health')
    assert UUID(first.headers['X-Request-ID']) != UUID(second.headers['X-Request-ID'])
    records = [json.loads(record.message) for record in caplog.records if record.name == 'netbox_sync.api']
    assert all(record['component'] == 'api' and record['run_id'] is None for record in records)
    assert SECRET not in caplog.text


@pytest.mark.parametrize(('method', 'path', 'status', 'code'), [
    ('get', '/api/v1/not-found', 404, 'API_NOT_FOUND'),
    ('post', '/api/v1/system/health', 405, 'API_METHOD_NOT_ALLOWED'),
    ('delete', '/api/v1/health', 405, 'API_METHOD_NOT_ALLOWED'),
])
def test_stable_api_errors_and_no_mutation_routes(method, path, status, code):
    with _client() as client:
        response = getattr(client, method)(path)
    assert response.status_code == status
    assert set(response.json()) == {'error'}
    assert response.json()['error']['code'] == code
    assert response.json()['error']['request_id'] == response.headers['X-Request-ID']


def test_internal_errors_and_invalid_inputs_are_sanitized(caplog):
    app = create_app(ApiSettings())
    @app.get('/test-failure')
    def fail():
        raise RuntimeError(SECRET)
    @app.get('/test-validation/{number}')
    def validated(number: int):
        return number
    with caplog.at_level(logging.INFO, logger='netbox_sync.api'), TestClient(app) as client:
        internal = client.get('/test-failure')
        invalid = client.get('/test-validation/' + SECRET)
    assert internal.status_code == 500
    assert internal.json()['error']['code'] == 'API_INTERNAL_ERROR'
    assert invalid.status_code == 422
    assert invalid.json()['error']['code'] == 'API_VALIDATION_FAILED'
    assert SECRET not in internal.text + invalid.text + caplog.text


def test_no_wildcard_cors_and_configuration_repr_hides_dsn():
    with _client() as client:
        response = client.get('/api/v1/health', headers={'Origin': 'https://untrusted.invalid'})
    assert 'access-control-allow-origin' not in response.headers
    assert SECRET not in repr(ApiSettings(registry_dsn=SECRET))


def test_frontend_serving_is_limited_to_build_assets(tmp_path):
    (tmp_path / 'index.html').write_text('<html>NetBox Sync</html>', encoding='utf-8')
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'private.txt').write_text(SECRET, encoding='utf-8')
    with TestClient(create_app(ApiSettings(web_dist=str(tmp_path)))) as client:
        assert client.get('/').status_code == 200
        assert client.get('/private.txt').status_code == 404
        response = client.get('/assets/%2e%2e/private.txt')
        assert response.status_code == 404
        assert SECRET not in response.text
