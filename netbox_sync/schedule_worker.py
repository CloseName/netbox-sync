"""Single-purpose Unix-socket worker for optimistic schedule updates."""
# Linux-only socket/ownership APIs are unavailable to Windows pylint inference.
# pylint: disable=no-member

import argparse
import json
import os
import socket
import struct
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .application.scheduling import validate_interval
from .source_config import SOURCE_INSTANCE_PATTERN
from .source_registry import SCHEMA_NAME_PATTERN

MAX_REQUEST = 2048


class ScheduleWorkerError(RuntimeError):
    """Safe closed worker error."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class ScheduleStore:
    """Column-limited conditional UPDATE boundary."""

    def __init__(self, dsn, schema, connector=psycopg.connect):
        if not dsn or not SCHEMA_NAME_PATTERN.fullmatch(schema or ''):
            raise ScheduleWorkerError('CONTROL_WORKER_UNAVAILABLE')
        self._dsn, self._schema, self._connector = dsn, schema, connector

    def update(self, request):
        """Atomically update only two schedule columns when expectations match."""
        table = sql.Identifier(self._schema, 'sources')
        try:
            with self._connector(self._dsn, connect_timeout=3,
                                 options='-c statement_timeout=3000') as connection:
                connection.row_factory = dict_row
                with connection.cursor() as cursor:
                    cursor.execute(sql.SQL('''UPDATE {} SET sync_enabled=%s,
                        sync_interval_seconds=%s
                        WHERE source_instance=%s AND sync_enabled=%s
                        AND sync_interval_seconds=%s
                        RETURNING source_instance, sync_enabled, sync_interval_seconds''').format(table), (
                            request['sync_enabled'], request['sync_interval_seconds'],
                            request['source_instance'], request['expected_sync_enabled'],
                            request['expected_sync_interval_seconds']))
                    row = cursor.fetchone()
                    if row is None:
                        cursor.execute(sql.SQL(
                            'SELECT 1 FROM {} WHERE source_instance=%s').format(table),
                            (request['source_instance'],))
                        raise ScheduleWorkerError(
                            'SCHEDULE_CONFLICT' if cursor.fetchone() else 'SOURCE_NOT_FOUND')
            return dict(row)
        except ScheduleWorkerError:
            raise
        except Exception:
            raise ScheduleWorkerError('CONTROL_REQUEST_FAILED') from None


def _receive(connection):
    connection.settimeout(5)
    chunks, size = [], 0
    while True:
        chunk = connection.recv(min(1024, MAX_REQUEST + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > MAX_REQUEST:
            raise ScheduleWorkerError('SCHEDULE_INVALID')
    raw = b''.join(chunks)
    try:
        request = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ScheduleWorkerError('SCHEDULE_INVALID') from None
    if request == {'operation': 'health'}:
        return request
    expected = {'operation', 'source_instance', 'sync_enabled', 'sync_interval_seconds',
                'expected_sync_enabled', 'expected_sync_interval_seconds'}
    if (not isinstance(request, dict) or set(request) != expected
            or request.get('operation') != 'update_schedule'
            or not SOURCE_INSTANCE_PATTERN.fullmatch(request.get('source_instance', ''))
            or not isinstance(request.get('sync_enabled'), bool)
            or not isinstance(request.get('expected_sync_enabled'), bool)):
        raise ScheduleWorkerError('SCHEDULE_INVALID')
    try:
        validate_interval(request['sync_interval_seconds'])
        validate_interval(request['expected_sync_interval_seconds'], current=True)
    except ValueError:
        raise ScheduleWorkerError('SCHEDULE_INVALID') from None
    return request


def _authorize(connection, uid):
    if not hasattr(socket, 'SO_PEERCRED'):
        raise ScheduleWorkerError('PEER_FORBIDDEN')
    _pid, peer_uid, _gid = struct.unpack('3i', connection.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
    if peer_uid != uid:
        raise ScheduleWorkerError('PEER_FORBIDDEN')


def _handle(store, request):
    return {'status': 'ok'} if request['operation'] == 'health' else store.update(request)


def serve(socket_path, store, allowed_uid):
    """Serve the exact health/update protocol to the API UID only."""
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
                    response = {'ok': True, 'result': _handle(store, _receive(connection))}
                except ScheduleWorkerError as exc:
                    response = {'ok': False, 'error': exc.code}
                except Exception:  # pylint: disable=broad-exception-caught
                    response = {'ok': False, 'error': 'CONTROL_REQUEST_FAILED'}
                connection.sendall(json.dumps(response).encode())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--socket', required=True)
    parser.add_argument('--api-uid', type=int, default=10001)
    args = parser.parse_args()
    from .api.lifecycle_adapters import LifecycleScheduleStore
    store = LifecycleScheduleStore(os.environ.get('NETBOX_SYNC_SCHEDULE_WRITER_DSN', ''),
                          os.environ.get('NETBOX_SYNC_REGISTRY_SCHEMA', ''))
    serve(args.socket, store, args.api_uid)


if __name__ == '__main__':
    main()
