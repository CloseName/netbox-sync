"""Source visibility tests: isolated fakes, no source or database connections."""

import json
from contextlib import AbstractContextManager

import pytest
from fastapi.testclient import TestClient

from tests.auth_support import authenticated_app as create_app
from netbox_sync.api.settings import ApiSettings
from netbox_sync.api.source_reader import PostgresSourceReader, SOURCE_COLUMNS
from netbox_sync.application.sources import SourceVisibilityService
from netbox_sync.source_registry import SourceRegistry
from netbox_sync.secret_resolver import FileSecretResolver


SECRET = 'DO_NOT_EXPOSE_CREDENTIAL_SENTINEL'


def public_row(**changes):
    row = dict(source_instance='pve-test', source_type='proxmox', name='Proxmox test',
               address='pve.example.test', enabled=True, sync_enabled=True, verify_ssl=True,
               sync_interval_seconds=600, site_slug='test', cluster_name='Test', platform_slug='pve',
               device_role_slug='host', device_type_slug='server', cluster_type_slug='proxmox',
               legacy_identity_owner=True)
    row.update(changes)
    return row


class FakeReadConnection(AbstractContextManager):
    """Spy fails immediately for writes or non-allowlisted source columns."""

    def __init__(self, rows=(), fail=False, version='1'):
        self.rows = rows
        self.fail = fail
        self.version = version
        self.read_only = False
        self.queries = []

    def __exit__(self, *_args):
        return False

    def cursor(self, **_kwargs):
        return self

    def execute(self, query, params=()):
        text = query.as_string()
        assert self.read_only
        assert text.startswith('SELECT ')
        assert not any(word in text for word in ('username', 'token_', 'settings', 'alembic', 'SELECT *'))
        self.queries.append((text, params))
        if self.fail:
            raise RuntimeError(SECRET)

    def fetchone(self):
        return {'value': self.version}

    def fetchall(self):
        params = self.queries[-1][1]
        return [row for row in self.rows if not params or row['source_instance'] == params[0]]


def source_client(connection=None, *, settings=None, connector=None):
    settings = settings or ApiSettings(registry_dsn=SECRET, registry_schema='netbox_sync_test')
    reader = PostgresSourceReader(settings, connector=connector or (lambda *_args, **_kw: connection))
    return TestClient(create_app(settings, source_service=SourceVisibilityService(reader)))


@pytest.fixture(autouse=True)
def prohibit_runtime(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Registry initialization and secret resolution forbidden')
    monkeypatch.setattr(SourceRegistry, 'initialize', forbidden)
    monkeypatch.setattr(FileSecretResolver, 'resolve', forbidden)


def test_empty_source_list():
    with source_client(FakeReadConnection()) as client:
        response = client.get('/api/v1/sources')
    assert response.status_code == 200
    assert response.json() == {'sources': []}


def test_source_list_detail_safe_mapping_and_select_only(caplog):
    row = public_row(username=SECRET, token_id_key=SECRET, settings={'private': SECRET}, id=SECRET)
    connection = FakeReadConnection([row])
    with source_client(connection) as client:
        listed = client.get('/api/v1/sources')
        detail = client.get('/api/v1/sources/pve-test')
    assert listed.status_code == detail.status_code == 200
    assert listed.json()['sources'] == [detail.json()]
    assert detail.json()['status'] == 'enabled'
    assert set(detail.json()) == (set(SOURCE_COLUMNS) - {'source_type'}) | {'type', 'status'}
    assert SECRET not in listed.text + detail.text + caplog.text
    assert connection.queries[-1][1] == ('pve-test',)
    assert 'pve-test' not in connection.queries[-1][0]


@pytest.mark.parametrize(('enabled', 'sync_enabled', 'status'), [
    (True, True, 'enabled'), (True, False, 'sync_disabled'), (False, True, 'disabled'),
    (False, False, 'disabled'),
])
def test_source_configuration_status(enabled, sync_enabled, status):
    with source_client(FakeReadConnection([public_row(enabled=enabled, sync_enabled=sync_enabled)])) as client:
        assert client.get('/api/v1/sources').json()['sources'][0]['status'] == status


@pytest.mark.parametrize('instance', ['missing-source', 'INVALID'])
def test_source_not_found_envelope(instance):
    with source_client(FakeReadConnection()) as client:
        response = client.get('/api/v1/sources/' + instance)
    assert response.status_code == 404
    assert response.json()['error'] == dict(code='SOURCE_NOT_FOUND', message='Source not found',
                                           request_id=response.headers['X-Request-ID'])


@pytest.mark.parametrize('path', ['/api/v1/sources', '/api/v1/sources/pve-test'])
def test_registry_failure_is_safe(path, caplog):
    with source_client(FakeReadConnection(fail=True)) as client:
        response = client.get(path, headers={'X-Request-ID': SECRET})
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'REGISTRY_UNAVAILABLE'
    assert response.json()['error']['request_id'] == response.headers['X-Request-ID']
    assert SECRET not in response.text + caplog.text


@pytest.mark.parametrize('settings', [ApiSettings(), ApiSettings(registry_dsn=SECRET, registry_schema='bad;schema')])
def test_unconfigured_or_invalid_schema_never_connects(settings):
    calls = []
    with source_client(settings=settings, connector=lambda *_a, **_k: calls.append(True)) as client:
        response = client.get('/api/v1/sources')
    assert response.status_code == 503
    assert calls == []


@pytest.mark.parametrize('changes', [
    {'address': 'https://user:password@example.test'}, {'address': 'example.test?token=' + SECRET},
    {'address': 'https://example.test/' + SECRET}, {'enabled': 'true'}, {'sync_interval_seconds': True},
    {'source_type': 'unsupported'}, {'site_slug': None},
])
def test_malformed_or_sensitive_metadata_fails_closed(changes):
    with source_client(FakeReadConnection([public_row(**changes)])) as client:
        response = client.get('/api/v1/sources')
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'SOURCE_DATA_INVALID'
    assert SECRET not in response.text


def test_unsupported_version_fails_before_reading_sources():
    connection = FakeReadConnection(version='99')
    with source_client(connection) as client:
        assert client.get('/api/v1/sources').status_code == 503
    assert len(connection.queries) == 1


def test_reader_passes_readonly_connection_timeouts():
    calls = []
    def connector(*_args, **kwargs):
        calls.append(kwargs)
        return FakeReadConnection()
    with source_client(connector=connector) as client:
        assert client.get('/api/v1/sources').status_code == 200
    assert calls == [dict(connect_timeout=3, options='-c statement_timeout=2000 -c default_transaction_read_only=on')]


def test_esxi_public_mapping_has_no_credential_reference():
    row = public_row(source_type='esxi', source_instance='esxi-test', legacy_identity_owner=False)
    with source_client(FakeReadConnection([row])) as client:
        data = client.get('/api/v1/sources/esxi-test').json()
    assert data['type'] == 'esxi'
    assert not any(key in json.dumps(data) for key in ('username', 'password', 'provider', 'token', 'settings'))
