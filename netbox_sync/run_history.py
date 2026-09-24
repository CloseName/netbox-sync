"""Shared, secret-free PostgreSQL persistence for manual and scheduled runs."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

import psycopg
from .run_gates import blocking_runs
from psycopg import sql
from psycopg.rows import dict_row

from .source_config import SOURCE_INSTANCE_PATTERN
from .source_registry import SCHEMA_NAME_PATTERN


class RunStatus(str, Enum):
    """Closed durable synchronization outcomes."""

    RUNNING = 'RUNNING'
    SUCCEEDED = 'SUCCEEDED'
    FAILED_BEFORE_WRITE = 'FAILED_BEFORE_WRITE'
    PARTIALLY_APPLIED = 'PARTIALLY_APPLIED'
    OUTCOME_UNCERTAIN = 'OUTCOME_UNCERTAIN'
    BLOCKED = 'BLOCKED'
    LOCKED = 'LOCKED'
    FAILED = 'FAILED'


class RunTrigger(str, Enum):
    """Closed initiating boundaries."""

    MANUAL = 'manual'
    SCHEDULED = 'scheduled'


ACTION_NAMES = ('CREATE', 'UPDATE', 'NO_CHANGE', 'REVIEW_REQUIRED', 'BLOCKED',
                'IGNORED', 'UNSUPPORTED', 'RETAIN_ONLY')
RUN_COLUMNS = ('run_id', 'source_instance', 'source_type', 'trigger', 'started_at',
               'finished_at', 'duration_ms', 'status', 'plan_digest', 'planner_version',
               'create_count', 'update_count', 'no_change_count', 'review_required_count',
               'blocked_count', 'ignored_count', 'unsupported_count', 'retain_only_count',
               'error_code', 'error_message_safe', 'created_by')
RUN_COLUMN_LIST = ', '.join(f'"{column}"' for column in RUN_COLUMNS)
ERROR_STATUS = {
    'APPLY_LOCKED': RunStatus.LOCKED,
    'PLAN_BLOCKED': RunStatus.BLOCKED,
    'FAILED_BEFORE_WRITE': RunStatus.FAILED_BEFORE_WRITE,
    'PARTIALLY_APPLIED': RunStatus.PARTIALLY_APPLIED,
    'OUTCOME_UNCERTAIN': RunStatus.OUTCOME_UNCERTAIN,
}
SAFE_ERROR_MESSAGES = {
    'APPLY_LOCKED': 'Another synchronization is already running.',
    'PLAN_BLOCKED': 'The synchronization plan contains blocking conditions.',
    'PLAN_STALE': 'The synchronization plan is no longer current.',
    'CONFIRMATION_EXPIRED': 'The synchronization confirmation expired.',
    'CONFIRMATION_INVALID': 'The synchronization confirmation is invalid.',
    'CONFIRMATION_SOURCE_MISMATCH': 'The confirmation does not match this source.',
    'FAILED_BEFORE_WRITE': 'Synchronization failed before any changes were written.',
    'PARTIALLY_APPLIED': 'Synchronization stopped after some changes were written.',
    'OUTCOME_UNCERTAIN': 'The final NetBox state may be uncertain.',
    'APPLY_FAILED': 'Synchronization failed.',
}


@dataclass(frozen=True)
class ActionCounts:
    """Canonical plan action totals."""

    create: int = 0
    update: int = 0
    no_change: int = 0
    review_required: int = 0
    blocked: int = 0
    ignored: int = 0
    unsupported: int = 0
    retain_only: int = 0

    @classmethod
    def from_items(cls, items):
        totals = {name: 0 for name in ACTION_NAMES}
        for item in items or ():
            action = item.get('action') if isinstance(item, dict) else getattr(item, 'action', None)
            action = getattr(action, 'value', action)
            if action in totals:
                totals[action] += 1
        return cls(**{name.lower(): value for name, value in totals.items()})


@dataclass(frozen=True)
class SyncRun:
    """Public-safe immutable history record."""

    run_id: UUID
    source_instance: str
    source_type: str
    trigger: RunTrigger
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    status: RunStatus
    plan_digest: str | None
    planner_version: str | None
    counts: ActionCounts
    error_code: str | None
    error_message_safe: str | None
    created_by: str


def terminal_status(error_code):
    """Map a stable runtime error into the closed history status set."""
    return ERROR_STATUS.get(error_code, RunStatus.FAILED)


def safe_error_code(error_code):
    """Collapse arbitrary exception codes into the stable public allowlist."""
    return error_code if error_code in SAFE_ERROR_MESSAGES else 'APPLY_FAILED'


def safe_error_message(error_code):
    """Never derive persisted text from exception content."""
    return SAFE_ERROR_MESSAGES.get(error_code, 'Synchronization failed.')


class RunRepository:
    """Parameterized SQL operations limited to sync_runs."""

    def __init__(self, connection_factory, schema, clock=None):
        if not callable(connection_factory) or not SCHEMA_NAME_PATTERN.fullmatch(schema or ''):
            raise ValueError('valid connection factory and schema are required')
        self._connection_factory = connection_factory
        self.schema = schema
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _connect(self):
        connection = self._connection_factory()
        connection.row_factory = dict_row
        return connection

    def reconciliation_required(self, source_instance):
        """Do not infer safety from the newest run or from zero action counters."""
        with self._connect() as connection:
            return bool(connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND status IN ('OUTCOME_UNCERTAIN','PARTIALLY_APPLIED') LIMIT 1").format(blocking_runs(connection,self.schema)), (source_instance,)).fetchone())

    def scheduled_reconciliation_required(self, source_instance):
        if self.reconciliation_required(source_instance):
            return True
        with self._connect() as connection:
            present = connection.execute('SELECT to_regclass(%s)', (self.schema + '.recovery_schedule_blocks',)).fetchone()
            if not present['to_regclass']:
                return False  # No baseline decisions exist before this migration.
            return bool(connection.execute(sql.SQL('SELECT 1 FROM {} WHERE source_instance=%s').format(
                sql.Identifier(self.schema, 'recovery_schedule_blocks')), (source_instance,)).fetchone())

    def _table(self):
        return sql.Identifier(self.schema, 'sync_runs')

    @staticmethod
    def _validate_source(source_instance, source_type):
        if not SOURCE_INSTANCE_PATTERN.fullmatch(source_instance or ''):
            raise ValueError('invalid source_instance')
        if source_type not in ('proxmox', 'esxi'):
            raise ValueError('invalid source_type')

    @staticmethod
    def _row(row):
        return SyncRun(
            run_id=row['run_id'], source_instance=row['source_instance'],
            source_type=row['source_type'], trigger=RunTrigger(row['trigger']),
            started_at=row['started_at'], finished_at=row['finished_at'],
            duration_ms=row['duration_ms'], status=RunStatus(row['status']),
            plan_digest=row['plan_digest'], planner_version=row['planner_version'],
            counts=ActionCounts(**{name: row[name + '_count'] for name in (
                'create', 'update', 'no_change', 'review_required', 'blocked', 'ignored',
                'unsupported', 'retain_only')}),
            error_code=row['error_code'], error_message_safe=row['error_message_safe'],
            created_by=row['created_by'],
        )

    def start_run(self, source_instance, source_type, trigger, created_by,
                  plan_digest=None, planner_version=None, run_id=None):
        """Insert RUNNING before an execution boundary is crossed."""
        self._validate_source(source_instance, source_type)
        trigger = RunTrigger(trigger)
        if not isinstance(created_by, str) or not created_by or len(created_by) > 128:
            raise ValueError('invalid created_by')
        if plan_digest is not None and not re.fullmatch(r'[a-f0-9]{64}', plan_digest):
            raise ValueError('invalid plan_digest')
        if planner_version is not None and (
                not isinstance(planner_version, str) or len(planner_version) > 128):
            raise ValueError('invalid planner_version')
        identifier, started = UUID(str(run_id)) if run_id else uuid4(), self._clock()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('''
                    INSERT INTO {} (run_id, source_instance, source_type, "trigger", started_at,
                                    status, plan_digest, planner_version, created_by)
                    VALUES (%s, %s, %s, %s, %s, 'RUNNING', %s, %s, %s)
                    RETURNING *
                ''').format(self._table()), (identifier, source_instance, source_type,
                    trigger.value, started, plan_digest, planner_version, created_by))
                return self._row(cursor.fetchone())

    def finish_run(self, run_id, status, counts=None, plan_digest=None,
                   planner_version=None, error_code=None, error_message_safe=None):
        """Finalize exactly one RUNNING record; terminal records are immutable."""
        identifier, status = UUID(str(run_id)), RunStatus(status)
        if status is RunStatus.RUNNING:
            raise ValueError('terminal status required')
        counts, finished = counts or ActionCounts(), self._clock()
        values = tuple(getattr(counts, name) for name in (
            'create', 'update', 'no_change', 'review_required', 'blocked', 'ignored',
            'unsupported', 'retain_only'))
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in values):
            raise ValueError('counts must be non-negative integers')
        if plan_digest is not None and not re.fullmatch(r'[a-f0-9]{64}', plan_digest):
            raise ValueError('invalid plan_digest')
        if planner_version is not None and (
                not isinstance(planner_version, str) or len(planner_version) > 128):
            raise ValueError('invalid planner_version')
        if error_code is not None:
            if error_code not in SAFE_ERROR_MESSAGES:
                raise ValueError('invalid error_code')
            if error_message_safe != safe_error_message(error_code):
                raise ValueError('invalid safe error message')
        elif error_message_safe is not None:
            raise ValueError('safe error message requires an error code')
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('''
                    UPDATE {} SET finished_at=%s,
                        duration_ms=GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (%s-started_at))*1000)::bigint),
                        status=%s, plan_digest=COALESCE(%s, plan_digest),
                        planner_version=COALESCE(%s, planner_version),
                        create_count=%s, update_count=%s, no_change_count=%s,
                        review_required_count=%s, blocked_count=%s, ignored_count=%s,
                        unsupported_count=%s, retain_only_count=%s,
                        error_code=%s, error_message_safe=%s
                    WHERE run_id=%s AND status='RUNNING' RETURNING *
                ''').format(self._table()), (finished, finished, status.value, plan_digest,
                    planner_version, *values, error_code, error_message_safe, identifier))
                row = cursor.fetchone()
        if row is None:
            raise ValueError('run is missing or already terminal')
        return self._row(row)

    def bind_plan(self, run_id, digest, version):
        """Durably fence the consumed plan before any child can write."""
        if not re.fullmatch(r'[a-f0-9]{64}', digest): raise ValueError('invalid digest')
        with self._connect() as connection:
            row = connection.execute(sql.SQL("UPDATE {} SET plan_digest=%s, planner_version=%s "
                "WHERE run_id=%s AND status='RUNNING' AND plan_digest IS NULL RETURNING run_id")
                .format(self._table()), (digest, version, UUID(str(run_id)))).fetchone()
            if not row: raise ValueError('run already bound')

    def plan_used(self, source, digest, finished_at):
        """A later accepted attempt consumes this snapshot even if its reply was lost."""
        return self.plan_run(source, digest, finished_at) is not None

    def plan_run(self, source, digest, finished_at):
        """Exact persisted evidence, independent of bounded history pagination."""
        with self._connect() as connection:
            row = connection.execute(sql.SQL("SELECT run_id FROM {} WHERE source_instance=%s "
                "AND plan_digest=%s AND started_at >= %s ORDER BY started_at DESC, run_id DESC LIMIT 1").format(self._table()),
                (source, digest, finished_at)).fetchone()
            return str(row['run_id'] if isinstance(row, dict) else row[0]) if row else None

    def get_run(self, run_id):
        """Read one run by public UUID."""
        try:
            identifier = UUID(str(run_id))
        except (TypeError, ValueError, AttributeError):
            return None
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('SELECT {} FROM {} WHERE run_id=%s').format(
                    sql.SQL(RUN_COLUMN_LIST), self._table()),
                               (identifier,))
                row = cursor.fetchone()
        return self._row(row) if row else None

    def list_runs(self, *, source_instance=None, source_type=None, trigger=None, status=None,
                  limit=50, cursor=None):
        """Return deterministic newest-first history with bounded filters."""
        if not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError('limit must be between 1 and 200')
        clauses, parameters = [], []
        if source_instance is not None:
            if not SOURCE_INSTANCE_PATTERN.fullmatch(source_instance):
                raise ValueError('invalid source_instance')
            clauses.append(sql.SQL('source_instance=%s'))
            parameters.append(source_instance)
        if source_type is not None:
            if source_type not in ('proxmox', 'esxi'):
                raise ValueError('invalid source_type')
            clauses.append(sql.SQL('source_type=%s'))
            parameters.append(source_type)
        if trigger is not None:
            trigger = RunTrigger(trigger).value
            clauses.append(sql.SQL('"trigger"=%s'))
            parameters.append(trigger)
        if status is not None:
            status = RunStatus(status).value
            clauses.append(sql.SQL('status=%s'))
            parameters.append(status)
        if cursor is not None:
            cursor = UUID(str(cursor))
            clauses.append(sql.SQL('''(started_at, run_id) < (
                SELECT started_at, run_id FROM {} WHERE run_id=%s)''').format(self._table()))
            parameters.append(cursor)
        query = sql.SQL('SELECT {} FROM {}').format(sql.SQL(RUN_COLUMN_LIST), self._table())
        if clauses:
            query += sql.SQL(' WHERE ') + sql.SQL(' AND ').join(clauses)
        query += sql.SQL(' ORDER BY started_at DESC, run_id DESC LIMIT %s')
        parameters.append(limit)
        with self._connect() as connection:
            with connection.cursor() as db_cursor:
                db_cursor.execute(query, tuple(parameters))
                rows = db_cursor.fetchall()
        return tuple(self._row(row) for row in rows)

    def latest_by_source(self, *, trigger=None, status=None):
        """Return one newest indexed record per source for a fixed filter."""
        clauses, parameters = [], []
        if trigger is not None:
            clauses.append(sql.SQL('"trigger"=%s'))
            parameters.append(RunTrigger(trigger).value)
        if status is not None:
            clauses.append(sql.SQL('status=%s'))
            parameters.append(RunStatus(status).value)
        query = sql.SQL('SELECT DISTINCT ON (source_instance) {} FROM {}').format(
            sql.SQL(RUN_COLUMN_LIST), self._table())
        if clauses:
            query += sql.SQL(' WHERE ') + sql.SQL(' AND ').join(clauses)
        query += sql.SQL(' ORDER BY source_instance, started_at DESC, run_id DESC')
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, tuple(parameters))
                rows = cursor.fetchall()
        return tuple(self._row(row) for row in rows)

    def stale_running(self, started_before, limit=100):
        """Return a bounded oldest-first list without changing lifecycle state."""
        if not isinstance(started_before, datetime) or not 1 <= limit <= 100:
            raise ValueError('valid stale boundary and limit required')
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('''SELECT {} FROM {}
                    WHERE status='RUNNING' AND started_at < %s
                    ORDER BY started_at ASC, run_id ASC LIMIT %s''').format(
                        sql.SQL(RUN_COLUMN_LIST), self._table()), (started_before, limit))
                rows = cursor.fetchall()
        return tuple(self._row(row) for row in rows)


def postgres_run_repository(dsn, schema):
    """Build the writer boundary, failing closed when deployment is incomplete."""
    if not isinstance(dsn, str) or not dsn.strip():
        raise RuntimeError('Run history writer configuration is required')
    return RunRepository(
        lambda: psycopg.connect(
            dsn, connect_timeout=3, options='-c statement_timeout=5000',
        ),
        schema,
    )
