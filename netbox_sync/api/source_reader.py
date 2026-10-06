"""SELECT-only registry v1 projection; no internal SourceRegistry objects loaded."""

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from ..application.sources import SourceReadError
from ..source_registry import SCHEMA_NAME_PATTERN


SOURCE_COLUMNS = (
    'source_instance', 'source_type', 'name', 'address', 'enabled', 'sync_enabled',
    'verify_ssl', 'sync_interval_seconds', 'sync_calendar', 'schedule_changed_at', 'site_slug', 'cluster_name', 'platform_slug',
    'device_role_slug', 'device_type_slug', 'cluster_type_slug', 'legacy_identity_owner',
)


class PostgresSourceReader:
    """Reuse WEB-1 configuration and timeout policy without migrations or secrets."""

    def __init__(self, settings, connector=psycopg.connect):
        self._settings = settings
        self._connector = connector

    def read(self, source_instance=None):
        """Identifiers are quoted; source_instance is a bound parameter."""
        try:
            schema = self._settings.registry_schema
            if not self._settings.registry_dsn or not SCHEMA_NAME_PATTERN.fullmatch(schema):
                raise SourceReadError()
            with self._connector(
                    self._settings.registry_dsn, connect_timeout=3,
                    options='-c statement_timeout=2000 -c default_transaction_read_only=on',
            ) as connection:
                connection.read_only = True
                with connection.cursor(row_factory=dict_row) as cursor:
                    cursor.execute(sql.SQL("SELECT value FROM {} WHERE key = 'schema_version'").format(
                        sql.Identifier(schema, 'schema_meta'),
                    ))
                    if cursor.fetchone() != {'value': '1'}:
                        raise SourceReadError()
                    query = sql.SQL('SELECT {} FROM {}').format(
                        sql.SQL(', ').join(map(sql.Identifier, SOURCE_COLUMNS)),
                        sql.Identifier(schema, 'sources'),
                    )
                    if source_instance is not None:
                        query += sql.SQL(' WHERE source_instance = %s')
                    query += sql.SQL(' ORDER BY source_instance')
                    cursor.execute(query, (source_instance,) if source_instance is not None else ())
                    return tuple(cursor.fetchall())
        except Exception:  # pylint: disable=broad-exception-caught
            raise SourceReadError() from None
