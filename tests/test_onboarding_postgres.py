"""Disposable PostgreSQL onboarding compatibility, never production."""

import base64
import os
import secrets
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from netbox_sync.api.onboarding_adapters import RegistrationRegistry
from netbox_sync.application.onboarding import (
    EphemeralOnboardingStore, OnboardingError, SecretReceipt, SourceOnboardingService,
)
from netbox_sync.secret_resolver import FileSecretResolver
from netbox_sync.source_bootstrap import load_runtime_source_configs
from netbox_sync.source_registry import SourceRegistry
from tests.test_onboarding import command, credentials, FakeSecrets, SECRET
from tests.test_source_registry_postgres import _safe_test_dsn
from tests.sample_data import sample_source_config


@pytest.fixture
def registry_database():
    dsn = _safe_test_dsn()
    schema = 'netbox_sync_test_' + uuid.uuid4().hex
    reader = SourceRegistry(lambda: psycopg.connect(dsn), schema)
    reader.initialize()
    try:
        yield RegistrationRegistry(dsn, schema), reader, dsn, schema
    finally:
        assert schema.startswith('netbox_sync_test_')
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


@pytest.mark.parametrize('source_type', ['proxmox', 'esxi'])
def test_postgres_registration_exact_defaults_references_and_duplicates(registry_database, source_type):
    writer, reader, dsn, schema = registry_database
    existing = reader.create_source(sample_source_config()).config
    store = FakeSecrets()
    service = SourceOnboardingService({source_type: lambda _: None}, EphemeralOnboardingStore(), writer, store)
    config = service.register(command(service.test_connection(credentials(source_type)), source_type))
    assert reader.get_source_config(config.id) == config
    assert config.enabled and not config.sync_enabled and not config.legacy_identity_owner
    assert config.credentials.token_secret.provider == 'file'
    assert SECRET not in repr(config)
    assert load_runtime_source_configs({'SOURCE_CONFIG_MODE': 'registry-all',
                                       'NETBOX_SYNC_REGISTRY_DSN': dsn,
                                       'NETBOX_SYNC_REGISTRY_SCHEMA': schema}) == (existing,)
    with pytest.raises(OnboardingError, match='SOURCE_ALREADY_EXISTS'):
        service.register(command(service.test_connection(credentials(source_type)), source_type))
    assert reader.get_source_config(config.id) == config
    assert reader.get_source_config(existing.id) == existing


@pytest.mark.skipif(not hasattr(os, 'geteuid') or getattr(os, 'geteuid', lambda: -1)() != 0,
                    reason='Requires disposable Linux root container')
@pytest.mark.parametrize('source_type', ['proxmox', 'esxi'])
def test_existing_runtime_resolves_broker_created_files(registry_database, tmp_path, source_type):
    from netbox_sync.secret_broker import SecretBrokerStore
    writer, reader, _dsn, _schema = registry_database
    os.chmod(tmp_path, 0o700)
    broker = SecretBrokerStore(tmp_path)
    class Store:
        def create(self, key, value):
            token = broker.create('operation-0123456789abcdef', key, base64.b64encode(value.encode()).decode())
            return SecretReceipt(key, token)
        def rollback(self, receipt):
            broker.rollback('operation-0123456789abcdef', receipt.key, receipt.rollback_token)
    service = SourceOnboardingService({source_type: lambda _: None}, EphemeralOnboardingStore(), writer, Store())
    config = service.register(command(service.test_connection(credentials(source_type)), source_type))
    loaded = reader.get_source_config(config.id)
    resolved = FileSecretResolver(secret_root=Path(tmp_path)).resolve_credentials(loaded.credentials)
    assert resolved.token_secret == SECRET
    assert resolved.token_id == ('token-name' if source_type == 'proxmox' else SECRET)
    assert not loaded.sync_enabled


def test_registration_role_insert_select_only(registry_database):
    _writer, reader, dsn, schema = registry_database
    role = 'netbox_sync_test_role_' + uuid.uuid4().hex
    with psycopg.connect(dsn) as connection:
        password = secrets.token_urlsafe(32)
        connection.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role), sql.Literal(password)))
        connection.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(
            sql.Identifier(schema), sql.Identifier(role)))
        connection.execute(sql.SQL('GRANT SELECT ON {}, {} TO {}').format(
            sql.Identifier(schema, 'schema_meta'), sql.Identifier(schema, 'sources'), sql.Identifier(role)))
        columns = ('id, source_instance, name, source_type, address, enabled, sync_enabled, '
                   'sync_interval_seconds, verify_ssl, site_slug, device_role_slug, platform_slug, '
                   'device_type_slug, cluster_type_slug, cluster_name, username, token_id_provider, '
                   'token_id_key, token_secret_provider, token_secret_key, legacy_identity_owner, settings')
        connection.execute(sql.SQL('GRANT INSERT ({}) ON {} TO {}').format(
            sql.SQL(columns), sql.Identifier(schema, 'sources'), sql.Identifier(role)))
    role_dsn = make_conninfo(dsn, user=role, password=password)
    try:
        service = SourceOnboardingService({'proxmox': lambda _: None}, EphemeralOnboardingStore(),
                                           RegistrationRegistry(role_dsn, schema), FakeSecrets())
        result = service.register(command(service.test_connection(credentials())))
        assert reader.get_source_config(result.id) == result
        for query in ('UPDATE {} SET enabled = false', 'DELETE FROM {}'):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), psycopg.connect(role_dsn) as connection:
                connection.execute(sql.SQL(query).format(sql.Identifier(schema, 'sources')))
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            connection.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


def test_definite_database_rejection_rolls_back_secrets(registry_database):
    writer, reader, dsn, schema = registry_database
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("ALTER TABLE {} ADD CONSTRAINT test_rejection CHECK (name <> 'New source')").format(
            sql.Identifier(schema, 'sources')))
    store = FakeSecrets()
    service = SourceOnboardingService({'proxmox': lambda _: None}, EphemeralOnboardingStore(), writer, store)
    with pytest.raises(OnboardingError, match='REGISTRATION_FAILED'):
        service.register(command(service.test_connection(credentials())))
    assert store.values == {}
    assert reader.list_sources() == ()


@pytest.mark.parametrize('error_type', [ValueError, TypeError])
def test_actual_commit_then_conversion_failure_reconciles(registry_database, monkeypatch, error_type):
    writer, reader, _dsn, _schema = registry_database
    original = SourceRegistry._row_to_record
    conversions = []
    def fail_once(row):
        conversions.append(True)
        if len(conversions) == 1:
            raise error_type('fake post-commit decoding error')
        return original(row)
    monkeypatch.setattr(SourceRegistry, '_row_to_record', staticmethod(fail_once))
    store = FakeSecrets()
    service = SourceOnboardingService({'proxmox': lambda _: None}, EphemeralOnboardingStore(), writer, store)
    result = service.register(command(service.test_connection(credentials())))
    assert reader.get_source_config(result.id) == result
    assert len(conversions) >= 2
    assert len(store.values) == 2
