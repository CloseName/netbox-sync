"""Static and unit contracts for the reproducible v1 deployment foundation."""

import os
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy import install
from netbox_sync import deployment


ROOT = Path(__file__).parents[1]
COMPOSE = ROOT / 'compose.production.yml'


def _release_tree(root, marker='one'):
    for relative in install.REQUIRED_RELEASE_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(marker + '\n', encoding='utf-8')
    return root


def _prepared(root, old_value='old', new_value='new'):
    old = _release_tree(root / 'releases/old', old_value)
    new = _release_tree(root / 'releases/new', new_value)
    (root / 'config').mkdir(parents=True)
    (root / 'config/api.env').write_text('NB_API_URL=https://old.example\n', encoding='utf-8')
    staged = root / 'state/staged/config'
    staged.mkdir(parents=True)
    for name in install.CONFIG_NAMES:
        value = ('NB_API_URL=https://new.example\n' if name == 'api.env'
                 else f'CONFIG_FILE={name}\n')
        (staged / name).write_text(value, encoding='utf-8')
    install.activate_release(root, old)
    return old, install.PreparedDeployment(root, new, staged, 'netbox-sync:new')


def test_canonical_compose_has_private_bundled_postgres_and_one_app_image():
    text = COMPOSE.read_text(encoding='utf-8')
    assert 'postgres:16-bookworm' in text
    postgres = text.split('  postgres:', 1)[1].split('  netbox-sync-api:', 1)[0]
    assert 'netbox-sync-postgres:/var/lib/postgresql/data' in postgres
    assert 'pg_isready' in postgres
    assert 'ports:' not in postgres
    assert 'internal: true' in text
    assert 'x-app: &app' in text
    assert text.count('dockerfile: Dockerfile.web') == 1
    assert text.count('container_name:') == 9
    assert 'container_name: ${NETBOX_SYNC_COMPOSE_PROJECT:-netbox-sync}-postgres' in text
    assert 'name: ${NETBOX_SYNC_COMPOSE_PROJECT:-netbox-sync}' in text
    for service in ('netbox-sync-api', 'netbox-sync-discovery-worker',
                    'netbox-sync-apply-worker', 'netbox-sync-schedule-worker',
                    'netbox-sync-secret-broker', 'netbox-sync-scheduler'):
        assert f'  {service}:' in text


def test_external_postgres_override_is_explicit_and_optional():
    override = (ROOT / 'compose.external-postgres.yml').read_text(encoding='utf-8')
    assert 'postgres:' in override
    assert 'profiles: [bundled-postgres]' in override
    assert 'netbox-sync-api:' in override and 'netbox-sync-egress' in override
    assert 'netbox-sync-schedule-worker:' in override
    assert 'netbox-sync-migrate:' in override


def test_canonical_compose_removes_historical_host_coupling():
    text = COMPOSE.read_text(encoding='utf-8')
    assert 'netbox_default' not in text
    assert 'docker.sock' not in text
    assert '/app/netbox_sync' not in text
    assert 'proxmox_token' not in text
    assert 'esxi_infra' not in text
    assert 'legacy-sources' not in text
    assert '${NETBOX_SYNC_SOURCE_SECRET_DIR' in text


def test_worker_network_and_credential_boundaries_are_preserved():
    text = COMPOSE.read_text(encoding='utf-8')
    api = text.split('  netbox-sync-api:', 1)[1].split('  netbox-sync-secret-broker:', 1)[0]
    broker = text.split('  netbox-sync-secret-broker:', 1)[1].split(
        '  netbox-sync-lifecycle-worker:', 1)[0]
    discovery = text.split('  netbox-sync-discovery-worker:', 1)[1].split(
        '  netbox-sync-apply-worker:', 1)[0]
    apply = text.split('  netbox-sync-apply-worker:', 1)[1].split(
        '  netbox-sync-schedule-worker:', 1)[0]
    schedule = text.split('  netbox-sync-schedule-worker:', 1)[1].split(
        '  netbox-sync-scheduler:', 1)[0]
    assert 'network_mode: none' in broker
    assert 'networks:' not in broker
    assert 'netbox-sync-egress' not in broker
    assert 'broker.env' not in broker
    assert 'cap_add: [CHOWN]' in broker
    assert 'networks: [netbox-sync-db]' in api
    assert 'ports:' not in api
    assert 'web_runtime, serve' in api
    assert 'netbox-sync-db, netbox-sync-egress' in discovery
    assert 'netbox-sync-db, netbox-sync-egress' in apply
    assert 'networks: [netbox-sync-db]' in schedule
    assert 'netbox-sync-egress' not in schedule
    assert 'source-secrets' not in api
    assert 'netbox/apply-token' not in api
    assert 'RUN_WRITER' not in api
    assert 'REGISTRATION' not in discovery + apply + schedule


