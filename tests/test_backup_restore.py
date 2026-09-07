"""Unit and static contracts for supported backup/restore operations."""

import datetime as dt
import contextlib
import json
import os
import stat
import tarfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy import backup, install
from netbox_sync import deployment


ROOT = Path(__file__).parents[1]


class FakeDatabase:
    """Standard-dump boundary without requiring PostgreSQL in unit tests."""

    mode = 'bundled'

    def __init__(self, *, sources=2, runs=3, revision=backup.ALEMBIC_HEAD, major=16):
        self.sources = sources
        self.runs = runs
        self.revision = revision
        self.major = major
        self.restore_calls = 0
        self.restored_schema = None

    def metadata(self):
        return {
            'postgres_major': self.major, 'alembic_revision': self.revision,
            'source_count': self.sources, 'run_count': self.runs,
        }

    def dump(self, destination):
        destination.write_bytes(b'PGDMP\x01fixture')

    def source_secret_references(self):
        if not self.sources:
            return []
        return [{
            'source_instance': 'pve-test', 'token_id_provider': 'file',
            'token_id_key': 'source-token', 'token_secret_provider': 'file',
            'token_secret_key': 'source-token',
        }]

    def verify_dump(self, dump):
        if not dump.read_bytes().startswith(b'PGDMP'):
            raise backup.BackupError('dump unreadable')

    def reconcile_operations(self):
        self.operations_reconciled = True

    def postgres_major(self):
        return self.major

    def target_counts(self):
        return 0, 0

    def validate_empty_target(self):
        if self.target_counts() != (0, 0):
            raise backup.BackupError("fresh restore target contains registry or run-history rows")

    def validate_foundation_target(self):
        return None

    def restore_fresh(self, dump, _maintenance, source_schema=backup.SCHEMA_NAME):
        self.verify_dump(dump)
        self.restore_calls += 1
        self.restored_schema = source_schema


def _layout(root):
    for relative, mode in (
            ('releases/r1', 0o755), ('config', 0o700), ('secrets', 0o700),
            ('secrets/infrastructure', 0o700), ('secrets/sources', 0o700),
            ('secrets/netbox', 0o700), ('backups', 0o700), ('state', 0o750),
            ('run', 0o750)):
        path = root / relative
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(mode)
    install.activate_release(root, root / 'releases/r1')
    for name in install.CONFIG_NAMES:
        text = ('NETBOX_SYNC_COMPOSE_PROJECT=test-project\nNETBOX_SYNC_IMAGE=netbox-sync:test\nUNKNOWN_KEY=preserved\n'
                if name == 'compose.env' else f'FILE={name}\n')
        path = root / 'config' / name
        path.write_text(text, encoding='utf-8')
        path.chmod(0o600)
    for name in install.PASSWORD_NAMES:
        path = root / 'secrets/infrastructure' / f'{name}_password'
        path.write_text(f'not-a-real-{name}\n', encoding='utf-8')
        path.chmod(0o600)
    for directory, name, value in (
            ('sources', 'source-token', 'not-a-real-source-secret'),
            ('netbox', 'read-token', 'not-a-real-read-token'),
            ('netbox', 'apply-token', 'not-a-real-apply-token')):
        path = root / 'secrets' / directory / name
        path.write_text(value + '\n', encoding='utf-8')
        path.chmod(0o600)
    return root


def _fake_xattr(path, name, **_kwargs):
    if 'secrets/sources/' not in Path(path).as_posix():
        raise OSError('not a broker file')
    return {
        'user.netbox_sync.operation': b'operation-do-not-disclose',
        'user.netbox_sync.receipt': b'receipt-do-not-disclose',
        'user.netbox_sync.complete': b'1',
    }[name]


