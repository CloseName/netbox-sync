"""Bounded, SELECT-only registry health adapter; no migrations or source loading."""

import psycopg
from psycopg import sql

from ..application.health import ComponentHealth, HealthStatus
from ..application.observability import ErrorCode
from ..source_registry import SCHEMA_NAME_PATTERN


class PostgresHealthProbe:
    """Inspect basic registry v1 availability, including unbaselined installations."""

    def __init__(self, settings, connector=psycopg.connect):
        self._settings = settings
        self._connector = connector

    def check(self):
        """Return safe states; never return driver errors, rows, DSNs or paths."""
        if not self._settings.registry_dsn:
            unknown = ComponentHealth(HealthStatus.UNKNOWN, 'Database configuration is absent')
            return unknown, ComponentHealth(HealthStatus.UNKNOWN, 'Registry has not been checked')
        connected = False
        try:
            with self._connector(
                    self._settings.registry_dsn,
                    connect_timeout=3,
                    options='-c statement_timeout=2000 -c default_transaction_read_only=on',
            ) as connection:
                connection.read_only = True
                with connection.cursor() as cursor:
                    cursor.execute('SELECT 1')
                    cursor.fetchone()
                    connected = True
                    schema = self._settings.registry_schema
                    if not SCHEMA_NAME_PATTERN.fullmatch(schema):
                        raise ValueError('Invalid registry schema')
                    cursor.execute(
                        sql.SQL("SELECT value FROM {} WHERE key = 'schema_version'").format(
                            sql.Identifier(schema, 'schema_meta')
                        )
                    )
                    if cursor.fetchone() != ('1',):
                        raise ValueError('Unsupported registry schema')
                    cursor.execute(
                        sql.SQL(
                            'SELECT source_instance, source_type, enabled, sync_enabled FROM {} LIMIT 0'
                        ).format(
                            sql.Identifier(schema, 'sources')
                        )
                    )
        except Exception:  # pylint: disable=broad-exception-caught
            database = ComponentHealth(
                HealthStatus.HEALTHY if connected else HealthStatus.UNAVAILABLE,
                'Database is reachable' if connected else 'Database is unavailable',
                None if connected else ErrorCode.REGISTRY_UNAVAILABLE,
            )
            return database, ComponentHealth(
                HealthStatus.UNAVAILABLE, 'Source registry is unavailable', ErrorCode.REGISTRY_UNAVAILABLE,
            )
        return (
            ComponentHealth(HealthStatus.HEALTHY, 'Database is reachable'),
            ComponentHealth(HealthStatus.HEALTHY, 'Registry v1 is readable'),
        )
