"""Root-run Unix-socket broker for exclusive, non-readable source secret storage."""
# Linux-only OS APIs are deliberately unavailable to Windows pylint inference.
# pylint: disable=no-member

import argparse
import base64
import json
import os
import re
import secrets
import socket
import stat as file_stat
import struct
import time
from pathlib import Path
from .source_lifecycle import LifecycleError


KEY_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{15,127}$')
OPERATION_PATTERN = re.compile(r'^[A-Za-z0-9_-]{20,128}$')
MAX_SECRET_BYTES = 4096
MAX_REQUEST_BYTES = 8192
REQUEST_DEADLINE = 5
XATTR_NAMES = {
    'operation': 'user.netbox_sync.operation',
    'receipt': 'user.netbox_sync.receipt',
    'complete': 'user.netbox_sync.complete',
}
LEGACY_XATTR_NAMES = {
    'operation': 'user.infra_sync.operation',
    'receipt': 'user.infra_sync.receipt',
    'complete': 'user.infra_sync.complete',
}


class BrokerError(Exception):
    """Safe broker failure carrying only an allowlisted code."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class SecretBrokerStore:
    """Operate beneath one pre-opened, root-owned directory without following links."""

    def __init__(self, root):
        root = Path(root)
        if not root.is_absolute() or '..' in root.parts:
            raise RuntimeError('Secret root must be an absolute directory')
        directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in root.parts[1:]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
            info = os.fstat(directory)
            if info.st_uid != 0 or info.st_gid != 0 or file_stat.S_IMODE(info.st_mode) != 0o700:
                raise RuntimeError('Secret root must be a root-owned 0700 directory')
        except Exception:
            os.close(directory)
            raise
        if not file_stat.S_ISDIR(info.st_mode):
            os.close(directory)
            raise RuntimeError('Secret root must be a root-owned 0700 directory')
        self._directory = directory

    def singleton(self):
        """Lock the root inode, never a replaceable lock filename; retained until process exit."""
        import fcntl  # pylint: disable=import-outside-toplevel,import-error
        fcntl.flock(self._directory, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlink_owned(self, descriptor, key, attributes):
        """Recheck immediately before unlink. Dedicated root + singleton exclude peer writers.

        Linux stdlib has no unlink-by-fd: an external privileged writer could still
        race this check. Host administrators must not mutate the active directory.
        """
        info = os.fstat(descriptor)
        if (not file_stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
                or info.st_nlink != 1 or file_stat.S_IMODE(info.st_mode) != 0o600):
            raise BrokerError('ROLLBACK_NOT_AUTHORIZED')
        for name, value in attributes.items():
            if os.getxattr(descriptor, name) != value:
                raise BrokerError('ROLLBACK_NOT_AUTHORIZED')
        current = os.stat(key, dir_fd=self._directory, follow_symlinks=False)
        if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
            raise BrokerError('ROLLBACK_NOT_AUTHORIZED')
        os.unlink(key, dir_fd=self._directory)
        os.fsync(self._directory)

    @staticmethod
    def _stored_attributes(descriptor):
        """Read one complete legacy/new receipt set and reject mixed conflicts."""
        present = set(os.listxattr(descriptor))
        complete = []
        for names in (XATTR_NAMES, LEGACY_XATTR_NAMES):
            selected = set(names.values()).intersection(present)
            if selected and selected != set(names.values()):
                raise BrokerError('ROLLBACK_NOT_AUTHORIZED')
            if selected:
                complete.append({key: os.getxattr(descriptor, name)
                                 for key, name in names.items()})
        if not complete or any(values != complete[0] for values in complete[1:]):
            raise BrokerError('ROLLBACK_NOT_AUTHORIZED')
        names = XATTR_NAMES if set(XATTR_NAMES.values()).issubset(present) else LEGACY_XATTR_NAMES
        return complete[0], {names[key]: value for key, value in complete[0].items()}

    @staticmethod
    def _key(key):
        if (not isinstance(key, str) or not KEY_PATTERN.fullmatch(key) or key in ('.', '..')
                or '%' in key or '/' in key or '\\' in key):
            raise BrokerError('SECRET_KEY_INVALID')
        return key

    def create(self, operation_id, key, secret_value):
        """Exclusively create and fsync one root-owned 0600 regular file."""
        key = self._key(key)
        _operation(operation_id)
        try:
            value = base64.b64decode(secret_value, validate=True)
        except (ValueError, TypeError):
            raise BrokerError('SECRET_VALUE_INVALID') from None
        if not value or len(value) > MAX_SECRET_BYTES or b'\x00' in value:
            raise BrokerError('SECRET_VALUE_INVALID')
        descriptor = None
        rollback_token = secrets.token_urlsafe(32)
        attributes = {}
        try:
            descriptor = os.open(
                key, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self._directory,
            )
            os.fchmod(descriptor, 0o600)
            os.fchown(descriptor, 0, 0)
            os.setxattr(descriptor, XATTR_NAMES['operation'], operation_id.encode())
            attributes[XATTR_NAMES['operation']] = operation_id.encode()
            os.setxattr(descriptor, XATTR_NAMES['receipt'], rollback_token.encode())
            attributes[XATTR_NAMES['receipt']] = rollback_token.encode()
            written = 0
            while written < len(value):
                count = os.write(descriptor, value[written:])
                if count <= 0:
                    raise OSError('Secret write failed')
                written += count
            os.fsync(descriptor)
            os.setxattr(descriptor, XATTR_NAMES['complete'], b'1')
            attributes[XATTR_NAMES['complete']] = b'1'
            os.fsync(descriptor)
        except FileExistsError:
            return self._repeat_create(operation_id, key, value)
        except OSError:
            if descriptor is not None:
                try:
                    self._unlink_owned(descriptor, key, attributes)
                except (OSError, BrokerError):
                    pass
            raise BrokerError('SECRET_CREATE_FAILED') from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
        os.fsync(self._directory)
        return rollback_token

    def _repeat_create(self, operation_id, key, value):
        """A same-attempt replay returns its receipt, never overwrites file contents."""
        descriptor = None
        try:
            descriptor = os.open(key, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._directory)
            info = os.fstat(descriptor)
            stored, _attributes = self._stored_attributes(descriptor)
            if (not file_stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
                    or info.st_nlink != 1 or file_stat.S_IMODE(info.st_mode) != 0o600
                    or stored['operation'] != operation_id.encode()
                    or stored['complete'] != b'1'
                    or os.read(descriptor, MAX_SECRET_BYTES + 1) != value):
                raise BrokerError('SECRET_ALREADY_EXISTS')
            os.fsync(descriptor)
            os.fsync(self._directory)
            return stored['receipt'].decode()
        except OSError:
            raise BrokerError('SECRET_ALREADY_EXISTS') from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def rollback(self, operation_id, key, rollback_token):
        """Delete only a file carrying this attempt's durable rollback capability."""
        key = self._key(key)
        _operation(operation_id)
        descriptor = None
        try:
            descriptor = os.open(key, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._directory)
            info = os.fstat(descriptor)
            current = os.stat(key, dir_fd=self._directory, follow_symlinks=False)
            stored, attributes = self._stored_attributes(descriptor)
            if (not file_stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
                    or info.st_nlink != 1 or file_stat.S_IMODE(info.st_mode) != 0o600
                    or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)
                    or stored['operation'] != operation_id.encode()
                    or stored['complete'] != b'1'
                    or not secrets.compare_digest(
                        stored['receipt'].decode(), rollback_token or '',
                    )):
                raise BrokerError('ROLLBACK_NOT_AUTHORIZED')
            self._unlink_owned(descriptor, key, attributes)
        except OSError:
            raise BrokerError('ROLLBACK_NOT_AUTHORIZED') from None
        finally:
            if descriptor is not None:
                os.close(descriptor)


    def remove_owned(self, keys):
        """Remove an exclusively referenced pair only after lifecycle authorization.

        Validate every file before unlinking any. The broker singleton and protected
        directory remain authoritative; callers never supply filesystem paths.
        """
        opened = []
        deleting = False
        try:
            for key in keys:
                key = self._key(key)
                descriptor = os.open(key, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                     dir_fd=self._directory)
                opened.append((descriptor, key, None))
                info = os.fstat(descriptor)
                stored, attributes = self._stored_attributes(descriptor)
                if (not file_stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
                        or info.st_nlink != 1 or file_stat.S_IMODE(info.st_mode) != 0o600
                        or stored['complete'] != b'1'
                        or not set(XATTR_NAMES.values()).issubset(set(attributes))):
                    return False
                opened[-1] = (descriptor, key, attributes)
            deleting = True
            for descriptor, key, attributes in opened:
                self._unlink_owned(descriptor, key, attributes)
            return True
        except BrokerError:
            if deleting:
                raise
            return False
        finally:
            for descriptor, _, _ in opened:
                os.close(descriptor)


