"""PostgreSQL storage foundation for source configuration references."""

import re
from dataclasses import dataclass, replace
from types import MappingProxyType

from psycopg import errors, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .source_config import (
    NetBoxTargetConfig,
    SecretReference,
    SourceConfig,
    SourceCredentials,
)


SCHEMA_VERSION = 1
SCHEMA_NAME_PATTERN = re.compile(r'^[a-z][a-z0-9_]{2,62}$')
SUPPORTED_SOURCE_TYPES = frozenset({'esxi', 'proxmox'})
SUPPORTED_SECRET_PROVIDERS = frozenset({'env', 'file'})
IMMUTABLE_UPDATE_FIELDS = frozenset({'id', 'source_instance', 'source_type'})
MUTABLE_UPDATE_FIELDS = frozenset({
    'name', 'address', 'enabled', 'sync_enabled', 'sync_interval_seconds',
    'verify_ssl', 'target', 'credentials', 'legacy_identity_owner', 'settings',
})


@dataclass(frozen=True)
class SourceRecord:
    """Immutable persisted source and PostgreSQL-managed timestamps."""

    config: SourceConfig
    created_at: object
    updated_at: object

    @property
    def id(self):
        return self.config.id

    @property
    def source_instance(self):
        return self.config.source_instance

    def to_source_config(self):
        """Return the single canonical runtime configuration model."""

        return self.config


@dataclass(frozen=True)
class SourceLoadResult:
    """One isolated registry-row conversion result for scheduler evaluation."""

    record: SourceRecord | None
    valid: bool


class SourceRegistryError(RuntimeError):
    """Base error for fail-closed registry operations."""


class SourceConflictError(ValueError):
    """A database uniqueness constraint rejected a source identity."""


class SourceConcurrentUpdateError(SourceRegistryError):
    """Optimistic concurrency detected a stale source record."""