def test_root_only_secrets_are_read_only_and_limited_to_required_processes():
    text = COMPOSE.read_text(encoding='utf-8')
    for service, following in (
            ('netbox-sync-scheduler', 'netbox-sync-db-roles'),
            ('netbox-sync-db-roles', 'netbox-sync-migrate'),
            ('netbox-sync-migrate', 'netbox-sync-db-grants')):
        block = text.split(f'  {service}:', 1)[1].split(f'  {following}:', 1)[0]
        assert 'user: "0:0"' in block
        assert ':ro' in block
    tools = text.split('  netbox-sync-db-roles:', 1)[1]
    assert '/run/secrets/netbox-sync-db:ro' in tools


def test_canonical_compose_renders_without_provider_configuration():
    if not shutil_which('docker'):
        pytest.skip('Docker CLI is unavailable')
    result = subprocess.run(
        ['docker', 'compose', '-f', str(COMPOSE), 'config', '--quiet'],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def shutil_which(name):
    """Local wrapper keeps pylint from mistaking a test import for installer state."""
    import shutil  # pylint: disable=import-outside-toplevel
    return shutil.which(name)


def test_tracked_systemd_path_has_exactly_one_shared_lock():
    service = (ROOT / 'deploy/systemd/netbox-sync.service').read_text(encoding='utf-8')
    wrapper = (ROOT / 'scripts/run-scheduled-sync.sh').read_text(encoding='utf-8')
    combined = service + wrapper
    assert 'ExecStart=@DEPLOYMENT_ROOT@/current/scripts/run-scheduled-sync.sh' in service
    assert combined.count('/usr/bin/flock') == 1
    assert '/run/netbox-sync/apply.lock' in wrapper
    assert '--remove-orphans' not in wrapper
    assert 'deploy/compose.py' in wrapper
    command = install.compose_command(Path('/opt/netbox-sync'), '--profile', 'scheduled', 'run', '--rm', '--no-deps', 'netbox-sync-scheduler')
    assert str(Path('/opt/netbox-sync/current/compose.production.yml')) in command
    assert '--env-file' in command
    timer = (ROOT / 'deploy/systemd/netbox-sync.timer').read_text(encoding='utf-8')
    assert 'OnUnitActiveSec=60s' in timer
    assert 'AccuracySec=5s' in timer


def test_scheduler_example_uses_actual_registry_all_runtime_boundary():
    environment = (ROOT / 'deploy/examples/scheduler.env').read_text(encoding='utf-8')
    assert 'SOURCE_CONFIG_MODE=registry-all' in environment
    assert 'SYNC_SOURCE_MODE' not in environment


def test_canonical_scripts_never_shell_source_env_files():
    for path in (ROOT / 'scripts').glob('*.sh'):
        text = path.read_text(encoding='utf-8')
        assert 'source ' not in text
        assert '. compose.env' not in text
        assert '.env' not in text or '--env-file' in text


def test_secret_creation_is_exclusive_0600_and_does_not_change_umask(tmp_path):
    path = tmp_path / 'secret'
    before = os.umask(0o022)
    os.umask(before)
    install.write_secret_exclusive(path, 'not-a-real-secret')
    observed = os.umask(0o077)
    os.umask(observed)
    assert observed == before
    if os.name == 'posix':
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        install.write_secret_exclusive(path, 'replacement')
    assert path.read_text(encoding='utf-8') == 'not-a-real-secret\n'


def test_existing_secret_is_reused_and_never_regenerated(tmp_path):
    path = tmp_path / 'owner_password'
    values = iter(('first', 'second'))
    assert install.ensure_secret(path, lambda: next(values)) == 'first'
    assert install.ensure_secret(path, lambda: next(values)) == 'first'


def test_generated_configuration_is_role_separated_and_idempotent(tmp_path):
    for relative in ('config', 'secrets/infrastructure', 'secrets/sources',
                     'secrets/netbox'):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    install.generate_configuration(tmp_path, 'netbox-sync:test-release')
    owner = (tmp_path / 'secrets/infrastructure/owner_password').read_bytes()
    install.generate_configuration(tmp_path, 'netbox-sync:test-release')
    assert (tmp_path / 'secrets/infrastructure/owner_password').read_bytes() == owner
    api = (tmp_path / 'config/api.env').read_text(encoding='utf-8')
    discovery = (tmp_path / 'config/discovery.env').read_text(encoding='utf-8')
    apply = (tmp_path / 'config/apply.env').read_text(encoding='utf-8')
    schedule = (tmp_path / 'config/schedule.env').read_text(encoding='utf-8')
    assert 'netbox_sync_web_reader' in api and 'netbox_sync_registration_writer' in api
    assert 'netbox_sync_discovery_reader' in discovery
    assert 'netbox_sync_apply_registry_reader' in apply and 'netbox_sync_run_writer' in apply
    assert 'netbox_sync_schedule_writer' in schedule
    assert 'PVE_' not in api + discovery + apply + schedule


def test_repeated_configuration_preserves_operator_values_and_adds_missing_keys(tmp_path):
    for relative in ('config', 'secrets/infrastructure', 'secrets/sources',
                     'secrets/netbox'):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    install.generate_configuration(tmp_path, 'netbox-sync:first')
    api_path = tmp_path / 'config/api.env'
    api_path.write_text(
        "NETBOX_SYNC_REGISTRY_DSN=host=custom dbname=registry application_name='has spaces'\n"
        'NB_API_URL=https://netbox.operator.example\n'
        'OPERATOR_PROVIDER_SETTING=preserve-me\n', encoding='utf-8')
    discovery_path = tmp_path / 'config/discovery.env'
    discovery_path.write_text(
        'NETBOX_SYNC_DISCOVERY_NB_API_URL=https://netbox.operator.example\n', encoding='utf-8')

    install.generate_configuration(tmp_path, 'netbox-sync:second')

    api = api_path.read_text(encoding='utf-8')
    assert "NETBOX_SYNC_REGISTRY_DSN=host=custom dbname=registry application_name='has spaces'" in api
    assert 'NB_API_URL=https://netbox.operator.example' in api
    assert 'OPERATOR_PROVIDER_SETTING=preserve-me' in api
    assert 'NETBOX_SYNC_REGISTRATION_DSN=' in api  # a new missing known key was appended
    assert ('NETBOX_SYNC_DISCOVERY_NB_API_URL=https://netbox.operator.example' in
            discovery_path.read_text(encoding='utf-8'))
    assert 'NETBOX_SYNC_IMAGE=netbox-sync:second' in (
        tmp_path / 'config/compose.env').read_text(encoding='utf-8')


def test_config_write_uses_atomic_replace_only_when_content_changes(tmp_path, monkeypatch):
    path = tmp_path / 'config.env'
    calls = []
    real_replace = os.replace

    def replace(source, destination):
        calls.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(os, 'replace', replace)
    install.write_config(path, {'VALUE': 'one'})
    install.write_config(path, {'VALUE': 'one'})
    install.write_config(path, {'VALUE': 'two'})
    assert len(calls) == 2
    assert path.read_text(encoding='utf-8') == 'VALUE=two\n'


def test_prepare_layout_does_not_activate_current(tmp_path):
    source = _release_tree(tmp_path / 'source')
    root = tmp_path / 'target'
    prepared = install.prepare_layout(root, source, 'release-one', 'netbox-sync:one')
    assert prepared.release == root / 'releases/release-one'
    assert prepared.config.is_dir()
    assert f'NETBOX_SYNC_CONFIG_DIR={prepared.config}' in (
        prepared.config / 'compose.env').read_text(encoding='utf-8')
    assert not (root / 'current').exists()


def test_same_release_content_is_safe_but_different_content_is_rejected(tmp_path):
    source = _release_tree(tmp_path / 'source')
    releases = tmp_path / 'releases'
    releases.mkdir()
    first = install.install_release(source, releases, 'release-one')
    assert install.install_release(source, releases, 'release-one') == first
    (source / 'Dockerfile.web').write_text('changed\n', encoding='utf-8')
    with pytest.raises(install.InstallError, match='different content'):
        install.install_release(source, releases, 'release-one')


def test_release_id_is_required_except_for_check():
    with pytest.raises(SystemExit, match='--release-id is required'):
        install.main(['--no-systemd'])


@pytest.mark.skipif(os.name != 'posix', reason='atomic directory symlink replacement is POSIX-only')
def test_successful_activation_switches_current_and_publishes_config(tmp_path, monkeypatch):
    old, prepared = _prepared(tmp_path)
    monkeypatch.setattr(install, 'install_systemd', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(install, 'start_runtime', lambda _prepared: None)
    install.activate_prepared(prepared, install_units=True, start_services=True)
    assert (tmp_path / 'current').resolve() == prepared.release.resolve()
    assert (tmp_path / 'config/api.env').read_text(encoding='utf-8') == (
        'NB_API_URL=https://new.example\n')
    assert old.exists()


@pytest.mark.skipif(os.name != 'posix', reason='atomic directory symlink replacement is POSIX-only')
def test_activation_failure_restores_current_and_config(tmp_path, monkeypatch):
    old, prepared = _prepared(tmp_path)
    monkeypatch.setattr(
        install, 'install_systemd',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(install.InstallError('unit failure')))
    with pytest.raises(install.InstallError, match='unit failure'):
        install.activate_prepared(prepared, install_units=True, start_services=False)
    assert (tmp_path / 'current').resolve() == old.resolve()
    assert (tmp_path / 'config/api.env').read_text(encoding='utf-8') == (
        'NB_API_URL=https://old.example\n')


@contextmanager
def _recording_lock(events):
    events.append('lock-acquired')
    try:
        yield
    finally:
        events.append('lock-released')


def test_upgrade_stops_timer_and_acquires_shared_lock_before_prepare(tmp_path, monkeypatch):
    _old, prepared = _prepared(tmp_path)
    events = []
    monkeypatch.setattr(install, 'validate_prerequisites', lambda **_kwargs: None)
    monkeypatch.setattr(install.shutil, 'which', lambda _name: 'systemctl')
    monkeypatch.setattr(install, 'prepare_layout', lambda *_args: prepared)
    monkeypatch.setattr(install, 'resolve_public_url', lambda *_args: 'https://sync.example.test')
    monkeypatch.setattr(install, 'initialize_tls_layout', lambda *_args: None)
    monkeypatch.setattr(install, 'validate_tls_material', lambda *_args: None)
    monkeypatch.setattr(install, 'configure_tls', lambda *_args: None)
    monkeypatch.setattr(install, 'stop_timer', lambda: events.append('timer-stopped'))
    monkeypatch.setattr(install, 'check_legacy_dropin', lambda _root: None)
    monkeypatch.setattr(install, 'shared_apply_lock',
                        lambda _path: _recording_lock(events))
    monkeypatch.setattr(install, 'prepare_stack', lambda _prepared: events.append('migrated'))
    monkeypatch.setattr(install, 'activate_prepared',
                        lambda *_args, **_kwargs: events.append('activated'))
    monkeypatch.setattr(install, 'run', lambda command, **_kwargs: events.append(command[-1]))
    assert install.main(['--root', str(tmp_path), '--source', str(tmp_path),
                         '--release-id', 'new', '--no-start']) == 0
    assert events[:4] == ['timer-stopped', 'lock-acquired', 'migrated', 'activated']
    assert events[-1] == 'lock-released'


@pytest.mark.parametrize('failed_service', ['netbox-sync-migrate', 'netbox-sync-db-grants'])
def test_database_prepare_failure_leaves_current_unchanged(tmp_path, monkeypatch, failed_service):
    old, prepared = _prepared(tmp_path)

    def command_result(command, **_kwargs):
        if failed_service in command:
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(returncode=0, stdout='')

    monkeypatch.setattr(install, 'run', command_result)
    monkeypatch.setattr(install, '_wait_for_postgres', lambda *_args: None)
    with pytest.raises(subprocess.CalledProcessError):
        install.prepare_stack(prepared)
    assert (tmp_path / 'current').resolve() == old.resolve()
    assert (tmp_path / 'config/api.env').read_text(encoding='utf-8') == (
        'NB_API_URL=https://old.example\n')


def test_prepare_failure_keeps_timer_stopped_and_never_activates(tmp_path, monkeypatch):
    old, prepared = _prepared(tmp_path)
    events = []
    monkeypatch.setattr(install, 'validate_prerequisites', lambda **_kwargs: None)
    monkeypatch.setattr(install.shutil, 'which', lambda _name: 'systemctl')
    monkeypatch.setattr(install, 'prepare_layout', lambda *_args: prepared)
    monkeypatch.setattr(install, 'resolve_public_url', lambda *_args: 'https://sync.example.test')
    monkeypatch.setattr(install, 'initialize_tls_layout', lambda *_args: None)
    monkeypatch.setattr(install, 'validate_tls_material', lambda *_args: None)
    monkeypatch.setattr(install, 'configure_tls', lambda *_args: None)
    monkeypatch.setattr(install, 'stop_timer', lambda: events.append('timer-stopped'))
    monkeypatch.setattr(install, 'check_legacy_dropin', lambda _root: None)
    monkeypatch.setattr(install, 'shared_apply_lock',
                        lambda _path: _recording_lock(events))
    monkeypatch.setattr(
        install, 'prepare_stack',
        lambda _prepared: (_ for _ in ()).throw(install.InstallError('migration failed')))
    monkeypatch.setattr(install, 'activate_prepared',
                        lambda *_args, **_kwargs: events.append('activated'))
    monkeypatch.setattr(install, 'run', lambda command, **_kwargs: events.append(command[-1]))
    assert install.main(['--root', str(tmp_path), '--source', str(tmp_path),
                         '--release-id', 'new']) == 1
    assert events == ['timer-stopped', 'lock-acquired', 'lock-released']
    assert (tmp_path / 'current').resolve() == old.resolve()


def test_env_file_preserves_libpq_spaces_without_shell_parsing(tmp_path):
    path = tmp_path / 'service.env'
    value = "host=postgres dbname=netbox_sync user=test password='contains spaces'"
    install.write_config(path, {'DATABASE_DSN': value})
    assert path.read_text(encoding='utf-8') == f'DATABASE_DSN={value}\n'
    if os.name == 'posix':
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def _legacy_environment_tree(root, compose_lines):
    (root / 'config').mkdir(parents=True)
    for name in install.CONFIG_NAMES:
        payload = compose_lines if name == 'compose.env' else f'FILE={name}\n'
        (root / 'config' / name).write_text(payload, encoding='utf-8')


def test_legacy_environment_migration_is_explicit_and_preserves_unknown_keys(tmp_path):
    _legacy_environment_tree(
        tmp_path,
        'INFRA_SYNC_IMAGE=example.invalid/image:one\nOPERATOR_KEY=preserved\n')
    before = (tmp_path / 'config/compose.env').read_bytes()
    assert install.migrate_legacy_environment(tmp_path) == 1
    assert (tmp_path / 'config/compose.env').read_bytes() == before

    assert install.migrate_legacy_environment(tmp_path, apply=True) == 1
    assert (tmp_path / 'config/compose.env').read_text(encoding='utf-8') == (
        'NETBOX_SYNC_IMAGE=example.invalid/image:one\nOPERATOR_KEY=preserved\n')


def test_legacy_environment_migration_removes_equal_duplicate_and_rejects_conflict(tmp_path):
    _legacy_environment_tree(
        tmp_path,
        'INFRA_SYNC_IMAGE=example.invalid/image:one\n'
        'NETBOX_SYNC_IMAGE=example.invalid/image:one\n')
    assert install.migrate_legacy_environment(tmp_path, apply=True) == 1
    assert (tmp_path / 'config/compose.env').read_text(encoding='utf-8') == (
        'NETBOX_SYNC_IMAGE=example.invalid/image:one\n')

    (tmp_path / 'config/compose.env').write_text(
        'INFRA_SYNC_IMAGE=example.invalid/image:old\n'
        'NETBOX_SYNC_IMAGE=example.invalid/image:new\n', encoding='utf-8')
    before = (tmp_path / 'config/compose.env').read_bytes()
    with pytest.raises(install.InstallError, match='conflicting legacy environment key'):
        install.migrate_legacy_environment(tmp_path, apply=True)
    assert (tmp_path / 'config/compose.env').read_bytes() == before


def test_legacy_environment_migration_rejects_unknown_product_key_without_writes(tmp_path):
    _legacy_environment_tree(tmp_path, 'INFRA_SYNC_UNKNOWN_EXTENSION=sensitive-value\n')
    before = (tmp_path / 'config/compose.env').read_bytes()
    with pytest.raises(install.InstallError, match='unrecognized legacy environment key'):
        install.migrate_legacy_environment(tmp_path, apply=True)
    assert (tmp_path / 'config/compose.env').read_bytes() == before


def test_legacy_environment_migration_translates_state_names_without_touching_secrets(
        tmp_path):
    secret = 'do-not-log-or-change-this-value'
    _legacy_environment_tree(
        tmp_path,
        'INFRA_SYNC_COMPOSE_PROJECT=infra-sync\n'
        'INFRA_SYNC_CONFIG_DIR=/opt/infra-sync/config\n'
        'INFRA_SYNC_REGISTRY_SCHEMA=infra_sync\n'
        'INFRA_SYNC_REGISTRY_DSN=postgresql://infra_sync_web_reader:' + secret +
        '@postgres:5432/infra_sync?connect_timeout=5\n')
    install.migrate_legacy_environment(tmp_path, apply=True)
    migrated = (tmp_path / 'config/compose.env').read_text(encoding='utf-8')
    assert 'NETBOX_SYNC_COMPOSE_PROJECT=netbox-sync\n' in migrated
    assert 'NETBOX_SYNC_CONFIG_DIR=/opt/netbox-sync/config\n' in migrated
    assert 'NETBOX_SYNC_REGISTRY_SCHEMA=netbox_sync\n' in migrated
    assert ('postgresql://netbox_sync_web_reader:' + secret +
            '@postgres:5432/netbox_sync?connect_timeout=5') in migrated
    assert secret in migrated


def test_release_permission_normalization_excludes_secret_policy(tmp_path):
    if os.name != 'posix':
        pytest.skip('POSIX modes are not represented by the Windows filesystem')
    root = tmp_path / 'release'
    script = root / 'scripts' / 'run.sh'
    code = root / 'netbox_sync' / 'module.py'
    script.parent.mkdir(parents=True)
    code.parent.mkdir(parents=True)
    script.write_text('#!/bin/sh\n', encoding='utf-8')
    code.write_text('VALUE = 1\n', encoding='utf-8')
    install.normalize_release_permissions(root)
    assert stat.S_IMODE(script.stat().st_mode) == 0o755
    assert stat.S_IMODE(code.stat().st_mode) == 0o644


def test_database_role_matrix_is_complete_and_has_no_secret_literals():
    assert set(deployment.DATABASE_ROLES) == {
        'owner', 'web_reader', 'registration_writer', 'discovery_reader',
        'apply_registry_reader', 'registry_reader', 'run_writer', 'schedule_writer',
        'operation_writer', 'lifecycle_writer',
    }
    source = (ROOT / 'netbox_sync/deployment.py').read_text(encoding='utf-8')
    assert 'DELETE' not in source
    assert 'TRUNCATE' not in source
    assert 'sql.Literal(password)' in source


def test_database_tool_sanitizes_failures(monkeypatch, capsys):
    marker = 'SENSITIVE_VALUE_MUST_NOT_LEAK'
    monkeypatch.setattr(deployment, 'bootstrap_roles', lambda: (_ for _ in ()).throw(
        RuntimeError(marker)))
    assert deployment.main(['bootstrap-roles']) == 1
    output = capsys.readouterr()
    assert marker not in output.out + output.err
    assert 'bootstrap-roles failed' in output.err


class _NamingCursor:
    def __init__(self, phase, statements):
        self.phase = phase
        self.statements = statements
        self.query = ''

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, parameters=None):
        self.query = str(query)
        self.parameters = parameters
        self.statements.append((self.phase, self.query, parameters))

    def fetchall(self):
        if 'pg_class' in self.query:
            return [('alembic_version', 'r'), ('schema_meta', 'r'),
                    ('sources', 'r'), ('sync_runs', 'r')]
        if 'pg_namespace' in self.query:
            return [(deployment.LEGACY_SCHEMA_NAME,)]
        if 'pg_tables' in self.query:
            return [(name,) for name in
                    ('alembic_version', 'schema_meta', 'sources', 'sync_runs')]
        if 'pg_database' in self.query:
            return [(deployment.LEGACY_DATABASE_NAME,)]
        if 'pg_roles' in self.query:
            return [(name,) for name in (
                deployment.LEGACY_BOOTSTRAP_ROLE,
                *deployment.LEGACY_DATABASE_ROLES.values())]
        return []

    def fetchone(self):
        if 'alembic_version' in self.query:
            return ('0002_sync_run_history',)
        if 'pg_stat_activity' in self.query:
            return (0,)
        if 'SELECT 1 FROM pg_roles' in self.query:
            return None
        return None


class _NamingConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._cursor


def test_database_naming_migration_requires_confirmation_and_preloads_passwords(monkeypatch):
    monkeypatch.setattr(deployment.psycopg, 'connect',
                        lambda *_args, **_kwargs: pytest.fail('database was contacted'))
    with pytest.raises(deployment.DeploymentError, match='confirmation'):
        deployment.migrate_database_naming({})

    environment = {'NETBOX_SYNC_NAMING_CONFIRM': deployment.NAMING_CONFIRMATION}
    monkeypatch.setattr(deployment, 'read_password',
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            deployment.DeploymentError('credential unavailable')))
    with pytest.raises(deployment.DeploymentError, match='credential unavailable'):
        deployment.migrate_database_naming(environment)