def _operation(value):
    if not isinstance(value, str) or not OPERATION_PATTERN.fullmatch(value):
        raise BrokerError('OPERATION_ID_INVALID')
    return value


def _reply(connection, payload):
    try:
        connection.sendall(json.dumps(payload, separators=(',', ':')).encode() + b'\n')
    except OSError:
        # A lost acknowledgement must not kill the broker or authorize cleanup.
        pass


def serve(socket_path, secret_root, allowed_uid, lifecycle=None):
    """Serve one request per local authenticated Unix connection."""
    store = SecretBrokerStore(secret_root)
    store.singleton()
    path = Path(socket_path)
    path.parent.mkdir(mode=0o755, parents=False, exist_ok=True)
    parent = path.parent.lstat()
    if path.parent.is_symlink() or parent.st_uid != 0 or parent.st_mode & 0o022:
        raise RuntimeError('Unsafe socket directory')
    # Also exclude a second root configured against this same socket directory.
    import fcntl  # pylint: disable=import-outside-toplevel,import-error
    socket_directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    fcntl.flock(socket_directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if path.exists() or path.is_symlink():
        previous = path.lstat()
        if not file_stat.S_ISSOCK(previous.st_mode) or previous.st_uid != 0:
            raise RuntimeError('Refusing to replace non-broker socket path')
        path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    os.chown(path, 0, allowed_uid)
    os.chmod(path, 0o660)
    server.listen(16)
    while True:
        connection, _ = server.accept()
        with connection:
            connection.settimeout(5)
            _, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != allowed_uid:
                _reply(connection, {'ok': False, 'error': 'PEER_NOT_AUTHORIZED'})
                continue
            try:
                raw = read_request(connection)
                request = json.loads(raw)
                if isinstance(request, dict) and request.get('action') in ('source_lifecycle', 'remove_source'):
                    from .lifecycle_protocol import handle_lifecycle
                    _reply(connection, {'ok': True, 'result': handle_lifecycle(lifecycle, store, request)})
                    continue
                operation_id = _operation(request.get('operation_id'))
                if request.get('action') == 'create' and set(request) == {
                        'action', 'operation_id', 'key', 'value'}:
                    token = store.create(operation_id, request['key'], request['value'])
                    _reply(connection, {'ok': True, 'rollback_token': token})
                elif request.get('action') == 'rollback' and set(request) == {
                        'action', 'operation_id', 'key', 'rollback_token'}:
                    store.rollback(operation_id, request['key'], request['rollback_token'])
                    _reply(connection, {'ok': True})
                else:
                    raise BrokerError('OPERATION_NOT_ALLOWED')
            except (BrokerError, LifecycleError, json.JSONDecodeError) as exc:
                code = exc.code if isinstance(exc, (BrokerError, LifecycleError)) else 'REQUEST_INVALID'
                _reply(connection, {'ok': False, 'error': code})
            except Exception:  # pylint: disable=broad-exception-caught
                _reply(connection, {'ok': False, 'error': 'BROKER_INTERNAL_ERROR'})
            finally:
                request = None
                raw = b''


def read_request(connection, clock=time.monotonic):
    """Absolute receive budget: slow-drip clients cannot extend it per byte."""
    deadline = clock() + REQUEST_DEADLINE
    raw = b''
    while not raw.endswith(b'\n') and len(raw) <= MAX_REQUEST_BYTES:
        remaining = deadline - clock()
        if remaining <= 0:
            raise BrokerError('REQUEST_TIMEOUT')
        connection.settimeout(remaining)
        try:
            chunk = connection.recv(MAX_REQUEST_BYTES + 1 - len(raw))
        except TimeoutError:
            raise BrokerError('REQUEST_TIMEOUT') from None
        if not chunk:
            break
        raw += chunk
    if len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b'\n'):
        raise BrokerError('REQUEST_INVALID')
    return raw


def main():
    """Start only from explicit broker container configuration."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--socket', required=True)
    parser.add_argument('--secret-root', required=True)
    parser.add_argument('--allowed-uid', type=int, default=10001)
    arguments = parser.parse_args()
    try:
        from .source_lifecycle import LifecycleStore
        lifecycle = LifecycleStore(os.environ.get('NETBOX_SYNC_LIFECYCLE_WRITER_DSN', ''),
            os.environ.get('NETBOX_SYNC_REGISTRY_SCHEMA', ''),
            os.environ.get('NETBOX_SYNC_APPLY_LOCK_PATH', '/run/netbox-sync-lock/apply.lock'))
        serve(arguments.socket, arguments.secret_root, arguments.allowed_uid, lifecycle)
    except Exception:
        print(json.dumps({'component': 'secret_broker', 'error_code': 'BROKER_FAILED'}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
