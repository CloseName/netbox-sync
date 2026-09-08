"""Dedicated Unix-socket supervisor for bounded, read-only discovery."""
# Platform APIs are Linux-only and provider imports are intentionally confined to the child.
# pylint: disable=no-member,import-outside-toplevel,too-few-public-methods
# pylint: disable=too-many-instance-attributes,too-many-arguments,too-many-positional-arguments
# pylint: disable=too-many-locals,subprocess-popen-preexec-fn

import argparse
from contextlib import redirect_stdout
import json
import logging
import os
import socket
import subprocess
import struct
import sys
import signal
import time
from dataclasses import asdict
from pathlib import Path

import psycopg

from .source_config import SOURCE_INSTANCE_PATTERN
from .source_registry import SourceRegistry
from .source_operations import OperationStore, OperationError

MAX_REQUEST = 512
MAX_RESPONSE = 8 * 1024 * 1024
REQUEST_TIMEOUT = 5
DISCOVERY_TIMEOUT = 120
MAX_SECRET = 4096


class WorkerError(RuntimeError):
    """One stable, secret-free worker failure."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _safe_environment():
    result = {key: value for key, value in os.environ.items()
              if key in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL')}
    result['PYTHONDONTWRITEBYTECODE'] = '1'
    return result


def _drop_privileges(uid, gid):
    def drop():
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
    return drop


def _bounded_secret(path):
    with Path(path).open('rb') as stream:
        value = stream.read(MAX_SECRET + 1)
    if len(value) > MAX_SECRET:
        raise OSError('secret exceeds limit')
    return value.decode('utf-8').strip()


class DiscoverySupervisor:
    """Resolve configuration/secrets, then execute provider code outside the root process."""

    def __init__(self, dsn, schema, secret_root, source_secret_root, netbox_url,
                 netbox_token_file, child_uid, child_gid, popen=subprocess.Popen):
        self._dsn = dsn
        self._schema = schema
        self._secret_root = secret_root
        self._source_secret_root = source_secret_root
        self._netbox_url = netbox_url
        self._netbox_token_file = netbox_token_file
        self._child_uid = child_uid
        self._child_gid = child_gid
        self._popen = popen
        self.operations = None

    def _source(self, instance):
        try:
            registry = SourceRegistry(lambda: psycopg.connect(
                self._dsn, connect_timeout=3,
                options='-c statement_timeout=3000 -c default_transaction_read_only=on'), self._schema)
            if registry.schema_version() != 1:
                raise WorkerError('REGISTRY_UNAVAILABLE')
            record = registry.get_by_source_instance(instance)
        except WorkerError:
            raise
        except Exception:
            raise WorkerError('REGISTRY_UNAVAILABLE') from None
        if record is None:
            raise WorkerError('SOURCE_NOT_FOUND')
        if not record.config.enabled:
            raise WorkerError('SOURCE_DISABLED')
        return record.config

    def run(self, instance, operation='discover'):
        """Resolve one source and execute its isolated child."""
        from .secret_resolver import FileSecretResolver, SecretResolutionError
        try:
            config = self._source(instance)
            resolver = FileSecretResolver(secret_root=self._secret_root,
                                          source_secret_root=self._source_secret_root,
                                          max_secret_bytes=MAX_SECRET)
            credentials = resolver.resolve_credentials(config.credentials)
            netbox_url = self._netbox_url
            if os.environ.get('NETBOX_SYNC_NETBOX_CONFIG_FILE'):
                from .bootstrap_state import runtime_netbox
                netbox_url, netbox_token = runtime_netbox(os.environ['NETBOX_SYNC_NETBOX_CONFIG_FILE'], 'read')
            else:
                netbox_token = _bounded_secret(self._netbox_token_file)
            if (not netbox_token or any(len(value.encode()) > MAX_SECRET for value in
                                        (credentials.token_id, credentials.token_secret))):
                raise OSError('empty token')
        except (SecretResolutionError, OSError):
            raise WorkerError('CREDENTIAL_UNAVAILABLE') from None
        payload = json.dumps({
            'source': _config_payload(config), 'credentials': asdict(credentials),
            'netbox_url': netbox_url, 'netbox_token': netbox_token,
            'operation': operation,
        }).encode()
        try:
            with self._popen([sys.executable, '-B', '-m', 'netbox_sync.discovery_worker', '--child'],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             env=_safe_environment(), preexec_fn=_drop_privileges(
                                 self._child_uid, self._child_gid) if os.name == 'posix' else None) as process:
                try:
                    output, _ = process.communicate(payload, timeout=DISCOVERY_TIMEOUT)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    raise WorkerError('DISCOVERY_TIMEOUT') from None
        finally:
            payload = b''
        if process.returncode or len(output) > MAX_RESPONSE:
            raise WorkerError('DISCOVERY_FAILED')
        try:
            result = json.loads(output)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise WorkerError('DISCOVERY_FAILED') from None
        if not isinstance(result, dict) or set(result) - {'result', 'error'}:
            raise WorkerError('DISCOVERY_FAILED')
        if result.get('error'):
            raise WorkerError(result['error'] if result['error'] in {
                'CREDENTIAL_UNAVAILABLE', 'PROVIDER_UNAVAILABLE', 'NETBOX_UNAVAILABLE',
                'DISCOVERY_FAILED'} else 'DISCOVERY_FAILED')
        return result.get('result')


def _config_payload(config):
    return {
        'id': config.id, 'source_instance': config.source_instance, 'name': config.name,
        'source_type': config.source_type, 'address': config.address, 'enabled': config.enabled,
        'sync_enabled': config.sync_enabled, 'sync_interval_seconds': config.sync_interval_seconds,
        'verify_ssl': config.verify_ssl, 'legacy_identity_owner': config.legacy_identity_owner,
        'settings': dict(config.settings), 'target': asdict(config.target),
    }


def _child_config(value):
    from .source_config import NetBoxTargetConfig, SecretReference, SourceConfig, SourceCredentials
    placeholder = SecretReference('env', 'DISPOSABLE_CHILD_VALUE')
    return SourceConfig(target=NetBoxTargetConfig(**value.pop('target')),
                        credentials=SourceCredentials(value.pop('username'), placeholder, placeholder), **value)


def execute_child(payload):
    """Discover and classify using read-only API objects only."""
    import pynetbox
    from proxmoxer import ProxmoxAPI
    from .application.discovery_review import build_esxi_review, build_proxmox_review
    from .application.runtime_plan import build_runtime_plan
    from .esxi_adoption import build_esxi_adoption_plan
    from .esxi_client import EsxiClient
    from .esxi_discovery import discover_hosts as discover_esxi
    from .proxmox_discovery import discover_hosts as discover_proxmox
    source = dict(payload['source'])
    credentials = payload['credentials']
    source['username'] = credentials['username']
    config = _child_config(source)
    nb_api = pynetbox.api(payload['netbox_url'], token=payload['netbox_token'])
    from .netbox_tls import configure_session
    configure_session(nb_api.http_session)
    if config.source_type == 'proxmox':
        token_name = credentials['token_id'].split('!', 1)[-1]
        provider = ProxmoxAPI(config.address, user=credentials['username'], token_name=token_name,
                              token_value=credentials['token_secret'], verify_ssl=config.verify_ssl)
        hosts = discover_proxmox(provider, config)
        review = build_proxmox_review(nb_api, hosts, config)
    elif config.source_type == 'esxi':
        class Resolved:
            """Ephemeral already-resolved ESXi password adapter."""
            def resolve(self, _reference):
                """Return the in-memory password without touching a file."""
                return credentials['token_secret']
        with EsxiClient(resolver=Resolved()).session(config) as service:
            hosts = discover_esxi(service, config)
        review = build_esxi_review(build_esxi_adoption_plan(nb_api, hosts, config), config)
    else:
        raise WorkerError('DISCOVERY_FAILED')
    if payload.get('operation') == 'plan':
        plan = build_runtime_plan(nb_api, hosts, config)
        return {**plan.canonical_dict(), 'digest': plan.digest}
    return asdict(review)


def child_main():
    """Execute one bounded stdin/stdout child request without logging."""
    logging.disable(logging.CRITICAL)
    try:
        raw = sys.stdin.buffer.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('payload too large')
        with redirect_stdout(sys.stderr):
            value = execute_child(json.loads(raw))
        result = {'result': value}
    except WorkerError as exc:
        result = {'error': exc.code}
    except Exception:  # pylint: disable=broad-exception-caught
        result = {'error': 'DISCOVERY_FAILED'}
    sys.stdout.write(json.dumps(result))


def _receive(connection):
    connection.settimeout(REQUEST_TIMEOUT)
    data = connection.recv(MAX_REQUEST + 1)
    if len(data) > MAX_REQUEST:
        raise WorkerError('REQUEST_INVALID')
    try:
        request = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise WorkerError('REQUEST_INVALID') from None
    if request == {'operation': 'health'}:
        return None, 'health'
    if isinstance(request, dict) and request.get('operation') == 'invalidate_plan':
        from uuid import UUID
        try:
            if set(request) != {'operation','source_instance','operation_id'} or not SOURCE_INSTANCE_PATTERN.fullmatch(request['source_instance']):
                raise ValueError()
            UUID(request['operation_id'])
        except (ValueError, TypeError, AttributeError):
            raise WorkerError('REQUEST_INVALID') from None
        return request['source_instance'], request
    if set(request) not in ({'source_instance'}, {'source_instance', 'operation'}) \
            or request.get('operation', 'discover') not in ('discover', 'plan', 'start_plan', 'start_discovery', 'operations') \
            or not SOURCE_INSTANCE_PATTERN.fullmatch(request.get('source_instance', '')):
        raise WorkerError('REQUEST_INVALID')
    return request['source_instance'], request.get('operation', 'discover')


def _authorize_peer(connection, allowed_uid):
    if not hasattr(socket, 'SO_PEERCRED'):
        raise WorkerError('PEER_FORBIDDEN')
    _pid, uid, _gid = struct.unpack('3i', connection.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
    if uid != allowed_uid:
        raise WorkerError('PEER_FORBIDDEN')


def _operation_public(row):
    return {key: (str(value) if key == 'operation_id' else value.isoformat()
                  if hasattr(value, 'isoformat') else value) for key, value in row.items()}


def _handle_request(supervisor, instance, operation, launch=None):
    """Own operation state outside HTTP; preserve injected test supervisors."""
    if operation == 'health':
        return {'status': 'ok'}
    store = getattr(supervisor, 'operations', None)
    if store is None:
        if operation in ('start_plan', 'start_discovery', 'operations'):
            raise WorkerError('OPERATIONS_UNAVAILABLE')
        return supervisor.run(instance, operation)
    if isinstance(operation, dict):
        store.invalidate_plan(instance, operation['operation_id'])
        return {}
    if operation == 'operations':
        return {'operations': [_operation_public(row) for row in store.latest(instance)]}
    kind = 'PLAN' if operation in ('plan', 'start_plan') else 'DISCOVERY'
    row, created = store.start(instance, kind)
    run = lambda: store.execute(row, lambda: supervisor.run(
        instance, 'plan' if kind == 'PLAN' else 'discover'))
    if operation.startswith('start_'):
        if created:
            launch(run)
        return {'operation': _operation_public(row)}
    if created:
        run()
    deadline = time.monotonic() + 130
    while time.monotonic() < deadline:
        current = next((item for item in store.latest(instance)
                        if item['operation_id'] == row['operation_id']), None)
        if current is None:
            raise WorkerError('PLAN_STALE')
        if current['status'] != 'RUNNING':
            if current['result'] is not None:
                return current['result']
            raise WorkerError(current['safe_error_code'] or 'OPERATION_FAILED')
        time.sleep(0.5)
    raise WorkerError('OPERATION_STILL_EXECUTING')


def serve(socket_path, supervisor, allowed_uid):
    """Serve the single-purpose protocol and authenticate every Unix peer."""
    import fcntl  # pylint: disable=import-outside-toplevel
    path = Path(socket_path)
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    lock_fd = os.open(path.parent / '.worker.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(lock_fd)
        raise WorkerError('WORKER_ALREADY_RUNNING') from exc
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(path))
        os.chown(path, 0, allowed_uid)
        os.chmod(path, 0o660)
        server.listen(32)
        signal.signal(signal.SIGCHLD, signal.SIG_IGN)
        while True:
            connection, _ = server.accept()
            try:
                _authorize_peer(connection, allowed_uid)
            except WorkerError as exc:
                try:
                    connection.sendall(json.dumps({'ok': False, 'error': exc.code}).encode())
                finally:
                    connection.close()
                continue
            pid = os.fork()
            if pid:
                connection.close()
                continue
            signal.signal(signal.SIGCHLD, signal.SIG_DFL)
            server.close()
            def launch(callback):
                worker_pid = os.fork()
                if worker_pid == 0:
                    connection.close()
                    try:
                        callback()
                    finally:
                        os._exit(0)
            with connection:
                try:
                    _authorize_peer(connection, allowed_uid)
                    instance, operation = _receive(connection)
                    result = {'ok': True, 'result': _handle_request(supervisor, instance, operation, launch)}
                except (WorkerError, OperationError) as exc:
                    result = {'ok': False, 'error': exc.code}
                except Exception:  # pylint: disable=broad-exception-caught
                    result = {'ok': False, 'error': 'WORKER_INTERNAL_ERROR'}
                try:
                    connection.sendall(json.dumps(result, separators=(',', ':')).encode())
                finally:
                    os._exit(0)


def main():
    """Start either the isolated child or single-purpose supervisor."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--socket')
    parser.add_argument('--registry-dsn')
    parser.add_argument('--registry-schema')
    parser.add_argument('--secret-root')
    parser.add_argument('--source-secret-root')
    parser.add_argument('--netbox-url')
    parser.add_argument('--netbox-token-file')
    parser.add_argument('--api-uid', type=int, default=10001)
    parser.add_argument('--child-uid', type=int, default=10001)
    parser.add_argument('--child-gid', type=int, default=10001)
    args = parser.parse_args()
    if args.child:
        child_main()
        return
    supervisor = DiscoverySupervisor(args.registry_dsn or os.environ.get('NETBOX_SYNC_DISCOVERY_REGISTRY_DSN', ''),
                                     args.registry_schema or os.environ.get('NETBOX_SYNC_REGISTRY_SCHEMA', ''),
                                     args.secret_root, args.source_secret_root,
                                     args.netbox_url or os.environ.get('NETBOX_SYNC_DISCOVERY_NB_API_URL', ''),
                                     args.netbox_token_file,
                                     args.child_uid, args.child_gid)
    supervisor.operations = OperationStore(
        os.environ.get('NETBOX_SYNC_OPERATION_WRITER_DSN', ''),
        args.registry_schema or os.environ.get('NETBOX_SYNC_REGISTRY_SCHEMA', ''))
    serve(args.socket, supervisor, args.api_uid)


if __name__ == '__main__':
    main()
