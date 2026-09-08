"""Dedicated Unix-socket supervisor for confirmed one-source manual sync."""
# pylint: disable=import-outside-toplevel,too-many-arguments,too-many-positional-arguments
# pylint: disable=too-many-instance-attributes,subprocess-popen-preexec-fn,no-member
# pylint: disable=line-too-long,missing-class-docstring,missing-function-docstring
# pylint: disable=too-few-public-methods,import-error,duplicate-code

import argparse
from contextlib import redirect_stdout
import json
import os
import re
import socket
import subprocess
import struct
import sys
from dataclasses import asdict
from pathlib import Path

import psycopg
from contextlib import nullcontext
from .source_operations import OperationStore, OperationError

from .application.confirmation import ConfirmationClaims, ConfirmationError, ConfirmationStore
from .discovery_worker import (_bounded_secret, _child_config, _config_payload, _drop_privileges,
                               _safe_environment)
from .run_history import (ActionCounts, RunStatus, RunTrigger, postgres_run_repository,
                          safe_error_code, safe_error_message, terminal_status)
from .source_config import SOURCE_INSTANCE_PATTERN
from .source_registry import SourceRegistry

MAX_REQUEST = 4096
MAX_RESPONSE = 8 * 1024 * 1024
CHILD_TIMEOUT = 300
DIGEST_PATTERN = re.compile(r'^[a-f0-9]{64}$')
TOKEN_PATTERN = re.compile(r'^[a-f0-9]{64}$')


