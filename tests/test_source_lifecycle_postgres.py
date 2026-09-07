"""Isolated PostgreSQL tests for lifecycle transitions before runtime integration."""
from contextlib import contextmanager
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from uuid import uuid4

import pytest
from psycopg import sql

from netbox_sync.source_lifecycle import LifecycleStore, LifecycleError
from netbox_sync.source_operations import OperationStore
from netbox_sync.source_config import SecretReference, SourceCredentials
from netbox_sync.run_history import postgres_run_repository, RunTrigger, RunStatus
from tests.test_migrations_postgres import migration_database, _upgrade
from tests.test_source_registry_postgres import _safe_test_dsn
from tests.sample_data import sample_source_config


@pytest.fixture
def lifecycle(migration_database):
    registry, engine = migration_database
    _upgrade(registry, engine)
    source = sample_source_config()
    registry.create_source(source)
    gate = Lock()
    @contextmanager
    def lock(_):
        with gate:
            yield
    return LifecycleStore(_safe_test_dsn(), registry.schema, 'test-only', lock=lock), registry, source


def remove(store, source, cleanup=lambda _: None, credentials=False):
    view = store.read(source)
    return store.remove(source, view['revision'], source, credentials, cleanup)


def test_remove_retains_identity_and_stops_schedule(lifecycle):
    store, registry, source = lifecycle
    calls = []
    result = remove(store, source.source_instance, calls.append)
    assert result['removed_at'] and result['credential_state'] == 'RETAINED_BY_REQUEST'
    saved = registry.get_by_source_instance(source.source_instance)
    assert saved is not None and not saved.config.enabled and not saved.config.sync_enabled
    assert not calls
    assert store.read(source.source_instance) == result
    with pytest.raises(LifecycleError, match='SOURCE_ALREADY_REMOVED'):
        remove(store, source.source_instance)


def test_id_typing_and_concurrent_configuration_fail_closed(lifecycle):
    store, registry, source = lifecycle
    version = store.read(source.source_instance)['revision']
    with pytest.raises(LifecycleError, match='SOURCE_CONFIRMATION_INVALID'):
        store.remove(source.source_instance, version, 'another-source', False, lambda _: None)
    registry.update_source(source.id, name='Changed name')
    with pytest.raises(LifecycleError, match='SOURCE_LIFECYCLE_CONFLICT'):
        store.remove(source.source_instance, version, source.source_instance, False, lambda _: None)


@pytest.mark.parametrize('kind', ['PLAN', 'DISCOVERY'])
def test_active_operation_blocks_removal(lifecycle, kind):
    store, _, source = lifecycle
    operations = OperationStore(_safe_test_dsn(), store.schema)
    operations.start(source.source_instance, kind)
    with pytest.raises(LifecycleError, match='SOURCE_OPERATION_ACTIVE'):
        remove(store, source.source_instance)
    assert store.read(source.source_instance)['removed_at'] is None


@pytest.mark.parametrize('status', ['RUNNING', 'OUTCOME_UNCERTAIN', 'PARTIALLY_APPLIED'])
def test_unconfirmed_apply_evidence_blocks_removal(lifecycle, status):
    store, _, source = lifecycle
    repository = postgres_run_repository(_safe_test_dsn(), store.schema)
    run = repository.start_run(source.source_instance, 'proxmox', RunTrigger.MANUAL, 'test')
    if status != 'RUNNING':
        repository.finish_run(run.run_id, RunStatus(status))
    with pytest.raises(LifecycleError, match='SOURCE_APPLY_UNCONFIRMED'):
        remove(store, source.source_instance)


def exclusive(registry, source):
    refs = SourceCredentials('operator', SecretReference('file', 'tokenid-'+'x'*24),
                             SecretReference('file', 'tokensecret-'+'y'*24))
    registry.update_source(source.id, credentials=refs)
    return refs


def test_exclusive_credentials_only_after_tombstone_commit(lifecycle):
    store, registry, source = lifecycle
    refs = exclusive(registry, source)
    calls = []
    def cleanup(keys):
        assert store.read(source.source_instance)['removed_at']
        calls.extend(keys)
    result = remove(store, source.source_instance, cleanup, True)
    assert result['credential_state'] == 'REMOVED'
    assert set(calls) == {refs.token_id.key, refs.token_secret.key}


