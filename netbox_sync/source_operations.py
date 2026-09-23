"""Bounded latest source operations, independent of synchronization run history."""

from contextlib import contextmanager
import hashlib
import json
import logging
import time
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .source_registry import SCHEMA_NAME_PATTERN
from .source_config import SOURCE_INSTANCE_PATTERN

KINDS = frozenset({'PLAN', 'DISCOVERY'})
ACTIVE_SECONDS = 180
RESULT_SECONDS = 86400
MAX_RESULT_BYTES = 8 * 1024 * 1024


class OperationError(RuntimeError):
    """An allowlisted operation failure, never raw worker or database text."""

    def __init__(self, code, reason=None):
        self.code = code
        from .plan_diagnostics import safe_reason
        self.reason = safe_reason(reason)
        super().__init__(code)


@contextmanager
def source_gate(connection, schema, source, *, allow_retirement=False):
    """Serialize short lifecycle/generation transitions for one source only."""
    connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
                       (f'netbox-sync:{schema}:source:{source}',))
    if not allow_retirement:
        # Compatibility with pre-retirement schemas is read-only. A failed query
        # is never treated as an empty journal or a permission to write.
        exists=connection.execute('SELECT to_regclass(%s)',(schema+'.source_retirements',)).fetchone()
        present=(exists.get('to_regclass') if isinstance(exists,dict) else exists[0]) if exists else None
        if present and connection.execute(sql.SQL("SELECT source_instance FROM {} WHERE source_instance=%s AND state IN ('SENDING','UNCERTAIN','SUCCEEDED') LIMIT 1").format(
                sql.Identifier(schema,'source_retirements')),(source,)).fetchone():
            raise OperationError('SOURCE_RETIREMENT_PENDING')
    yield


