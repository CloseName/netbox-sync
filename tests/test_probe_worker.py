"""Isolated probe transport, privileges and fail-closed client regressions."""
from dataclasses import asdict
from unittest.mock import Mock, MagicMock
import pytest
from netbox_sync import probe_worker as worker
from netbox_sync.api.connection_probe import run_connection_test
from netbox_sync.api.egress import EgressPolicy
from netbox_sync.application.onboarding import PendingCredentials, OnboardingError
from netbox_sync.application.observability import ErrorCode


def credentials():
    return PendingCredentials('esxi', 'esxi.example.test', True, 'netbox-sync', '', 'fixture-only')


def test_handler_drops_child_identity_and_passes_only_ephemeral_payload(monkeypatch):
    execute = Mock()
    monkeypatch.setattr(worker, 'run_connection_test', execute)
    from netbox_sync.api.auth import AuthClient
    monkeypatch.setattr(AuthClient, 'call', lambda *a, **k: {'effective':asdict(EgressPolicy())})
    payload = {'credentials': asdict(credentials()), 'session':'unit-session', 'revision':0}
    assert worker.handle(payload) == {'success': True}
    assert execute.call_args.kwargs == {'child_uid': 10001}


@pytest.mark.parametrize('code', list(worker.CODES))
def test_safe_error_codes_cross_worker_boundary(monkeypatch, code):
    monkeypatch.setattr(worker, 'request', lambda *a, **k: {'ok': True, 'result': {'error': code.value}})
    with pytest.raises(OnboardingError) as error:
        worker.remote_test('/fixture.sock', credentials(), EgressPolicy())
    assert error.value.code == code


@pytest.mark.parametrize('result', [{'error': 'REMOTE_SECRET'}, {'success': True, 'extra': 'REMOTE_SECRET'}, None])
def test_bad_worker_responses_are_not_exposed(monkeypatch, result):
    monkeypatch.setattr(worker, 'request', lambda *a, **k: {'ok': True, 'result': result})
    with pytest.raises(OnboardingError) as error:
        worker.remote_test('/fixture.sock', credentials(), EgressPolicy())
    assert error.value.code == ErrorCode.SOURCE_CONNECTION_FAILED
    assert 'REMOTE_SECRET' not in str(error.value)


def test_probe_child_uid_and_credentials_are_not_argv_or_environment():
    popen = MagicMock()
    process = popen.return_value.__enter__.return_value
    process.communicate.return_value = (b'{"ok":true}', None)
    process.returncode = 0
    run_connection_test(credentials(), EgressPolicy(), popen=popen, child_uid=10001)
    kwargs = popen.call_args.kwargs
    assert (kwargs['user'], kwargs['group'], kwargs['extra_groups']) == (10001, 10001, [])
    assert credentials().secret not in str(popen.call_args)
    assert credentials().secret.encode() in process.communicate.call_args.args[0]

@pytest.mark.skipif(getattr(__import__('os'), 'geteuid', lambda: -1)() != 0, reason='Disposable Linux root Unix peers')
def test_real_socket_authorizes_api_uid_rejects_root_and_survives_restart():
    import json
    from pathlib import Path
    import subprocess
    import sys
    import tempfile
    from tests.test_first_run_transport import peer_request
    with tempfile.TemporaryDirectory(prefix='netbox-sync-probe-peer-') as directory:
        root = Path(directory)
        root.chmod(0o755)
        path = root / 'worker.sock'
        script = 'import sys; from netbox_sync.local_control import serve; from netbox_sync.probe_worker import handle; serve(sys.argv[1],handle,allowed_uid=10001)'
        for _ in range(2):
            process = subprocess.Popen([sys.executable, '-c', script, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                # Wait for a live listener, including replacement of a stale socket.
                import socket
                import time
                for _attempt in range(100):
                    assert process.poll() is None
                    try:
                        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                            connection.settimeout(5)
                            connection.connect(str(path))
                            assert json.loads(connection.recv(1024))['error'] == 'PEER_NOT_AUTHORIZED'
                        break
                    except (FileNotFoundError, ConnectionRefusedError):
                        time.sleep(.02)
                else: raise AssertionError('Worker listener unavailable')
                response = peer_request(path, {'unexpected': True})
                assert response.returncode != 0 and 'AUTH_REQUIRED' in response.stderr
                payload = {'credentials': asdict(credentials()) | {'address': '127.0.0.1'}, 'policy': asdict(EgressPolicy())}
                response = peer_request(path, payload)
                assert response.returncode != 0 and 'AUTH_REQUIRED' in response.stderr
                assert set(p.name for p in root.iterdir()) == {'worker.sock'}
            finally:
                process.terminate()
                process.wait(timeout=5)


def test_unavailable_worker_never_falls_back_to_api_probe(monkeypatch):
    def unavailable(*args, **kwargs): raise worker.ControlError()
    monkeypatch.setattr(worker, 'request', unavailable)
    local = Mock()
    monkeypatch.setattr(worker, 'run_connection_test', local)
    with pytest.raises(OnboardingError):
        worker.remote_test('/missing.sock', credentials(), EgressPolicy())
    local.assert_not_called()