def test_database_naming_migration_renames_only_preflighted_state(monkeypatch):
    statements = []
    cursors = iter(_NamingCursor(phase, statements) for phase in ('legacy', 'cluster', 'target'))
    monkeypatch.setattr(deployment.psycopg, 'connect',
                        lambda *_args, **_kwargs: _NamingConnection(next(cursors)))
    monkeypatch.setattr(deployment, '_legacy_connection_info', lambda *_args: '')
    monkeypatch.setattr(deployment, 'connection_info', lambda *_args: '')
    monkeypatch.setattr(deployment, 'read_password', lambda key, _env: 'test-' + key)
    deployment.migrate_database_naming({
        'NETBOX_SYNC_NAMING_CONFIRM': deployment.NAMING_CONFIRMATION})

    rendered = '\n'.join(query for _phase, query, _parameters in statements)
    assert 'DROP' not in rendered and 'CASCADE' not in rendered
    assert rendered.count('CREATE ROLE') >= len(deployment.DATABASE_ROLES) + 1
    assert 'ALTER DATABASE' in rendered
    assert 'ALTER SCHEMA' in rendered
    assert 'DROP ROLE' not in rendered


class _OwnershipCursor:
    def __init__(self, database_owner='netbox_sync_owner', schema_owner='netbox_sync_owner',
                 table_owners=('netbox_sync_owner',)):
        self.database_owner = database_owner
        self.schema_owner = schema_owner
        self.table_owners = table_owners
        self.query = ''

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, _parameters=None):
        self.query = query

    def fetchone(self):
        if 'pg_database' in self.query:
            return (self.database_owner,)
        return None if self.schema_owner is None else (self.schema_owner,)

    def fetchall(self):
        return [(f'table-{index}', owner) for index, owner in enumerate(self.table_owners)]


