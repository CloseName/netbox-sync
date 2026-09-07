"""Source tombstones and an explicit, narrow removal capability."""
from contextlib import contextmanager
import hashlib
import json
import os

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .source_operations import source_gate
from .source_registry import SCHEMA_NAME_PATTERN


class LifecycleError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@contextmanager
def apply_lock(path):
    """Contend on the existing manual/scheduled lock, never a second lock system."""
    import fcntl
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise LifecycleError('SOURCE_APPLY_ACTIVE') from None
        yield
    finally:
        os.close(descriptor)


def initialize_tombstones(connection, schema):
    """Test/bootstrap initializer; production uses forward Alembic migration."""
    connection.execute(sql.SQL('''CREATE TABLE IF NOT EXISTS {} (
        source_instance TEXT PRIMARY KEY, display_name TEXT NOT NULL,
        removed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        credential_state TEXT NOT NULL CHECK (credential_state IN
        ('RETAINED_BY_REQUEST','REMOVED','RETAINED_SHARED_OR_LEGACY','CLEANUP_FAILED'))
    )''').format(sql.Identifier(schema, 'source_tombstones')))


class LifecycleStore:
    def __init__(self, dsn, schema, lock_path, connector=psycopg.connect, lock=apply_lock):
        if not dsn or not SCHEMA_NAME_PATTERN.fullmatch(schema or ''):
            raise LifecycleError('LIFECYCLE_UNAVAILABLE')
        self.dsn, self.schema, self.lock_path = dsn, schema, lock_path
        self.connector, self.lock = connector, lock

    def connect(self):
        return self.connector(self.dsn, connect_timeout=3, row_factory=dict_row,
                              options='-c statement_timeout=5000 -c lock_timeout=3000')

    def table(self, name):
        return sql.Identifier(self.schema, name)

    @staticmethod
    def revision(row):
        return hashlib.sha256(json.dumps(dict(row), sort_keys=True, default=str,
                                        separators=(',', ':')).encode()).hexdigest()

    def read(self, source):
        with self.connect() as connection:
            removed = connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s')
                .format(self.table('source_tombstones')), (source,)).fetchone()
            if removed:
                return {**removed, 'removed_at': removed['removed_at'].isoformat(), 'revision': None}
            row = connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s')
                .format(self.table('sources')), (source,)).fetchone()
            if not row:
                raise LifecycleError('SOURCE_NOT_FOUND')
            return {'source_instance': source, 'display_name': row['name'],
                    'removed_at': None, 'credential_state': None, 'revision': self.revision(row)}

    def remove(self, source, expected_revision, confirmed_source, remove_credentials, cleanup):
        """Commit the tombstone first; remove only broker-owned, exclusive local refs.

        The credential-reference gate excludes registration/reference changes during the
        exclusivity check and cleanup. The global apply lock spans both phases.
        A crash leaves a tombstone with CLEANUP_FAILED; it never resumes deletion.
        """
        if confirmed_source != source:
            raise LifecycleError('SOURCE_CONFIRMATION_INVALID')
        with self.lock(self.lock_path):
            with self.connect() as connection, source_gate(connection, self.schema, source):
                connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                                   (f'netbox-sync:{self.schema}:credential-refs',))
                row = connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s')
                    .format(self.table('sources')), (source,)).fetchone()
                if not row:
                    raise LifecycleError('SOURCE_NOT_FOUND')
                if connection.execute(sql.SQL('SELECT 1 FROM {} WHERE source_instance=%s')
                    .format(self.table('source_tombstones')), (source,)).fetchone():
                    raise LifecycleError('SOURCE_ALREADY_REMOVED')
                if self.revision(row) != expected_revision:
                    raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')
                if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND status='RUNNING'")
                    .format(self.table('source_operations')), (source,)).fetchone():
                    raise LifecycleError('SOURCE_OPERATION_ACTIVE')
                if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND status IN "
                    "('RUNNING','OUTCOME_UNCERTAIN','PARTIALLY_APPLIED') LIMIT 1")
                    .format(self.table('sync_runs')), (source,)).fetchone():
                    raise LifecycleError('SOURCE_APPLY_UNCONFIRMED')
                connection.execute(sql.SQL('UPDATE {} SET enabled=false, sync_enabled=false '
                                           'WHERE source_instance=%s').format(self.table('sources')), (source,))
                state = 'CLEANUP_FAILED' if remove_credentials else 'RETAINED_BY_REQUEST'
                connection.execute(sql.SQL('INSERT INTO {} (source_instance,display_name,credential_state) '
                                           'VALUES (%s,%s,%s)').format(self.table('source_tombstones')),
                                   (source, row['name'], state))
            # The lifecycle transition is durable before touching any credential file.
            if remove_credentials:
                try:
                    with self.connect() as connection:
                        connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                                           (f'netbox-sync:{self.schema}:credential-refs',))
                        refs = {(row['token_id_provider'], row['token_id_key']),
                                (row['token_secret_provider'], row['token_secret_key'])}
                        others = connection.execute(sql.SQL('SELECT token_id_provider,token_id_key,'
                            'token_secret_provider,token_secret_key FROM {} WHERE source_instance<>%s')
                            .format(self.table('sources')), (source,)).fetchall()
                        shared = {(item[provider], item[key]) for item in others
                                  for provider,key in [('token_id_provider','token_id_key'),
                                                       ('token_secret_provider','token_secret_key')]}
                        # Retain the entire credential pair if any ref is ambiguous/shared.
                        import re
                        exclusive = all(provider == 'file' and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{15,127}', key)
                                        and (provider,key) not in shared for provider,key in refs)
                        if exclusive:
                            cleaned = cleanup([key for _,key in sorted(refs)])
                            state = 'RETAINED_SHARED_OR_LEGACY' if cleaned is False else 'REMOVED'
                        else:
                            state = 'RETAINED_SHARED_OR_LEGACY'
                        connection.execute(sql.SQL('UPDATE {} SET credential_state=%s WHERE source_instance=%s')
                            .format(self.table('source_tombstones')), (state,source))
                except Exception:
                    # Persisted CLEANUP_FAILED is deliberately retained on ambiguity/failure.
                    pass
            return self.read(source)