class OperationStore:
    """At most two latest records per source; no growing snapshot history.

    A slot is replaced only after its terminal state. Its UUID fences every
    completion. Execution owns a separate session advisory lock. Recovery never
    releases an operation whose executing supervisor still owns that lock.
    """

    def __init__(self, dsn, schema, connector=psycopg.connect):
        if not dsn or not SCHEMA_NAME_PATTERN.fullmatch(schema or ''):
            raise OperationError('OPERATIONS_UNAVAILABLE')
        self.dsn, self.schema, self.connector = dsn, schema, connector

    def connect(self):
        return self.connector(self.dsn, connect_timeout=3, row_factory=dict_row,
                              keepalives=1, keepalives_idle=30, keepalives_interval=10,
                              keepalives_count=3, tcp_user_timeout=60000,
                              options='-c statement_timeout=5000 -c lock_timeout=3000')

    @property
    def table(self):
        return sql.Identifier(self.schema, 'source_operations')

    def lock_key(self, source, kind):
        return f'netbox-sync:{self.schema}:operation:{source}:{kind}'

    def latest(self, source):
        """Reconcile abandoned/expired slots without automatically rerunning work."""
        with self.connect() as connection:
            rows = connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s '
                                               'ORDER BY operation_kind').format(self.table),
                                      (source,)).fetchall()
            for row in rows:
                if row['status'] == 'RUNNING':
                    expired = connection.execute(
                        'SELECT %s < clock_timestamp() - interval \'180 seconds\' AS expired',
                        (row['updated_at'],)).fetchone()['expired']
                    if not expired:
                        continue
                    key = self.lock_key(source, row['operation_kind'])
                    free = connection.execute(
                        'SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0)) AS free',
                        (key,)).fetchone()['free']
                    if free:
                        connection.execute(sql.SQL('''UPDATE {} SET status='FAILED',
                            safe_error_code='OPERATION_INTERRUPTED', result=NULL,
                            updated_at=clock_timestamp(), finished_at=clock_timestamp()
                            WHERE operation_id=%s AND status='RUNNING' ''').format(self.table),
                            (row['operation_id'],))
                elif row['result'] is not None:
                    connection.execute(sql.SQL('''UPDATE {} SET result=NULL,
                        status=CASE WHEN operation_kind='PLAN' THEN 'STALE' ELSE 'FAILED' END,
                        safe_error_code='RESULT_EXPIRED', updated_at=clock_timestamp()
                        WHERE operation_id=%s AND finished_at < clock_timestamp()-interval '24 hours'
                        ''').format(self.table), (row['operation_id'],))
            return connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s '
                                               'ORDER BY operation_kind').format(self.table),
                                      (source,)).fetchall()

    def start(self, source, kind):
        """Atomic per-source/kind deduplication; callers receive the same active UUID."""
        if kind not in KINDS or not SOURCE_INSTANCE_PATTERN.fullmatch(source):
            raise OperationError('OPERATION_INVALID')
        self.latest(source)
        with self.connect() as connection, source_gate(connection, self.schema, source):
            record = connection.execute(sql.SQL('SELECT enabled FROM {} WHERE source_instance=%s')
                                        .format(sql.Identifier(self.schema, 'sources')),
                                        (source,)).fetchone()
            if not record:
                raise OperationError('SOURCE_NOT_FOUND')
            if not record['enabled']:
                raise OperationError('SOURCE_DISABLED')
            current = connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s '
                                                 'AND operation_kind=%s').format(self.table),
                                         (source, kind)).fetchone()
            if current and current['status'] == 'RUNNING':
                return current, False
            key = self.lock_key(source, kind)
            if not connection.execute(
                    'SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS free',
                    (key,)).fetchone()['free']:
                raise OperationError('OPERATION_STILL_EXECUTING')
            row = connection.execute(sql.SQL('''INSERT INTO {} (source_instance, operation_kind,
                operation_id, status) VALUES (%s,%s,%s,'RUNNING')
                ON CONFLICT (source_instance,operation_kind) DO UPDATE SET
                operation_id=EXCLUDED.operation_id, status='RUNNING', started_at=clock_timestamp(),
                updated_at=clock_timestamp(), finished_at=NULL, safe_error_code=NULL, result=NULL
                RETURNING *''').format(self.table), (source, kind, uuid4())).fetchone()
            return row, True

    def execute(self, operation, callback):
        """Run only the current generation, retaining ownership across provider work."""
        with self.connect() as owner:
            owner.autocommit = True
            key = self.lock_key(operation['source_instance'], operation['operation_kind'])
            if not owner.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS free',
                                 (key,)).fetchone()['free']:
                return
            try:
                current = owner.execute(sql.SQL('SELECT status FROM {} WHERE operation_id=%s')
                                        .format(self.table), (operation['operation_id'],)).fetchone()
                if not current or current['status'] != 'RUNNING':
                    return
                started = time.monotonic()
                phase = 'operation'
                try:
                    result = callback()
                    phase = 'result_validation'
                    raw = json.dumps(result, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
                    if len(raw.encode()) > MAX_RESULT_BYTES:
                        raise OperationError('RESULT_TOO_LARGE')
                    if result.get('source_instance') != operation['source_instance']:
                        raise OperationError('RESULT_INVALID')
                    if operation['operation_kind'] == 'PLAN':
                        canonical = dict(result)
                        digest = canonical.pop('digest')
                        actual = hashlib.sha256(json.dumps(canonical, sort_keys=True,
                            separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
                        if actual != digest:
                            raise OperationError('RESULT_INVALID')
                    from .api.dto import SyncPlanDTO, DiscoveryResultDTO
                    try:
                        (SyncPlanDTO if operation['operation_kind'] == 'PLAN' else DiscoveryResultDTO).from_worker(result)
                    except Exception:
                        raise OperationError('RESULT_INVALID') from None
                    status = 'READY' if operation['operation_kind'] == 'PLAN' else 'SUCCEEDED'
                    code = None
                except Exception as exc:  # Public result never contains exception text.
                    result, status = None, 'FAILED'
                    candidate = getattr(exc, 'code', '')
                    from .worker_failure import ERRORS, safe_diagnostic, diagnostic
                    code = candidate if candidate in set(ERRORS) | {
                        'SOURCE_NOT_FOUND', 'SOURCE_DISABLED', 'CREDENTIAL_UNAVAILABLE',
                        'REGISTRY_UNAVAILABLE', 'DISCOVERY_TIMEOUT', 'PROVIDER_UNAVAILABLE',
                        'NETBOX_UNAVAILABLE', 'DISCOVERY_FAILED', 'RESULT_TOO_LARGE',
                        'RESULT_INVALID'} else 'OPERATION_FAILED'
                    event=safe_diagnostic(getattr(exc,'diagnostic',None) or diagnostic(exc,'planning'),code)
                    event.update(duration_ms=int((time.monotonic()-started)*1000), phase=event.get('phase',phase))
                    event.update(event_id=str(operation['operation_id']),source_instance=operation['source_instance'],
                                 operation_kind=operation['operation_kind'])
                    logging.getLogger(__name__).error(json.dumps(event,sort_keys=True))
                completion = owner.execute(sql.SQL('''UPDATE {} SET status=%s, result=%s, safe_error_code=%s,
                    updated_at=clock_timestamp(), finished_at=clock_timestamp()
                    WHERE operation_id=%s AND status='RUNNING' ''').format(self.table),
                    (status, Jsonb(result) if result is not None else None, code,
                     operation['operation_id']))
                if completion.rowcount == 0:
                    logging.getLogger(__name__).warning(json.dumps({
                        'code': 'OPERATION_COMPLETION_DISCARDED',
                        'operation_id': str(operation['operation_id']),
                        'source_instance': operation['source_instance']}))
            finally:
                owner.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (key,))

    def current_plan(self, source, digest, operation_id=None, *, include_result=False):
        """Require the current READY generation, including its bounded lifetime."""
        with self.connect() as connection:
            row = connection.execute(sql.SQL('''SELECT *, finished_at <= clock_timestamp()-interval '24 hours' AS expired FROM {} WHERE source_instance=%s
                AND operation_kind='PLAN'
                ''').format(self.table), (source,)).fetchone()
        reason = ('OPERATION_MISSING' if not row else
                  'OPERATION_VERSION' if operation_id is not None and str(row['operation_id']) != str(operation_id) else
                  'OPERATION_EXPIRED' if row.get('expired') is not False else
                  'OPERATION_STATUS' if row['status'] != 'READY' else
                  'RESULT_MISSING' if not row['result'] else
                  'REVIEW_DIGEST' if row['result']['digest'] != digest else None)
        if reason:
            raise OperationError('PLAN_STALE', reason)
        return row['result'] if include_result else str(row['operation_id'])

    def plan_time(self, source, operation_id):
        with self.connect() as connection:
            row = connection.execute(sql.SQL("SELECT finished_at FROM {} WHERE source_instance=%s "
                "AND operation_id=%s AND operation_kind='PLAN'").format(self.table),
                (source, operation_id)).fetchone()
            if not row or not row['finished_at']: raise OperationError('PLAN_STALE', 'OPERATION_MISSING')
            return row['finished_at']

    @contextmanager
    def review_guard(self, source, digest, operation_id):
        """Keep the reviewed generation current during revalidation and apply."""
        if operation_id is None:
            raise OperationError('PLAN_STALE', 'OPERATION_MISSING')
        with self.connect() as connection, source_gate(connection, self.schema, source):
            reviewed = self.current_plan(source, digest, operation_id, include_result=True)
            yield reviewed

    def invalidate_plan(self, source, operation_id):
        """Persist revalidation failure only for the exact reviewed generation."""
        with self.connect() as connection, source_gate(connection, self.schema, source):
            connection.execute(sql.SQL("UPDATE {} SET status='STALE', result=NULL, "
                "safe_error_code='PLAN_STALE', updated_at=clock_timestamp() "
                "WHERE source_instance=%s AND operation_id=%s AND operation_kind='PLAN' AND status='READY'")
                .format(self.table), (source, operation_id))