class _OwnershipConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._cursor


def test_migration_ownership_preflight_accepts_owner_and_missing_schema(monkeypatch):
    for cursor in (_OwnershipCursor(), _OwnershipCursor(schema_owner=None, table_owners=())):
        monkeypatch.setattr(deployment.psycopg, 'connect',
                            lambda *_args, current=cursor, **_kwargs: _OwnershipConnection(current))
        monkeypatch.setattr(deployment, 'connection_info', lambda *_args, **_kwargs: '')
        deployment.validate_migration_ownership({'NETBOX_SYNC_REGISTRY_SCHEMA': 'netbox_sync'})


def test_migration_ownership_preflight_rejects_foreign_table_owner(monkeypatch):
    cursor = _OwnershipCursor(table_owners=('legacy_owner',))
    monkeypatch.setattr(deployment.psycopg, 'connect',
                        lambda *_args, **_kwargs: _OwnershipConnection(cursor))
    monkeypatch.setattr(deployment, 'connection_info', lambda *_args, **_kwargs: '')
    with pytest.raises(deployment.DeploymentError, match='table owners'):
        deployment.validate_migration_ownership({'NETBOX_SYNC_REGISTRY_SCHEMA': 'netbox_sync'})


def test_lf_policy_covers_deployment_artifacts():
    attributes = (ROOT / '.gitattributes').read_text(encoding='utf-8')
    for pattern in ('*.py text eol=lf', '*.sh text eol=lf', '*.yml text eol=lf',
                    '*.service text eol=lf', '*.timer text eol=lf'):
        assert pattern in attributes


