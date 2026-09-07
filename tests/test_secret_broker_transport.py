"""Unix protocol and durable rollback proof across broker process restart."""

import json
import os
import socket
import subprocess
import sys
import time

import pytest

from netbox_sync.api.onboarding_adapters import BrokerSecretStore

pytestmark = pytest.mark.skipif(not hasattr(os, 'geteuid') or getattr(os, 'geteuid', lambda: -1)() != 0,
                                reason='Requires disposable Linux root container')


def start_broker(root, socket_path, uid=0):
    process = subprocess.Popen([
        sys.executable, '-m', 'netbox_sync.secret_broker', '--socket', str(socket_path),
        '--secret-root', str(root), '--allowed-uid', str(uid),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ,
        'NETBOX_SYNC_LIFECYCLE_WRITER_DSN': 'dbname=netbox_sync_test',
        'NETBOX_SYNC_REGISTRY_SCHEMA': 'netbox_sync_test'})
    for _attempt in range(100):
        if process.poll() is not None:
            raise AssertionError('Test broker did not start')
        try:
            with socket.socket(socket.AF_UNIX) as connection:
                connection.connect(str(socket_path))
            return process
        except OSError:
            time.sleep(0.02)
    process.terminate()
    process.wait(timeout=5)
    raise AssertionError('Test broker startup timeout')


def exchange(path, request):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(5)
        connection.connect(str(path))
        connection.sendall(json.dumps(request).encode() + b'\n')
        return json.loads(connection.recv(2048))


def test_no_read_list_or_arbitrary_file_operations(tmp_path):
    root = tmp_path / 'secrets'
    root.mkdir(mode=0o700)
    path = tmp_path / 'broker.sock'
    process = start_broker(root, path)
    try:
        for action in ('read', 'list', 'delete', 'write', 'chmod'):
            result = exchange(path, {'action': action, 'operation_id': 'operation-0123456789abcdef'})
            assert result == {'ok': False, 'error': 'OPERATION_NOT_ALLOWED'}
        assert list(root.iterdir()) == []
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_wrong_peer_uid_cannot_operate(tmp_path):
    root = tmp_path / 'secrets'
    root.mkdir(mode=0o700)
    path = tmp_path / 'broker.sock'
    process = start_broker(root, path, uid=10001)
    try:
        result = exchange(path, {})
        assert result == {'ok': False, 'error': 'PEER_NOT_AUTHORIZED'}
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_client_receipt_can_rollback_after_broker_restart(tmp_path):
    root = tmp_path / 'secrets'
    root.mkdir(mode=0o700)
    path = tmp_path / 'broker.sock'
    process = start_broker(root, path)
    client = BrokerSecretStore(str(path))
    try:
        receipt = client.create('src-transport-0123456789abcdef', 'FAKE_TEST_SECRET')
    finally:
        process.terminate()
        process.wait(timeout=5)
    process = start_broker(root, path)
    try:
        client.rollback(receipt)
        assert list(root.iterdir()) == []
    finally:
        process.terminate()
        process.wait(timeout=5)