def _portable_tar(root, destination):
    def metadata(info):
        if info.name == 'secrets/sources/source-token':
            path = root / info.name
            for name in os.listxattr(path, follow_symlinks=False):
                value = os.getxattr(path, name, follow_symlinks=False)
                info.pax_headers['SCHILY.xattr.' + name] = value.decode('ascii')
        return info

    with tarfile.open(destination, 'w') as archive:
        archive.add(root / 'config', arcname='config', recursive=True, filter=metadata)
        archive.add(root / 'secrets', arcname='secrets', recursive=True, filter=metadata)
    destination.chmod(0o600)


@pytest.fixture
def bundle_setup(tmp_path, monkeypatch):
    root = _layout(tmp_path / 'root')
    monkeypatch.setattr(backup, '_require_gnu_tar', lambda: None)
    monkeypatch.setattr(backup, '_tar_create', _portable_tar)
    monkeypatch.setattr(backup, 'Maintenance', lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(backup.os, 'listxattr',
                        lambda *_args, **_kwargs: list(backup.BROKER_XATTR_SETS[0]),
                        raising=False)
    monkeypatch.setattr(backup.os, 'getxattr', _fake_xattr, raising=False)
    return root, FakeDatabase()


def test_backup_bundle_is_versioned_complete_and_preserves_unknown_config(bundle_setup):
    root, database = bundle_setup
    created = dt.datetime(2026, 9, 6, 12, 0, tzinfo=dt.timezone.utc)
    bundle = backup.create_backup(root, root / 'backups', database, now=created)
    assert bundle.name == 'netbox-sync-backup-20260906-120000'
    assert set(path.name for path in bundle.iterdir()) == {
        'database.dump', 'state.tar', 'manifest.json', 'checksums.sha256', 'COMPLETE'}
    if os.name == 'posix':
        assert all(stat.S_IMODE((bundle / name).stat().st_mode) == 0o600
                   for name in ('database.dump', 'state.tar', 'manifest.json',
                                'checksums.sha256'))
    manifest = backup.verify_bundle(bundle, database)
    assert manifest['backup_format_version'] == 1
    assert manifest['source_count'] == 2 and manifest['run_count'] == 3
    assert manifest['compose_project'] == 'test-project'
    assert manifest['active_release_id'] == 'r1'
    with tarfile.open(bundle / 'state.tar') as archive:
        assert b'UNKNOWN_KEY=preserved' in archive.extractfile('config/compose.env').read()


def test_manifest_never_contains_secret_or_broker_receipt(bundle_setup):
    root, database = bundle_setup
    bundle = backup.create_backup(root, root / 'backups', database)
    manifest = (bundle / 'manifest.json').read_text(encoding='utf-8')
    assert 'not-a-real-source-secret' not in manifest
    assert 'not-a-real-read-token' not in manifest
    assert 'receipt-do-not-disclose' not in manifest
    source = next(item for item in json.loads(manifest)['files']
                  if item['path'] == 'secrets/sources/source-token')
    assert set(source['xattrs']) == set(backup.BROKER_XATTR_SETS[0])
    assert all(value.startswith('sha256:') for value in source['xattrs'].values())


def test_unmanaged_source_secret_without_broker_xattrs_is_preserved(bundle_setup, monkeypatch):
    root, database = bundle_setup
    monkeypatch.setattr(backup.os, 'listxattr', lambda *_args, **_kwargs: [])
    bundle = backup.create_backup(root, root / 'backups', database)
    manifest = backup.verify_bundle(bundle, database)
    source = next(item for item in manifest['files']
                  if item['path'] == 'secrets/sources/source-token')
    assert source['xattrs'] == {}


def test_partial_broker_xattr_set_fails_closed(bundle_setup, monkeypatch):
    root, database = bundle_setup
    monkeypatch.setattr(backup.os, 'listxattr',
                        lambda *_args, **_kwargs: ['user.netbox_sync.operation'])
    with pytest.raises(backup.BackupError, match='xattrs are incomplete'):
        backup.create_backup(root, root / 'backups', database)


def test_legacy_broker_xattr_set_remains_backup_compatible(bundle_setup, monkeypatch):
    root, database = bundle_setup
    legacy = backup.BROKER_XATTR_SETS[1]
    values = dict(zip(legacy, (b'operation-do-not-disclose',
                               b'receipt-do-not-disclose', b'1')))
    monkeypatch.setattr(backup.os, 'listxattr', lambda *_args, **_kwargs: list(legacy))
    monkeypatch.setattr(backup.os, 'getxattr',
                        lambda _path, name, **_kwargs: values[name])
    bundle = backup.create_backup(root, root / 'backups', database)
    manifest = backup.verify_bundle(bundle, database)
    source = next(item for item in manifest['files']
                  if item['path'] == 'secrets/sources/source-token')
    assert set(source['xattrs']) == set(legacy)


def test_checksum_corruption_is_rejected_before_database_validation(bundle_setup):
    root, database = bundle_setup
    bundle = backup.create_backup(root, root / 'backups', database)
    (bundle / 'database.dump').write_bytes(b'corrupted')
    with pytest.raises(backup.BackupError, match='integrity'):
        backup.verify_bundle(bundle, database)


def test_archive_traversal_is_rejected_before_restore(bundle_setup):
    root, database = bundle_setup
    bundle = backup.create_backup(root, root / 'backups', database)
    with tarfile.open(bundle / 'state.tar', 'w') as archive:
        info = tarfile.TarInfo('../outside')
        info.size = 1
        archive.addfile(info, fileobj=__import__('io').BytesIO(b'x'))
    backup._write_checksums(bundle)  # pylint: disable=protected-access
    with pytest.raises(backup.BackupError, match='unsafe path'):
        backup.verify_bundle(bundle)


def test_unsupported_future_format_is_rejected(bundle_setup):
    root, database = bundle_setup
    bundle = backup.create_backup(root, root / 'backups', database)
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    manifest['backup_format_version'] = 2
    (bundle / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    backup._write_checksums(bundle)  # pylint: disable=protected-access
    with pytest.raises(backup.BackupError, match='format'):
        backup.verify_bundle(bundle)


def test_failed_dump_never_publishes_or_marks_bundle_complete(bundle_setup):
    root, database = bundle_setup

    def fail(_destination):
        raise backup.BackupError('pg_dump failed')

    database.dump = fail
    with pytest.raises(backup.BackupError):
        backup.create_backup(root, root / 'backups', database)
    assert not list((root / 'backups').glob('netbox-sync-backup-*'))
    assert not list((root / 'backups').glob('.*.tmp-*'))


def test_failed_archive_never_publishes_bundle(bundle_setup, monkeypatch):
    root, database = bundle_setup
    monkeypatch.setattr(backup, '_tar_create',
                        lambda *_args: (_ for _ in ()).throw(backup.BackupError('tar failed')))
    with pytest.raises(backup.BackupError):
        backup.create_backup(root, root / 'backups', database)
    assert not list((root / 'backups').iterdir())


def test_transient_config_entry_is_rejected_not_archived(bundle_setup):
    root, database = bundle_setup
    (root / 'config/api.env.tmp').write_text('transient\n', encoding='utf-8')
    with pytest.raises(backup.BackupError, match='non-canonical'):
        backup.create_backup(root, root / 'backups', database)


def test_zero_source_backup_is_valid(bundle_setup):
    root, _database = bundle_setup
    database = FakeDatabase(sources=0, runs=0)
    bundle = backup.create_backup(root, root / 'backups', database)
    manifest = backup.verify_bundle(bundle, database)
    assert (manifest['source_count'], manifest['run_count']) == (0, 0)


@pytest.mark.parametrize('revision', ['future_revision', '', None])
def test_newer_or_unknown_database_revision_is_rejected(revision):
    manifest = {'alembic_revision': revision, 'postgres_major': 16}
    with pytest.raises(backup.BackupError, match='revision'):
        backup._compatible(manifest, 16)  # pylint: disable=protected-access


def test_older_revision_can_restore_forward_but_older_postgres_cannot():
    backup._compatible({'alembic_revision': '0001_registry_baseline',
                        'postgres_major': 16}, 17)  # pylint: disable=protected-access
    with pytest.raises(backup.BackupError, match='PostgreSQL'):
        backup._compatible({'alembic_revision': backup.ALEMBIC_HEAD,
                            'postgres_major': 17}, 16)  # pylint: disable=protected-access


def test_fresh_restore_check_rejects_populated_target_before_writes(bundle_setup):
    root, database = bundle_setup
    bundle = backup.create_backup(root, root / 'backups', database)
    database.target_counts = lambda: (1, 0)
    with pytest.raises(backup.BackupError, match='contains registry'):
        backup.restore_fresh(root, bundle, database, check_only=True)
    assert database.restore_calls == 0


def test_fresh_restore_check_is_read_only(bundle_setup):
    root, database = bundle_setup
    bundle = backup.create_backup(root, root / 'backups', database)
    manifest = backup.restore_fresh(root, bundle, database, check_only=True)
    assert manifest['source_count'] == 2
    assert database.restore_calls == 0


def test_fresh_restore_replaces_state_and_runs_provisioning_in_order(
        bundle_setup, monkeypatch, tmp_path):
    source, database = bundle_setup
    bundle = backup.create_backup(source, source / 'backups', database)
    target = _layout(tmp_path / 'target')
    (target / 'config/compose.env').write_text(
        'NETBOX_SYNC_COMPOSE_PROJECT=target-before-restore\n', encoding='utf-8')
    stages = []
    monkeypatch.setattr(backup, 'Maintenance', lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(backup, '_require_gnu_tar', lambda: None)

    def extract(archive, destination):
        with tarfile.open(archive) as payload:
            payload.extractall(destination, filter='data')

    monkeypatch.setattr(backup, '_tar_extract', extract)
    monkeypatch.setattr(backup, '_validate_restored_files', lambda *_args: None)
    monkeypatch.setattr(backup, '_run_deployment_tool',
                        lambda _root, service, *_args, **_kwargs: stages.append(service))
    monkeypatch.setattr(backup, '_start_restored_runtime',
                        lambda _root, _mode: stages.append('runtime-health'))
    backup.restore_fresh(target, bundle, database, no_systemd=True)
    assert database.restore_calls == 1
    assert stages == [
        'netbox-sync-migrate', 'netbox-sync-db-grants', 'netbox-sync-db-restore-roles',
        'runtime-health']
    assert 'UNKNOWN_KEY=preserved' in (target / 'config/compose.env').read_text(
        encoding='utf-8')
    assert 'NETBOX_SYNC_COMPOSE_PROJECT=target-before-restore' in (
        target / 'config/compose.env').read_text(encoding='utf-8')
    assert (target / 'secrets/sources/source-token').read_text(
        encoding='utf-8').strip() == 'not-a-real-source-secret'


def test_legacy_bundle_environment_is_translated_before_database_restore(
        bundle_setup, monkeypatch, tmp_path):
    source, database = bundle_setup
    bundle = backup.create_backup(source, source / 'backups', database)
    target = _layout(tmp_path / 'target')
    original_manifest = backup.verify_bundle(bundle, database)
    legacy_manifest = {
        **original_manifest,
        'product': backup.LEGACY_PRODUCT,
        'database_name': backup.LEGACY_DATABASE_NAME,
        'schema_name': backup.LEGACY_SCHEMA_NAME,
        'alembic_revision': '0002_sync_run_history',
    }
    events = []
    monkeypatch.setattr(backup, 'verify_bundle', lambda *_args: legacy_manifest)
    monkeypatch.setattr(backup, '_require_gnu_tar', lambda: None)
    monkeypatch.setattr(backup, '_validate_restored_files', lambda *_args: None)
    monkeypatch.setattr(backup, 'Maintenance', lambda *_args, **_kwargs: nullcontext())

    def extract(_archive, destination):
        _layout(destination)
        (destination / 'config/compose.env').write_text(
            'INFRA_SYNC_COMPOSE_PROJECT=legacy-project\nOPERATOR_KEY=preserved\n',
            encoding='utf-8')

    monkeypatch.setattr(backup, '_tar_extract', extract)
    monkeypatch.setattr(install, 'migrate_legacy_environment',
                        lambda root, apply=False: events.append(('env', root, apply)) or 1)
    original_restore = database.restore_fresh

    def restore(dump, maintenance, source_schema=backup.SCHEMA_NAME):
        events.append(('database', source_schema))
        return original_restore(dump, maintenance, source_schema)

    database.restore_fresh = restore
    monkeypatch.setattr(backup, '_run_deployment_tool', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(backup, '_start_restored_runtime', lambda *_args: None)
    backup.restore_fresh(target, bundle, database, no_systemd=True)
    assert events[0][0] == 'env'
    assert events[0][2] is True
    assert events[1] == ('database', backup.LEGACY_SCHEMA_NAME)


def test_restore_role_passwords_changes_bootstrap_last(monkeypatch, tmp_path):
    secret_root = tmp_path / 'passwords'
    secret_root.mkdir()
    for filename in deployment.PASSWORD_FILES.values():
        (secret_root / filename).write_text('restored-runtime\n', encoding='utf-8')
    (secret_root / deployment.RESTORE_BOOTSTRAP_FILE).write_text(
        'restored-bootstrap\n', encoding='utf-8')
    environment = {'NETBOX_SYNC_DB_PASSWORD_DIR': str(secret_root)}
    calls = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(deployment, 'bootstrap_roles',
                        lambda _env: calls.append('runtime-roles'))
    monkeypatch.setattr(deployment, 'connection_info', lambda *_args: 'redacted')
    monkeypatch.setattr(deployment.psycopg, 'connect', lambda *_args, **_kwargs: Connection())
    monkeypatch.setattr(deployment, '_rotate_bootstrap_password',
                        lambda _cursor, password: calls.append(('bootstrap', password)))
    deployment.restore_role_passwords(environment)
    assert calls == ['runtime-roles', ('bootstrap', 'restored-bootstrap')]


def test_bootstrap_password_rotation_preserves_privileged_role_attributes():
    statements = []

    class Cursor:
        def execute(self, statement):
            statements.append(statement.as_string(None))

    deployment._rotate_bootstrap_password(  # pylint: disable=protected-access
        Cursor(), 'not-a-real-password')
    assert statements == [
        "ALTER ROLE \"netbox_sync_bootstrap\" WITH LOGIN PASSWORD "
        "'not-a-real-password'"
    ]
    assert 'NOSUPERUSER' not in statements[0]


def test_database_tool_never_places_external_dsn_in_argv(monkeypatch, tmp_path):
    observed = []

    def fake_run(command, **kwargs):
        observed.append((command, kwargs['env']))
        return SimpleNamespace(returncode=0, stdout='160000\n', stderr='')

    monkeypatch.setattr(backup.shutil, 'which', lambda _name: '/usr/bin/tool')
    monkeypatch.setattr(backup.subprocess, 'run', fake_run)
    literal = 'postgresql://operator:secret@example/netbox_sync_backup_test'
    tool = backup.DatabaseTool(tmp_path, 'external', {'NETBOX_SYNC_BACKUP_DSN': literal})
    assert tool.postgres_major() == 16
    command, environment = observed[0]
    assert literal not in ' '.join(command)
    assert literal not in environment.values()
    assert environment['PGHOST'] == 'example'
    assert environment['PGDATABASE'] == 'netbox_sync_backup_test'
    assert environment['PGUSER'] == 'operator'
    assert environment['PGPASSWORD'] == 'secret'
    assert 'NETBOX_SYNC_BACKUP_DSN' not in environment


def test_external_restore_selects_database_without_exposing_dsn(monkeypatch, tmp_path):
    observed = []
    literal = 'postgresql://operator:secret@example/netbox_sync_backup_test'
    tool = backup.DatabaseTool(tmp_path, 'external', {'NETBOX_SYNC_BACKUP_DSN': literal})
    monkeypatch.setattr(
        tool, '_run',
        lambda executable, arguments, **kwargs: observed.append(
            (executable, arguments, kwargs)))

    tool.restore(tmp_path / 'database.dump')

    arguments = observed[0][1]
    assert arguments[-2:] == ('--dbname', 'netbox_sync_backup_test')
    assert literal not in ' '.join(arguments)


def test_fresh_database_restore_requires_live_maintenance_boundary(monkeypatch,
                                                                   tmp_path):
    observed = []
    tool = backup.DatabaseTool(tmp_path)
    monkeypatch.setattr(tool, 'validate_foundation_target', lambda: None)
    monkeypatch.setattr(tool, 'validate_empty_target', lambda: None)
    monkeypatch.setattr(
        tool, '_run',
        lambda executable, arguments, **kwargs: observed.append(
            (executable, arguments, kwargs)))

    class MaintenanceBoundary:
        def __init__(self, authorized):
            self.authorized = authorized

        def authorizes_fresh_restore(self, root, mode):
            return self.authorized and root == tmp_path and mode == 'bundled'

    with pytest.raises(backup.BackupError, match='maintenance boundary'):
        tool.restore_fresh(tmp_path / 'database.dump', MaintenanceBoundary(False))
    assert observed == []

    tool.restore_fresh(tmp_path / 'database.dump', MaintenanceBoundary(True))
    assert [entry[0] for entry in observed] == ['psql', 'pg_restore']
    cleanup = observed[0][1][-1]
    assert cleanup == (
        'DROP TABLE IF EXISTS netbox_sync.sync_runs; '
        'DROP TABLE IF EXISTS netbox_sync.sources; '
        'DROP TABLE IF EXISTS netbox_sync.source_tombstones; '
        'DROP TABLE IF EXISTS netbox_sync.source_operations; '
        'DROP TABLE IF EXISTS netbox_sync.schema_meta; '
        'DROP TABLE IF EXISTS netbox_sync.alembic_version; '
        'DROP FUNCTION IF EXISTS netbox_sync.guard_source_credential_refs(); '
        'DROP SCHEMA netbox_sync')
    assert 'CASCADE' not in cleanup
    assert observed[1][2]['input_file'] == tmp_path / 'database.dump'
    assert '--clean' not in observed[1][1]


def test_fresh_restore_converts_verified_legacy_schema_without_cascade(monkeypatch,
                                                                       tmp_path):
    observed = []
    tool = backup.DatabaseTool(tmp_path)
    monkeypatch.setattr(tool, 'validate_foundation_target', lambda: None)
    monkeypatch.setattr(tool, 'validate_empty_target', lambda: None)
    monkeypatch.setattr(tool, '_run', lambda executable, arguments, **kwargs:
                        observed.append((executable, arguments, kwargs)))

    class Boundary:
        @staticmethod
        def authorizes_fresh_restore(root, mode):
            return root == tmp_path and mode == 'bundled'

    tool.restore_fresh(
        tmp_path / 'database.dump', Boundary(), source_schema='infra_sync')
    assert [item[0] for item in observed] == ['psql', 'pg_restore', 'psql']
    assert observed[-1][1][-1] == 'ALTER SCHEMA infra_sync RENAME TO netbox_sync'
    assert all('CASCADE' not in ' '.join(item[1]) for item in observed)


def test_bundle_inspection_is_allowlisted(bundle_setup):
    root, database = bundle_setup
    bundle = backup.create_backup(root, root / 'backups', database)
    result = backup.inspect_bundle(bundle, database)
    assert set(result) == {
        'created_at', 'application_version', 'release_id', 'source_count', 'run_count',
        'postgres_major', 'alembic_revision', 'size_bytes', 'checksum_status'}
    assert result['checksum_status'] == 'valid'


def test_compose_has_restore_role_tool_but_runtime_services_receive_no_credentials():
    compose = (ROOT / 'compose.production.yml').read_text(encoding='utf-8')
    assert 'netbox-sync-db-restore-roles:' in compose
    restore = compose.split('  netbox-sync-db-restore-roles:', 1)[1].split('\nvolumes:', 1)[0]
    assert 'restore-role-passwords' in restore
    assert 'NETBOX_SYNC_RESTORE_PASSWORD_DIR' in restore
    api = compose.split('  netbox-sync-api:', 1)[1].split('  netbox-sync-secret-broker:', 1)[0]
    assert 'RESTORE_PASSWORD' not in api


def test_backup_scope_excludes_runtime_and_release_payloads():
    assert backup.STATE_DIRS == ('config', 'secrets')
    source = (ROOT / 'deploy/backup.py').read_text(encoding='utf-8')
    for excluded in ('/run/netbox-sync-broker', 'node_modules', 'docker.sock'):
        assert excluded not in source


def test_maintenance_restores_prior_services_and_timer(monkeypatch, tmp_path):
    calls = []

    @contextlib.contextmanager
    def lock(_path):
        calls.append('lock-enter')
        yield
        calls.append('lock-exit')

    monkeypatch.setattr(install, 'stop_timer', lambda: calls.append('timer-stop') or True)
    monkeypatch.setattr(install, 'shared_apply_lock', lock)
    monkeypatch.setattr(install, 'compose_command',
                        lambda _root, *args, **_kwargs: list(args))

    def run(command, **_kwargs):
        calls.append(tuple(command))
        if command[:4] == ['ps', '--status', 'running', '--services']:
            return SimpleNamespace(stdout='netbox-sync-api\nnetbox-sync-apply-worker\n')
        return SimpleNamespace(stdout='', returncode=0)

    monkeypatch.setattr(install, 'run', run)
    with backup.Maintenance(tmp_path, restore_after=True):
        calls.append('inside')
    assert calls.index('timer-stop') < calls.index('lock-enter') < calls.index('inside')
    assert ('stop', *backup.MAINTENANCE_SERVICES) in calls
    assert ('up', '-d', 'netbox-sync-api', 'netbox-sync-apply-worker') in calls
    assert ('systemctl', 'start', 'netbox-sync.timer') in calls
    assert calls[-1] == 'lock-exit'


def test_restore_maintenance_never_restarts_writers_or_timer(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(install, 'stop_timer', lambda: True)
    monkeypatch.setattr(install, 'shared_apply_lock', lambda _path: nullcontext())
    monkeypatch.setattr(install, 'compose_command',
                        lambda _root, *args, **_kwargs: list(args))
    monkeypatch.setattr(install, 'run', lambda command, **_kwargs:
                        calls.append(tuple(command)) or SimpleNamespace(stdout='', returncode=0))
    with backup.Maintenance(tmp_path, restore_after=False):
        pass
    assert not any(call[:2] == ('up', '-d') for call in calls)
    assert ('systemctl', 'start', 'netbox-sync.timer') not in calls


def test_backup_lock_failure_restores_previous_timer_state(monkeypatch, tmp_path):
    calls = []

    class Locked:
        def __enter__(self):
            raise install.InstallError('active sync')

        def __exit__(self, *_args):
            calls.append('unexpected-exit')

    monkeypatch.setattr(install, 'stop_timer', lambda: True)
    monkeypatch.setattr(install, 'shared_apply_lock', lambda _path: Locked())
    monkeypatch.setattr(install, 'run',
                        lambda command, **_kwargs: calls.append(tuple(command)))
    with pytest.raises(install.InstallError, match='active sync'):
        with backup.Maintenance(tmp_path, restore_after=True):
            pass
    assert 'unexpected-exit' not in calls
    assert ('systemctl', 'start', 'netbox-sync.timer') in calls


@pytest.mark.skipif(os.name != 'posix', reason='Linux xattr and GNU tar contract')
def test_gnu_tar_round_trip_preserves_mode_owner_and_broker_xattrs(tmp_path):
    try:
        backup._require_gnu_tar()  # pylint: disable=protected-access
        source = tmp_path / 'source'
        (source / 'config').mkdir(parents=True)
        (source / 'secrets/sources').mkdir(parents=True)
        (source / 'config/compose.env').write_text('KEY=value\n', encoding='utf-8')
        secret = source / 'secrets/sources/token'
        secret.write_text('not-a-real-secret\n', encoding='utf-8')
        secret.chmod(0o600)
        current_xattrs = backup.BROKER_XATTR_SETS[0]
        for name, value in zip(current_xattrs, (b'op', b'receipt', b'1')):
            os.setxattr(secret, name, value, follow_symlinks=False)
    except (AttributeError, OSError, backup.BackupError) as exc:
        pytest.skip(f'xattrs unavailable: {exc}')
    archive = tmp_path / 'state.tar'
    backup._tar_create(source, archive)  # pylint: disable=protected-access
    destination = tmp_path / 'destination'
    destination.mkdir()
    backup._tar_extract(archive, destination)  # pylint: disable=protected-access
    restored = destination / 'secrets/sources/token'
    assert stat.S_IMODE(restored.stat().st_mode) == 0o600
    assert (restored.stat().st_uid, restored.stat().st_gid) == (
        secret.stat().st_uid, secret.stat().st_gid)
    assert [os.getxattr(restored, name, follow_symlinks=False)
            for name in current_xattrs] == [b'op', b'receipt', b'1']


def test_captured_operator_failure_never_contains_secret(monkeypatch, capsys):
    monkeypatch.setattr(backup, 'DatabaseTool', lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(backup.BackupError('literal-secret')))
    assert backup.main(['--root', '.', 'verify', 'missing']) == 1
    captured = capsys.readouterr()
    assert 'literal-secret' not in captured.err
    assert 'DSN' not in captured.err
    assert 'BACKUP_INVALID' in captured.err


def test_stable_restore_failure_codes_are_secret_free():
    assert backup._failure_code(  # pylint: disable=protected-access
        'restore', backup.BackupError('fresh restore target contains registry rows')) == \
        'RESTORE_TARGET_NOT_EMPTY'
    assert backup._failure_code(  # pylint: disable=protected-access
        'restore', backup.BackupError('backup database revision is newer or unsupported')) == \
        'RESTORE_INCOMPATIBLE'


def test_external_backup_executes_the_same_client_binary_it_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(backup.shutil, 'which', lambda _: '/reviewed/pg16/pg_restore')
    tool = backup.DatabaseTool(tmp_path, 'external', {'NETBOX_SYNC_BACKUP_DSN':'dbname=netbox_sync_backup_test'})
    assert tool._command('pg_restore', '--version') == ['/reviewed/pg16/pg_restore','--version']

@pytest.mark.parametrize('counts', ['1|0', '0|1'])
def test_fresh_restore_rejects_orphan_operation_or_tombstone(monkeypatch, tmp_path, counts):
    tool = backup.DatabaseTool(tmp_path)
    monkeypatch.setattr(tool, 'target_counts', lambda: (0, 0))
    monkeypatch.setattr(tool, 'query', lambda _statement: [counts])
    with pytest.raises(backup.BackupError, match='operation or tombstone'):
        tool.validate_empty_target()