@pytest.mark.parametrize('existing_config', [False, True])
def test_fresh_runtime_failure_then_new_release_preserves_credentials(tmp_path, monkeypatch, existing_config):
    source = _release_tree(tmp_path / 'repo')
    root = tmp_path / 'target'
    first = install.prepare_layout(root, source, 'failed-release', 'netbox-sync:failed')
    if existing_config:
        install.generate_configuration(root, 'netbox-sync:previous')
        with (root / 'config/api.env').open('a') as stream:
            stream.write('OPERATOR_SETTING=preserved\n')
    snapshot = install._config_snapshot(root)
    passwords = {p.name: p.read_bytes() for p in (root / 'secrets/infrastructure').iterdir()}
    stopped = []
    monkeypatch.setattr(install, 'install_systemd', lambda *a, **k: None)
    monkeypatch.setattr(install, 'quiesce_uncertain_runtime', lambda prepared: stopped.append(prepared.release))
    def fail_start(prepared):
        raise install.InstallError('proxy mount creation failed')
    monkeypatch.setattr(install, 'start_runtime', fail_start)
    with pytest.raises(install.InstallError, match='proxy mount'):
        install.activate_prepared(first, install_units=True, start_services=True)
    install._cleanup_prepared(first)
    assert not (root / 'current').exists()
    assert install._config_snapshot(root) == snapshot
    assert not first.config.exists()
    assert first.release.exists() and stopped == [first.release]
    second = install.prepare_layout(root, source, 'fixed-release', 'netbox-sync:fixed')
    assert {p.name: p.read_bytes() for p in (root / 'secrets/infrastructure').iterdir()} == passwords
    assert 'NETBOX_SYNC_POSTGRES_VOLUME=netbox-sync-postgres-data' in (second.config / 'compose.env').read_text()
    if existing_config:assert 'OPERATOR_SETTING=preserved' in (second.config / 'api.env').read_text()
    monkeypatch.setattr(install, 'start_runtime', lambda prepared: None)
    install.activate_prepared(second, install_units=True, start_services=True)
    assert (root / 'current').resolve() == second.release.resolve()
    assert first.release.exists()
    assert {p.name: p.read_bytes() for p in (root / 'secrets/infrastructure').iterdir()} == passwords
    install._cleanup_prepared(second)


