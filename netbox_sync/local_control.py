"""Bounded peer-authenticated Unix transport for narrow control services."""
import json
import os
from pathlib import Path
import socket
import stat
import struct
import time


class ControlError(RuntimeError):
    def __init__(self, code='CONTROL_UNAVAILABLE'):
        self.code = code
        super().__init__(code)


def request(path, payload, timeout=10):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            deadline = time.monotonic() + timeout
            connection.settimeout(timeout)
            connection.connect(path)
            connection.sendall(json.dumps(payload).encode() + b'\n')
            raw = receive(connection, deadline)
        response = json.loads(raw)
        if response.get('ok') is not True:
            raise ControlError(response.get('error', 'CONTROL_UNAVAILABLE'))
        return response
    except ControlError:
        raise
    except Exception:
        raise ControlError() from None


def receive(connection, deadline):
    raw = b''
    while not raw.endswith(b'\n'):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or len(raw) >= 32768:
            raise ControlError('CONTROL_REQUEST_INVALID')
        connection.settimeout(remaining)
        chunk = connection.recv(32768 - len(raw))
        if not chunk:
            raise ControlError('CONTROL_REQUEST_INVALID')
        raw += chunk
    return raw


def serve(path, handler, allowed_uid=10001, concurrent=False):
    import fcntl
    import signal
    if concurrent:
        signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    path = Path(path)
    path.parent.mkdir(mode=0o755, exist_ok=True)
    info = path.parent.lstat()
    if path.parent.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
        raise ControlError('CONTROL_DIRECTORY_INVALID')
    directory = os.open(path.parent, os.O_DIRECTORY | os.O_NOFOLLOW)
    fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0:
            raise ControlError('CONTROL_SOCKET_INVALID')
        path.unlink()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        os.chown(path, 0, allowed_uid)
        os.chmod(path, 0o660)
        server.listen(16)
        while True:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(5)
                _, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if concurrent and uid == allowed_uid:
                    if os.fork():
                        continue
                    server.close()
                    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
                try:
                    if uid != allowed_uid:
                        raise ControlError('PEER_NOT_AUTHORIZED')
                    payload = json.loads(receive(connection, time.monotonic() + 5))
                    if not isinstance(payload, dict):
                        raise ControlError('CONTROL_REQUEST_INVALID')
                    result = handler(payload)
                    response = {'ok': True, 'result': result}
                except Exception as error:
                    # Only our closed error vocabulary can cross this boundary.
                    code = getattr(error, 'code', 'CONTROL_UNAVAILABLE')
                    response = {'ok': False, 'error': code if code in SAFE_CODES else 'CONTROL_UNAVAILABLE'}
                try:
                    connection.sendall(json.dumps(response).encode() + b'\n')
                except OSError:
                    pass
                if concurrent and uid == allowed_uid:
                    os._exit(0)


SAFE_CODES = frozenset({
    'CONTROL_UNAVAILABLE', 'CONTROL_REQUEST_INVALID', 'PEER_NOT_AUTHORIZED',
    'SOURCE_NOT_FOUND', 'SOURCE_ALREADY_REMOVED', 'SOURCE_LIFECYCLE_CONFLICT',
    'SOURCE_CONFIRMATION_INVALID', 'SOURCE_OPERATION_ACTIVE', 'SOURCE_APPLY_ACTIVE',
    'SOURCE_APPLY_UNCONFIRMED', 'LIFECYCLE_UNAVAILABLE', 'REQUEST_INVALID',
    'BOOTSTRAP_CONFLICT', 'BOOTSTRAP_NOT_READY', 'BOOTSTRAP_INVALID', 'BOOTSTRAP_BUSY',
})