class SourceRegistry:
    """PostgreSQL registry with externally supplied connection bootstrap."""

    def __init__(self, connection_factory, schema):
        if not callable(connection_factory):
            raise TypeError('connection_factory must be callable')
        if not isinstance(schema, str) or not SCHEMA_NAME_PATTERN.fullmatch(schema):
            raise ValueError('schema must be a safe PostgreSQL identifier')
        self._connection_factory = connection_factory
        self.schema = schema

    def _connect(self):
        connection = self._connection_factory()
        connection.row_factory = dict_row
        return connection

    def _table(self, table_name):
        return sql.Identifier(self.schema, table_name)

    def initialize(self):
        """Transactionally create the versioned schema without data loss."""

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(
                        sql.Identifier(self.schema)
                    )
                )
                cursor.execute(
                    sql.SQL(
                        '''
                        CREATE TABLE IF NOT EXISTS {} (
                            key TEXT PRIMARY KEY,
                            value TEXT NOT NULL
                        )
                        '''
                    ).format(self._table('schema_meta'))
                )
                cursor.execute(
                    sql.SQL(
                        '''
                        INSERT INTO {} (key, value)
                        VALUES ('schema_version', %s)
                        ON CONFLICT (key) DO NOTHING
                        '''
                    ).format(self._table('schema_meta')),
                    (str(SCHEMA_VERSION),),
                )
                cursor.execute(
                    sql.SQL(
                        '''
                        CREATE TABLE IF NOT EXISTS {} (
                            id TEXT PRIMARY KEY,
                            source_instance TEXT NOT NULL UNIQUE,
                            name TEXT NOT NULL,
                            source_type TEXT NOT NULL,
                            address TEXT NOT NULL,
                            enabled BOOLEAN NOT NULL,
                            sync_enabled BOOLEAN NOT NULL,
                            sync_interval_seconds INTEGER NOT NULL,
                            verify_ssl BOOLEAN NOT NULL,
                            site_slug TEXT NOT NULL,
                            device_role_slug TEXT NOT NULL,
                            platform_slug TEXT NOT NULL,
                            device_type_slug TEXT NOT NULL,
                            cluster_type_slug TEXT NOT NULL,
                            cluster_name TEXT NOT NULL,
                            username TEXT NOT NULL,
                            token_id_provider TEXT NOT NULL,
                            token_id_key TEXT NOT NULL,
                            token_secret_provider TEXT NOT NULL,
                            token_secret_key TEXT NOT NULL,
                            legacy_identity_owner BOOLEAN NOT NULL DEFAULT FALSE,
                            settings JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            CONSTRAINT settings_is_object
                                CHECK (jsonb_typeof(settings) = 'object'),
                            CONSTRAINT positive_sync_interval
                                CHECK (sync_interval_seconds > 0)
                        )
                        '''
                    ).format(self._table('sources'))
                )
                cursor.execute(
                    sql.SQL(
                        "SELECT value FROM {} WHERE key = 'schema_version'"
                    ).format(self._table('schema_meta'))
                )
                row = cursor.fetchone()
                if row is None or int(row['value']) != SCHEMA_VERSION:
                    raise SourceRegistryError(
                        'unsupported source registry schema version'
                    )

    def schema_version(self):
        """Read the initialized schema version."""

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "SELECT value FROM {} WHERE key = 'schema_version'"
                    ).format(self._table('schema_meta'))
                )
                row = cursor.fetchone()
        if row is None:
            raise SourceRegistryError('source registry is not initialized')
        return int(row['value'])

    @staticmethod
    def _validate_config(config):
        if not isinstance(config, SourceConfig):
            raise TypeError('source must be a SourceConfig')
        if config.source_type not in SUPPORTED_SOURCE_TYPES:
            raise ValueError(f'unsupported source_type: {config.source_type!r}')
        if config.source_type == 'esxi' and config.legacy_identity_owner:
            raise ValueError('ESXi cannot be a legacy identity owner')
        if not isinstance(config.target, NetBoxTargetConfig):
            raise TypeError('target must be NetBoxTargetConfig')
        if not isinstance(config.credentials, SourceCredentials):
            raise TypeError('credentials must be SourceCredentials')

        references = (
            config.credentials.token_id,
            config.credentials.token_secret,
        )
        for reference in references:
            if not isinstance(reference, SecretReference):
                raise TypeError('credential values must be SecretReference objects')
            if reference.provider not in SUPPORTED_SECRET_PROVIDERS:
                raise ValueError(
                    f'unsupported secret provider: {reference.provider!r}'
                )

        for key in config.settings:
            lowered = str(key).casefold()
            if any(part in lowered for part in ('password', 'secret', 'token_value')):
                raise ValueError('secret values are not allowed in source settings')

    @staticmethod
    def _row_to_record(row):
        settings = row['settings']
        if not isinstance(settings, dict):
            raise SourceRegistryError('registry settings must be a JSON object')

        config = SourceConfig(
            id=row['id'],
            source_instance=row['source_instance'],
            name=row['name'],
            source_type=row['source_type'],
            address=row['address'],
            enabled=row['enabled'],
            sync_enabled=row['sync_enabled'],
            sync_interval_seconds=row['sync_interval_seconds'],
            verify_ssl=row['verify_ssl'],
            target=NetBoxTargetConfig(
                site_slug=row['site_slug'],
                device_role_slug=row['device_role_slug'],
                platform_slug=row['platform_slug'],
                device_type_slug=row['device_type_slug'],
                cluster_type_slug=row['cluster_type_slug'],
                cluster_name=row['cluster_name'],
            ),
            credentials=SourceCredentials(
                username=row['username'],
                token_id=SecretReference(
                    provider=row['token_id_provider'],
                    key=row['token_id_key'],
                ),
                token_secret=SecretReference(
                    provider=row['token_secret_provider'],
                    key=row['token_secret_key'],
                ),
            ),
            legacy_identity_owner=row['legacy_identity_owner'],
            settings=MappingProxyType(dict(settings)),
        )
        SourceRegistry._validate_config(config)
        return SourceRecord(
            config=config,
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )

    @staticmethod
    def _create_parameters(config):
        target = config.target
        credentials = config.credentials
        return (
            config.id, config.source_instance, config.name, config.source_type,
            config.address, config.enabled, config.sync_enabled,
            config.sync_interval_seconds, config.verify_ssl, target.site_slug,
            target.device_role_slug, target.platform_slug, target.device_type_slug,
            target.cluster_type_slug, target.cluster_name, credentials.username,
            credentials.token_id.provider, credentials.token_id.key,
            credentials.token_secret.provider, credentials.token_secret.key,
            config.legacy_identity_owner, Jsonb(dict(config.settings)),
        )

    def create_source(self, config):
        """Transactionally persist one validated SourceConfig."""

        self._validate_config(config)
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL(
                            '''
                            INSERT INTO {} (
                                id, source_instance, name, source_type, address,
                                enabled, sync_enabled, sync_interval_seconds,
                                verify_ssl, site_slug, device_role_slug,
                                platform_slug, device_type_slug, cluster_type_slug,
                                cluster_name, username, token_id_provider,
                                token_id_key, token_secret_provider,
                                token_secret_key, legacy_identity_owner, settings
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                            ) RETURNING *
                            '''
                        ).format(self._table('sources')),
                        self._create_parameters(config),
                    )
                    row = cursor.fetchone()
        except errors.UniqueViolation as exc:
            raise SourceConflictError(
                'duplicate source id or source_instance'
            ) from exc
        return self._row_to_record(row)

    def _get_one(self, query, parameters):
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, parameters)
                row = cursor.fetchone()
        return None if row is None else self._row_to_record(row)

    def get_source(self, source_id):
        """Read one source by registry id."""

        query = sql.SQL('SELECT * FROM {} WHERE id = %s').format(
            self._table('sources')
        )
        return self._get_one(query, (source_id,))

    def get_by_source_instance(self, source_instance):
        """Read one source by stable operator-defined identity."""

        query = sql.SQL('SELECT * FROM {} WHERE source_instance = %s').format(
            self._table('sources')
        )
        return self._get_one(query, (source_instance,))

    def assert_exclusive_host(self, config):
        """Reject known active duplicate ESXi claims before any runtime write.

        Historical rows without hardware evidence still need explicit review;
        absence of evidence is not used to merge or assign ownership.
        """
        if config.source_type != 'esxi':
            return
        from .host_registration import legacy_anchor, HostRegistrationConflict
        anchor = legacy_anchor(config.settings)
        if anchor is None:
            return
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('SELECT source_instance, settings FROM {} WHERE source_type=%s AND enabled=true').format(
                    self._table('sources')), ('esxi',))
                others = [row for row in cursor.fetchall()
                          if row['source_instance'] != config.source_instance and legacy_anchor(row['settings']) == anchor]
        if others:
            raise HostRegistrationConflict('HOST_IDENTITY_CONFLICT')

    def list_sources(self):
        """List all source records without resolving credentials."""

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL('SELECT * FROM {} ORDER BY id').format(
                        self._table('sources')
                    )
                )
                rows = cursor.fetchall()
        return tuple(self._row_to_record(row) for row in rows)

    def list_sources_isolated(self):
        """Convert every row independently without weakening strict registry reads."""

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL('SELECT * FROM {} ORDER BY id').format(
                        self._table('sources')
                    )
                )
                rows = cursor.fetchall()
        results = []
        for row in rows:
            try:
                results.append(SourceLoadResult(self._row_to_record(row), True))
            except Exception:  # pylint: disable=broad-exception-caught
                results.append(SourceLoadResult(None, False))
        return tuple(results)

    def list_runnable_sources(self):
        """List enabled, sync-enabled configs deterministically by source id."""

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        'SELECT * FROM {} '
                        'WHERE enabled = TRUE AND sync_enabled = TRUE '
                        'ORDER BY id'
                    ).format(self._table('sources'))
                )
                rows = cursor.fetchall()
        return tuple(
            self._row_to_record(row).to_source_config()
            for row in rows
        )

    def get_source_config(self, source_id):
        """Return the existing immutable SourceConfig, or ``None``."""

        record = self.get_source(source_id)
        return None if record is None else record.to_source_config()

    @staticmethod
    def _update_parameters(config, expected_updated_at):
        target = config.target
        credentials = config.credentials
        return (
            config.name, config.address, config.enabled, config.sync_enabled,
            config.sync_interval_seconds, config.verify_ssl, target.site_slug,
            target.device_role_slug, target.platform_slug, target.device_type_slug,
            target.cluster_type_slug, target.cluster_name, credentials.username,
            credentials.token_id.provider, credentials.token_id.key,
            credentials.token_secret.provider, credentials.token_secret.key,
            config.legacy_identity_owner, Jsonb(dict(config.settings)),
            config.id, expected_updated_at,
        )

    def update_source(self, source_id, **changes):
        """Update mutable fields with transactional optimistic concurrency."""

        forbidden = IMMUTABLE_UPDATE_FIELDS.intersection(changes)
        if forbidden:
            raise ValueError(
                'immutable source fields cannot be updated: '
                + ', '.join(sorted(forbidden))
            )
        unknown = set(changes).difference(MUTABLE_UPDATE_FIELDS)
        if unknown:
            raise ValueError('unsupported source update fields: ' + repr(sorted(unknown)))

        existing = self.get_source(source_id)
        if existing is None:
            raise KeyError(source_id)
        if not changes:
            return existing

        candidate = replace(existing.config, **changes)
        self._validate_config(candidate)
        if candidate == existing.config:
            return existing

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        '''
                        UPDATE {} SET
                            name = %s, address = %s, enabled = %s,
                            sync_enabled = %s, sync_interval_seconds = %s,
                            verify_ssl = %s, site_slug = %s,
                            device_role_slug = %s, platform_slug = %s,
                            device_type_slug = %s, cluster_type_slug = %s,
                            cluster_name = %s, username = %s,
                            token_id_provider = %s, token_id_key = %s,
                            token_secret_provider = %s, token_secret_key = %s,
                            legacy_identity_owner = %s, settings = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s AND updated_at = %s
                        RETURNING *
                        '''
                    ).format(self._table('sources')),
                    self._update_parameters(candidate, existing.updated_at),
                )
                row = cursor.fetchone()
                if row is None:
                    raise SourceConcurrentUpdateError(
                        'source changed during transactional update'
                    )
        return self._row_to_record(row)