@pytest.mark.parametrize('owner', ['foreign', 'matching'])
def test_canonical_container_names_require_matching_compose_ownership(tmp_path, monkeypatch, owner):
    config=tmp_path/'config';config.mkdir();(config/'compose.env').write_text('NETBOX_SYNC_COMPOSE_PROJECT=netbox-sync\n')
    calls=[]
    def run(command, **kwargs):
        calls.append(command)
        if command[1]=='ps':return SimpleNamespace(stdout='netbox-sync-postgres\n')
        return SimpleNamespace(stdout=__import__('json').dumps({'com.docker.compose.project':'netbox-sync' if owner=='matching' else 'foreign', 'com.docker.compose.service':'postgres'}))
    monkeypatch.setattr(install,'run',run)
    prepared=SimpleNamespace(config=config)
    if owner=='foreign':
        with pytest.raises(install.ContainerNameConflict):install.validate_container_names(prepared)
    else:install.validate_container_names(prepared)
    assert all(command[1] in ('ps','inspect') for command in calls)


def test_installer_waits_for_final_postgres_tcp_listener(monkeypatch):
    from types import SimpleNamespace
    calls=[]
    monkeypatch.setattr(install,'compose_command',lambda root,*args,**kwargs:list(args))
    monkeypatch.setattr(install,'run',lambda command,**kwargs:(calls.append(command) or SimpleNamespace(returncode=0)))
    install._wait_for_postgres(None,None,None)
    assert calls[0][calls[0].index('pg_isready')+1:][:2]==['-h','127.0.0.1']
    assert 'pg_isready -h 127.0.0.1' in COMPOSE.read_text()