class ApplyWorkerError(RuntimeError):
    """Stable, secret-free worker failure."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _discover(payload):
    """Build provider inventory inside the unprivileged child."""
    from proxmoxer import ProxmoxAPI
    from .esxi_client import EsxiClient
    from .esxi_discovery import discover_hosts as discover_esxi
    from .proxmox_discovery import discover_hosts as discover_proxmox
    source = dict(payload['source'])
    credentials = payload['credentials']
    source['username'] = credentials['username']
    config = _child_config(source)
    if config.source_type == 'proxmox':
        provider = ProxmoxAPI(
            config.address, user=credentials['username'],
            token_name=credentials['token_id'].split('!', 1)[-1],
            token_value=credentials['token_secret'], verify_ssl=config.verify_ssl)
        return config, discover_proxmox(provider, config)
    if config.source_type == 'esxi':
        class Resolved:
            def resolve(self, _reference):
                return credentials['token_secret']
        with EsxiClient(resolver=Resolved()).session(config) as service:
            return config, discover_esxi(service, config)
    raise ApplyWorkerError('SOURCE_UNSUPPORTED')


def _plan(nb_api, hosts, config):
    from .application.runtime_plan import build_runtime_plan
    return build_runtime_plan(nb_api, hosts, config)


def execute_child(payload):
    """Re-plan and optionally cross the guarded write boundary."""
    import pynetbox
    from .esxi_runtime import execute_esxi_runtime
    from .netbox_full_apply import apply_full_sync
    config, hosts = _discover(payload)
    nb_api = pynetbox.api(payload['netbox_url'], token=payload['netbox_token'])
    plan = _plan(nb_api, hosts, config)
    if payload['operation'] == 'plan':
        return {**plan.canonical_dict(), 'digest': plan.digest}
    if not plan.apply_allowed or plan.digest != payload.get('expected_digest'):
        raise ApplyWorkerError('PLAN_STALE')
    # Prove all provider-specific prechecks before entering the write call.
    try:
        if config.source_type == 'proxmox':
            apply_full_sync(nb_api, hosts, config.target, confirmed=False)
        else:
            execute_esxi_runtime(nb_api, hosts, config, confirmed=False)
    except Exception as exc:
        raise ApplyWorkerError('FAILED_BEFORE_WRITE') from exc
    try:
        if config.source_type == 'proxmox':
            apply_full_sync(nb_api, hosts, config.target, confirmed=True)
        else:
            execute_esxi_runtime(nb_api, hosts, config, confirmed=True)
    except Exception as exc:
        raise ApplyWorkerError('OUTCOME_UNCERTAIN') from exc
    return {'status': 'SUCCEEDED', 'plan_digest': plan.digest,
            'planner_version': plan.planner_version,
            'action_counts': ActionCounts.from_items(plan.items).__dict__}


def child_main():
    """Execute without logging secrets or exception text."""
    try:
        payload = json.loads(sys.stdin.buffer.read(MAX_RESPONSE + 1))
        with redirect_stdout(sys.stderr):
            value = execute_child(payload)
        result = {'result': value}
    except ApplyWorkerError as exc:
        result = {'error': exc.code}
    except Exception:  # pylint: disable=broad-exception-caught
        result = {'error': 'APPLY_FAILED'}
    sys.stdout.write(json.dumps(result))


class ApplySupervisor:
    """Own credentials, confirmation state, child lifecycle, and the shared apply lock."""

    def __init__(self, dsn, schema, secret_root, source_secret_root, netbox_url,
                 netbox_token_file, lock_path, child_uid=10001, child_gid=10001,
                 popen=subprocess.Popen, confirmations=None, run_repository=None):
        self._dsn, self._schema = dsn, schema
        self._secret_root, self._source_secret_root = secret_root, source_secret_root
        self._netbox_url, self._netbox_token_file = netbox_url, netbox_token_file
        self._lock_path = lock_path
        self._child_uid, self._child_gid, self._popen = child_uid, child_gid, popen
        self._confirmations = confirmations or ConfirmationStore()
        self._runs = run_repository
        self.operations = None

    def _source(self, instance):
        try:
            registry = SourceRegistry(lambda: psycopg.connect(
                self._dsn, connect_timeout=3,
                options='-c statement_timeout=3000 -c default_transaction_read_only=on'), self._schema)
            if registry.schema_version() != 1:
                raise ApplyWorkerError('REGISTRY_UNAVAILABLE')
            record = registry.get_by_source_instance(instance)
        except ApplyWorkerError:
            raise
        except Exception:
            raise ApplyWorkerError('REGISTRY_UNAVAILABLE') from None
        if record is None:
            raise ApplyWorkerError('SOURCE_NOT_FOUND')
        if not record.config.enabled:
            raise ApplyWorkerError('SOURCE_DISABLED')
        return record.config

    def _payload(self, config, operation, expected_digest=None):
        from .secret_resolver import FileSecretResolver, SecretResolutionError
        try:
            credentials = FileSecretResolver(
                secret_root=self._secret_root, source_secret_root=self._source_secret_root,
                max_secret_bytes=4096).resolve_credentials(config.credentials)
            netbox_url = self._netbox_url
            if os.environ.get('NETBOX_SYNC_NETBOX_CONFIG_FILE'):
                from .bootstrap_state import runtime_netbox
                netbox_url, token = runtime_netbox(os.environ['NETBOX_SYNC_NETBOX_CONFIG_FILE'], 'apply')
            else:
                token = _bounded_secret(self._netbox_token_file)
        except (SecretResolutionError, OSError):
            raise ApplyWorkerError('CREDENTIAL_UNAVAILABLE') from None
        return {'source': _config_payload(config), 'credentials': asdict(credentials),
                'netbox_url': netbox_url, 'netbox_token': token,
                'operation': operation, 'expected_digest': expected_digest}

    def _child(self, payload):
        operation = payload['operation']
        raw = json.dumps(payload).encode()
        try:
            with self._popen([sys.executable, '-B', '-m', 'netbox_sync.apply_worker', '--child'],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             env=_safe_environment(), preexec_fn=_drop_privileges(
                                 self._child_uid, self._child_gid) if os.name == 'posix' else None) as process:
                try:
                    output, _ = process.communicate(raw, timeout=CHILD_TIMEOUT)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    code = ('FAILED_BEFORE_WRITE' if operation == 'plan'
                            else 'OUTCOME_UNCERTAIN')
                    raise ApplyWorkerError(code) from None
        finally:
            raw = b''
            payload = None
        if process.returncode or len(output) > MAX_RESPONSE:
            raise ApplyWorkerError('FAILED_BEFORE_WRITE' if operation == 'plan'
                                   else 'OUTCOME_UNCERTAIN')
        try:
            response = json.loads(output)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApplyWorkerError('FAILED_BEFORE_WRITE' if operation == 'plan'
                                   else 'OUTCOME_UNCERTAIN') from None
        if not isinstance(response, dict) or set(response) - {'result', 'error'}:
            raise ApplyWorkerError('FAILED_BEFORE_WRITE' if operation == 'plan'
                                   else 'OUTCOME_UNCERTAIN')
        if response.get('error'):
            allowed = {'PLAN_STALE', 'PLAN_BLOCKED', 'FAILED_BEFORE_WRITE',
                       'OUTCOME_UNCERTAIN', 'APPLY_FAILED', 'SOURCE_UNSUPPORTED'}
            code = response['error'] if response['error'] in allowed else 'APPLY_FAILED'
            raise ApplyWorkerError(code)
        if not isinstance(response.get('result'), dict):
            raise ApplyWorkerError('APPLY_FAILED')
        return response['result']

    def prepare(self, instance, digest, operation_id=None):
        """Recompute the exact current generation and bind its single-use token."""
        guard = self.operations.review_guard(instance, digest, operation_id) if self.operations else nullcontext()
        try:
            with guard:
                config = self._source(instance)
                plan = self._child(self._payload(config, 'plan'))
                if not plan['apply_allowed']:
                    raise ApplyWorkerError('PLAN_BLOCKED')
                if plan['digest'] != digest:
                    raise ApplyWorkerError('PLAN_STALE')
                claims = ConfirmationClaims(instance, config.id, digest, plan['planner_version'],
                    plan['source_fingerprint'], plan['target_fingerprint'], operation_id)
                return {'confirmation_token': self._confirmations.issue(claims), 'expires_in_seconds': 300}
        except OperationError as exc:
            raise ApplyWorkerError(exc.code) from None

    def apply(self, instance, token):
        """Consume, lock, reload and recompute before any write."""
        config = self._source(instance)
        run = self._runs.start_run(
            instance, config.source_type, RunTrigger.MANUAL, 'web/manual',
        ) if self._runs else None
        claims = None
        apply_started = False
        try:
            try:
                claims = self._confirmations.consume(token, instance)
            except ConfirmationError as exc:
                raise ApplyWorkerError(exc.code) from exc
            import fcntl  # pylint: disable=import-outside-toplevel
            try:
                lock_fd = os.open(
                    self._lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600,
                )
            except OSError:
                raise ApplyWorkerError('FAILED_BEFORE_WRITE') from None
            try:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    raise ApplyWorkerError('APPLY_LOCKED') from None
                guard = self.operations.review_guard(instance, claims.plan_digest, claims.operation_id) if self.operations else nullcontext()
                try:
                    with guard:
                        config = self._source(instance)
                        if config.id != claims.source_id:
                            raise ApplyWorkerError('PLAN_STALE')
                        apply_started = True
                        result = self._child(self._payload(config, 'apply', claims.plan_digest))
                        if result.get('plan_digest') != claims.plan_digest:
                            # The child may already have crossed the NetBox write boundary.
                            # A response-contract mismatch is therefore not a pre-write stale plan.
                            raise ApplyWorkerError('OUTCOME_UNCERTAIN')
                except OperationError as exc:
                    raise ApplyWorkerError(exc.code) from None
            finally:
                os.close(lock_fd)
            counts = ActionCounts(**result.pop('action_counts', {}))
            if run:
                self._runs.finish_run(
                    run.run_id, RunStatus.SUCCEEDED, counts, result['plan_digest'],
                    result.get('planner_version'),
                )
                result['run_id'] = str(run.run_id)
            result.pop('planner_version', None)
            return result
        except ApplyWorkerError as exc:
            if run:
                code = safe_error_code(exc.code)
                self._runs.finish_run(
                    run.run_id, terminal_status(code),
                    plan_digest=claims.plan_digest if claims else None,
                    planner_version=claims.planner_version if claims else None,
                    error_code=code, error_message_safe=safe_error_message(code),
                )
            raise
        except Exception as exc:
            code = 'OUTCOME_UNCERTAIN' if apply_started else 'APPLY_FAILED'
            if run:
                self._runs.finish_run(
                    run.run_id, terminal_status(code),
                    plan_digest=claims.plan_digest if claims else None,
                    planner_version=claims.planner_version if claims else None,
                    error_code=code, error_message_safe=safe_error_message(code),
                )
            raise ApplyWorkerError(code) from exc


def _receive(connection):
    connection.settimeout(5)
    chunks = []
    size = 0
    while True:
        chunk = connection.recv(min(4096, MAX_REQUEST + 1 - size))
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_REQUEST:
            raise ApplyWorkerError('REQUEST_INVALID')
        chunks.append(chunk)
    raw = b''.join(chunks)
    try:
        request = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ApplyWorkerError('REQUEST_INVALID') from None
    if request == {'operation': 'health'}:
        return request
    operation = request.get('operation') if isinstance(request, dict) else None
    allowed = ({'operation', 'source_instance', 'plan_digest'} if operation == 'prepare'
               else {'operation', 'source_instance', 'confirmation_token'})
    if operation == 'prepare' and isinstance(request, dict) and 'operation_id' in request:
        allowed = allowed | {'operation_id'}
        from uuid import UUID
        try:
            UUID(request['operation_id'])
        except (ValueError, TypeError, AttributeError):
            raise ApplyWorkerError('REQUEST_INVALID') from None
    if (not isinstance(request, dict) or set(request) != allowed
            or operation not in ('prepare', 'apply')
            or not SOURCE_INSTANCE_PATTERN.fullmatch(request.get('source_instance', ''))
            or (operation == 'prepare' and not DIGEST_PATTERN.fullmatch(
                request.get('plan_digest', '')))
            or (operation == 'apply' and not TOKEN_PATTERN.fullmatch(
                request.get('confirmation_token', '')))):
        raise ApplyWorkerError('REQUEST_INVALID')
    return request


def _authorize(connection, uid):
    if not hasattr(socket, 'SO_PEERCRED'):
        raise ApplyWorkerError('PEER_FORBIDDEN')
    _pid, peer_uid, _gid = struct.unpack('3i', connection.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
    if peer_uid != uid:
        raise ApplyWorkerError('PEER_FORBIDDEN')


def _handle_request(supervisor, request):
    """Answer health before any confirmation, lock, credential, or apply boundary."""
    if request['operation'] == 'health':
        return {'status': 'ok'}
    if request['operation'] == 'prepare':
        if 'operation_id' in request:
            return supervisor.prepare(request['source_instance'], request['plan_digest'], request['operation_id'])
        return supervisor.prepare(request['source_instance'], request['plan_digest'])
    return supervisor.apply(request['source_instance'], request['confirmation_token'])


def serve(socket_path, supervisor, allowed_uid):
    """Serve only fixed prepare/apply operations to the API UID."""
    path = Path(socket_path)
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(path))
        os.chown(path, 0, allowed_uid)
        os.chmod(path, 0o660)
        server.listen(8)
        while True:
            connection, _ = server.accept()
            with connection:
                try:
                    _authorize(connection, allowed_uid)
                    request = _receive(connection)
                    result = _handle_request(supervisor, request)
                    response = {'ok': True, 'result': result}
                except ApplyWorkerError as exc:
                    response = {'ok': False, 'error': exc.code}
                except Exception:  # pylint: disable=broad-exception-caught
                    response = {'ok': False, 'error': 'WORKER_INTERNAL_ERROR'}
                connection.sendall(json.dumps(response).encode())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--socket')
    parser.add_argument('--secret-root')
    parser.add_argument('--source-secret-root')
    parser.add_argument('--netbox-token-file')
    parser.add_argument('--lock-path', default='/run/netbox-sync/apply.lock')
    parser.add_argument('--api-uid', type=int, default=10001)
    parser.add_argument('--child-uid', type=int, default=10001)
    parser.add_argument('--child-gid', type=int, default=10001)
    args = parser.parse_args()
    if args.child:
        child_main()
        return
    supervisor = ApplySupervisor(
        os.environ.get('NETBOX_SYNC_APPLY_REGISTRY_DSN', ''),
        os.environ.get('NETBOX_SYNC_REGISTRY_SCHEMA', ''), args.secret_root,
        args.source_secret_root, os.environ.get('NETBOX_SYNC_APPLY_NB_API_URL', ''),
        args.netbox_token_file, args.lock_path, args.child_uid, args.child_gid,
        run_repository=postgres_run_repository(
            os.environ.get('NETBOX_SYNC_RUN_WRITER_DSN', ''),
            os.environ.get('NETBOX_SYNC_REGISTRY_SCHEMA', ''),
        ))
    supervisor.operations = OperationStore(supervisor._dsn, supervisor._schema)
    serve(args.socket, supervisor, args.api_uid)


if __name__ == '__main__':
    main()