def test_shared_and_legacy_credentials_are_retained(lifecycle):
    store, registry, source = lifecycle
    refs = exclusive(registry, source)
    registry.create_source(replace(source, id='other-source', source_instance='other-source', credentials=refs))
    calls = []
    result = remove(store, source.source_instance, calls.append, True)
    assert result['credential_state'] == 'RETAINED_SHARED_OR_LEGACY' and not calls
    assert registry.get_by_source_instance('other-source').config.enabled


def test_broker_failure_does_not_roll_back_tombstone(lifecycle):
    store, registry, source = lifecycle
    exclusive(registry, source)
    def cleanup(_):
        raise RuntimeError('SECRET SHOULD NOT BE REPORTED')
    result = remove(store, source.source_instance, cleanup, True)
    assert result['removed_at'] and result['credential_state'] == 'CLEANUP_FAILED'
    assert 'SECRET SHOULD' not in str(result)


def test_concurrent_removal_has_one_transition(lifecycle):
    store, _, source = lifecycle
    revision = store.read(source.source_instance)['revision']
    def call():
        try:
            return store.remove(source.source_instance, revision, source.source_instance, False, lambda _: None)
        except LifecycleError as exc:
            return exc.code
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: call(), range(2)))
    assert sum(isinstance(item, dict) for item in results) == 1
    assert 'SOURCE_ALREADY_REMOVED' in results


def test_column_limited_lifecycle_role_can_take_credential_gate(lifecycle):
    store, _, _ = lifecycle
    role = 'ui6_test_' + uuid4().hex
    with store.connect() as owner:
        owner.execute(sql.SQL('CREATE ROLE {}').format(sql.Identifier(role)))
        owner.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(store.schema), sql.Identifier(role)))
        owner.execute(sql.SQL('GRANT SELECT, UPDATE(enabled,sync_enabled) ON {} TO {}').format(store.table('sources'), sql.Identifier(role)))
        owner.commit()
        try:
            owner.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
            owner.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                          (f'netbox-sync:{store.schema}:credential-refs',))
            owner.rollback()
        finally:
            owner.rollback()
            owner.execute('RESET ROLE')
            owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            owner.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


def test_active_reader_excludes_only_removed_sources(lifecycle):
    from netbox_sync.api.lifecycle_adapters import ActiveSourceReader
    from netbox_sync.api.settings import ApiSettings
    store, registry, source = lifecycle
    registry.create_source(replace(source, id='other-source', source_instance='other-source'))
    reader = ActiveSourceReader(ApiSettings(registry_dsn=_safe_test_dsn(), registry_schema=store.schema))
    assert len(reader.read()) == 2
    remove(store, source.source_instance)
    assert [row['source_instance'] for row in reader.read()] == ['other-source']
    assert reader.read(source.source_instance) == ()


def test_reserved_registration_and_schedule_updates_are_blocked(lifecycle):
    from netbox_sync.api.lifecycle_adapters import LifecycleRegistrationRegistry, LifecycleScheduleStore, ReservedSourceError
    from netbox_sync.schedule_worker import ScheduleWorkerError
    store, registry, source = lifecycle
    registration = LifecycleRegistrationRegistry(_safe_test_dsn(), store.schema)
    assert registration.find(source.source_instance) is not None
    remove(store, source.source_instance)
    with pytest.raises(ReservedSourceError):
        registration.find(source.source_instance)
    schedule = LifecycleScheduleStore(_safe_test_dsn(), store.schema)
    with pytest.raises(ScheduleWorkerError, match='SOURCE_NOT_FOUND'):
        schedule.update({'source_instance': source.source_instance, 'sync_enabled': True,
                         'sync_interval_seconds':600, 'expected_sync_enabled':False,
                         'expected_sync_interval_seconds':600})
    assert not registry.get_by_source_instance(source.source_instance).config.sync_enabled


def test_removed_credential_refs_cannot_be_reassigned(lifecycle):
    from psycopg.errors import CheckViolation
    store, registry, source = lifecycle
    refs = exclusive(registry, source)
    remove(store, source.source_instance, lambda _: None, True)
    with pytest.raises(CheckViolation):
        registry.create_source(replace(source, id='new-source', source_instance='new-source', credentials=refs))
