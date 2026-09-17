"""Discovery worker protocol and privilege-boundary tests."""

from io import BytesIO, StringIO
import json
import subprocess
from dataclasses import replace

import pytest

from netbox_sync.discovery_worker import (DiscoverySupervisor, WorkerError, _authorize_peer,
                                               _receive, _safe_environment, child_main)
from netbox_sync.source_config import SecretReference, SourceCredentials
from netbox_sync.secret_resolver import FileSecretResolver, SecretResolutionError
from tests.sample_data import sample_source_config


class Connection:
    def __init__(self, value):
        self.value = value
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def recv(self, _size):
        return self.value


class ChildInput:
    """Text-stream shape exposing bounded binary child input."""

    def __init__(self, payload):
        self.buffer = BytesIO(json.dumps(payload).encode())


def _run_child(monkeypatch, payload, execute):
    output, errors = StringIO(), StringIO()
    monkeypatch.setattr('netbox_sync.discovery_worker.execute_child', execute)
    monkeypatch.setattr('netbox_sync.discovery_worker.sys.stdin', ChildInput(payload))
    monkeypatch.setattr('netbox_sync.discovery_worker.sys.stdout', output)
    monkeypatch.setattr('netbox_sync.discovery_worker.sys.stderr', errors)
    child_main()
    return output.getvalue(), errors.getvalue()


def test_plan_child_redirects_executor_output_and_emits_only_json(monkeypatch):
    def execute(_payload):
        print('arbitrary guarded executor output')
        return {'apply_allowed': True, 'items': 26}

    output, errors = _run_child(
        monkeypatch, {'operation': 'plan', 'source': {}}, execute)
    assert json.loads(output) == {'result': {'apply_allowed': True, 'items': 26}}
    assert 'arbitrary guarded executor output' not in output
    assert 'arbitrary guarded executor output' in errors


def test_child_error_after_executor_output_remains_valid_json(monkeypatch):
    def execute(_payload):
        print('precheck output before error')
        raise WorkerError('PROVIDER_UNAVAILABLE')

    output, errors = _run_child(monkeypatch, {'operation': 'plan'}, execute)
    assert json.loads(output) == {'error': 'PROVIDER_UNAVAILABLE'}
    assert 'precheck output before error' not in output
    assert 'precheck output before error' in errors


def test_ordinary_discovery_child_transport_is_unchanged(monkeypatch):
    def execute(payload):
        assert payload == {'source_instance': 'pve-test'}
        print('provider diagnostic')
        return {'source_instance': 'pve-test', 'items': []}

    output, _errors = _run_child(monkeypatch, {'source_instance': 'pve-test'}, execute)
    assert json.loads(output) == {
        'result': {'source_instance': 'pve-test', 'items': []},
    }


def test_worker_accepts_only_source_instance():
    connection = Connection(json.dumps({'source_instance': 'pve-test'}).encode())
    assert _receive(connection) == ('pve-test', 'discover')
    assert connection.timeout == 5


@pytest.mark.parametrize('payload', [b'{', b'not-json', b'"text"'])
def test_worker_rejects_malformed_json(payload):
    with pytest.raises(WorkerError, match='REQUEST_INVALID'):
        _receive(Connection(payload))


@pytest.mark.parametrize('payload', [
    {'source_instance': 'INVALID'},
    {'source_instance': 'pve-test', 'secret_path': '/etc/shadow'},
    {'source_instance': 'pve-test', 'address': '127.0.0.1'},
    {'source_instance': 'pve-test', 'provider': 'arbitrary.module'},
])
def test_worker_rejects_malformed_or_capability_bearing_request(payload):
    with pytest.raises(WorkerError, match='REQUEST_INVALID'):
        _receive(Connection(json.dumps(payload).encode()))


def test_child_environment_excludes_credentials_and_database_capabilities(monkeypatch):
    monkeypatch.setenv('NETBOX_SYNC_REGISTRATION_DSN', 'WRITER_SECRET')
    monkeypatch.setenv('NETBOX_SYNC_DISCOVERY_REGISTRY_DSN', 'READER_SECRET')
    monkeypatch.setenv('NB_API_TOKEN', 'NETBOX_SECRET')
    monkeypatch.setenv('HTTPS_PROXY', 'PROXY_SECRET')
    environment = _safe_environment()
    serialized = json.dumps(environment)
    assert 'SECRET' not in serialized
    assert 'NETBOX_SYNC_REGISTRATION_DSN' not in environment
    assert set(environment) <= {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL',
                                'PYTHONDONTWRITEBYTECODE'}


def test_worker_rejects_wrong_peer_uid(monkeypatch):
    monkeypatch.setattr('netbox_sync.discovery_worker.socket.SO_PEERCRED', 17, raising=False)
    monkeypatch.setattr('netbox_sync.discovery_worker.struct.unpack', lambda *_args: (1, 10002, 10002))
    peer = type('Peer', (), {'getsockopt': lambda *_args: b'x' * 12})()
    with pytest.raises(WorkerError, match='PEER_FORBIDDEN'):
        _authorize_peer(peer, 10001)


def test_worker_secret_reads_are_bounded(tmp_path):
    (tmp_path / 'oversized').write_bytes(b'x' * 4097)
    resolver = FileSecretResolver(secret_root=tmp_path, source_secret_root=tmp_path,
                                  max_secret_bytes=4096)
    with pytest.raises(SecretResolutionError, match='maximum size'):
        resolver.resolve(SecretReference('file', 'oversized'))


class Process:
    def __init__(self, timeout=False):
        self.timeout = timeout
        self.returncode = 0
        self.killed = False
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def communicate(self, _payload=None, timeout=None):
        self.calls += 1
        if self.timeout and self.calls == 1:
            raise subprocess.TimeoutExpired('child', timeout)
        return (b'', b'') if self.killed else (json.dumps({'result': {
            'source_instance': 'pve-infra-test', 'source_type': 'proxmox',
            'site_slug': 'test-site', 'cluster_name': 'Test Cluster', 'items': [],
        }}).encode(), b'')

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def test_timeout_kills_reaps_and_next_request_can_succeed(tmp_path, monkeypatch):
    secret = 'WORKER_SECRET_SENTINEL'
    (tmp_path / 'token-id').write_text('token', encoding='utf-8')
    (tmp_path / 'token-secret').write_text(secret, encoding='utf-8')
    token = tmp_path / 'netbox-token'
    token.write_text(secret, encoding='utf-8')
    config = replace(sample_source_config(), credentials=SourceCredentials(
        'user', SecretReference('file', 'token-id'), SecretReference('file', 'token-secret')))
    processes = [Process(timeout=True), Process()]
    captured = []
    def popen(argv, **kwargs):
        captured.append((argv, kwargs))
        return processes.pop(0)
    supervisor = DiscoverySupervisor('reader', 'netbox_sync', tmp_path, tmp_path,
                                     'http://netbox.test', token, 10001, 10001, popen=popen)
    monkeypatch.setattr(supervisor, '_source', lambda _instance: config)
    with pytest.raises(WorkerError, match='DISCOVERY_TIMEOUT'):
        supervisor.run('pve-infra-test')
    assert supervisor.run('pve-infra-test')['items'] == []
    for argv, kwargs in captured:
        assert secret not in json.dumps(argv) + json.dumps(kwargs['env'])
        assert 'NETBOX_SYNC_REGISTRATION_DSN' not in kwargs['env']
