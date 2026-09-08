#!/usr/bin/env python3
"""Transactional non-interactive foundation installer for a Debian host."""

import argparse
import contextlib
import hashlib
import os
import re
import runpy
import ssl
import stat
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


ROLE_USERS = {
    'owner': 'netbox_sync_owner',
    'web_reader': 'netbox_sync_web_reader',
    'registration_writer': 'netbox_sync_registration_writer',
    'discovery_reader': 'netbox_sync_discovery_reader',
    'apply_registry_reader': 'netbox_sync_apply_registry_reader',
    'registry_reader': 'netbox_sync_registry_reader',
    'run_writer': 'netbox_sync_run_writer',
    'schedule_writer': 'netbox_sync_schedule_writer',
    'operation_writer': 'netbox_sync_operation_writer',
    'lifecycle_writer': 'netbox_sync_lifecycle_writer',
}
PASSWORD_NAMES = ('postgres_bootstrap', *ROLE_USERS)
RELEASE_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
IGNORED_NAMES = frozenset({
    '.git', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.coverage', 'coverage.xml',
    'htmlcov', 'build', 'dist', 'node_modules', '__pycache__', '.codex-test-tmp',
    'secrets', 'privkey.pem',
    '.venv', 'venv', '.idea', '.vscode',
})
CONFIG_NAMES = ('compose.env', 'api.env', 'discovery.env', 'apply.env',
                'schedule.env', 'scheduler.env', 'broker.env')
ENV_KEY_PATTERN = re.compile(r'^[A-Z][A-Z0-9_]*$')
LEGACY_ENV_SUFFIXES = frozenset({
    'APPLY_LOCK_DIR', 'APPLY_NB_API_URL', 'APPLY_NB_TOKEN_FILE',
    'APPLY_REGISTRY_DSN', 'APPLY_SOCKET', 'BACKUP_DSN', 'BROKER_SOCKET',
    'COMPOSE_PROJECT', 'CONFIG_DIR', 'DB_HOST', 'DB_NAME', 'DB_PASSWORD_DIR',
    'DB_PORT', 'DIAGNOSTICS_STALE_SECONDS', 'DISCOVERY_NB_API_URL',
    'DISCOVERY_NB_TOKEN_FILE', 'DISCOVERY_REGISTRY_DSN', 'DISCOVERY_SOCKET',
    'IMAGE', 'INFRA_SECRET_DIR', 'LEGACY_SOURCE_SECRET_DIR',
    'NETBOX_SECRET_DIR', 'ONBOARDING_ALLOWED_CIDRS', 'ONBOARDING_ALLOWED_HOSTS',
    'ONBOARDING_ALLOWED_SUFFIXES', 'ONBOARDING_DENIED_CIDRS',
    'POSTGRES_IMAGE', 'POSTGRES_VOLUME', 'REGISTRATION_DSN', 'REGISTRY_DSN',
    'REGISTRY_SCHEMA', 'RESTORE_PASSWORD_DIR', 'RUN_WRITER_DSN',
    'SCHEDULE_SOCKET', 'SCHEDULE_WRITER_DSN', 'SOURCE_SECRET_DIR', 'WEB_DIST',
    'WEB_PORT', 'WRITE_HOSTS',
})
REQUIRED_RELEASE_FILES = (
    'compose.production.yml', 'Dockerfile.web', 'deploy/nginx.conf.template',
    'compose.external-ingress.yml', 'deploy/nginx.external-ingress.conf.template', 'deploy/compose.py',
    'deploy/backup.py',
    'deploy/systemd/netbox-sync.service',
    'deploy/systemd/netbox-sync.timer', 'scripts/run-scheduled-sync.sh',
)


class InstallError(RuntimeError):
    """Safe installation failure."""


@dataclass(frozen=True)
class PreparedDeployment:
    """Release and protected configuration staged before activation."""

    root: Path
    release: Path
    config: Path
    image: str


def run(command, *, check=True, capture_output=False):
    """Run a fixed operator command without shell parsing."""
    return subprocess.run(  # noqa: S603
        command, check=check, text=True, capture_output=capture_output)


def validate_prerequisites(*, require_systemd=True):
    """Verify required host tools without writing host state."""
    if sys.version_info < (3, 10):
        raise InstallError('Python 3.10 or newer is required')
    for executable in ('docker', 'install', 'flock'):
        if shutil.which(executable) is None:
            raise InstallError(f'required executable is missing: {executable}')
    result = run(['docker', 'compose', 'version'], check=False)
    if result.returncode:
        raise InstallError('Docker Compose v2 is required')
    if require_systemd and shutil.which('systemctl') is None:
        raise InstallError('systemd is required unless --no-systemd is used')


def ensure_directory(path, mode):
    """Create or normalize one non-secret layout directory."""
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(mode)


def write_secret_exclusive(path, value):
    """Create one secret atomically without changing process-global umask."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, (value + '\n').encode('utf-8'))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def ensure_secret(path, generator=lambda: secrets.token_urlsafe(36)):
    """Generate once; reruns never rotate or overwrite an existing secret."""
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
            raise InstallError(f'invalid existing secret path: {path.name}')
        path.chmod(0o600)
        value = path.read_text(encoding='utf-8').rstrip('\r\n')
        if not value or '\n' in value or '\r' in value:
            raise InstallError(f'invalid existing secret file: {path.name}')
        return value
    value = generator()
    write_secret_exclusive(path, value)
    return value


def normalize_release_permissions(root):
    """Make packaged code readable while never traversing persistent secrets."""
    for path in root.rglob('*'):
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o755)
        elif path.suffix == '.sh' or path == root / 'deploy' / 'install.py':
            path.chmod(0o755)
        else:
            path.chmod(0o644)


def _ignore(_directory, names):
    return [name for name in names if (name in IGNORED_NAMES or name.endswith(('.pyc', '.log', '.key'))
                                       or name == '.env' or name.endswith('.env'))]


def _release_digest(root):
    """Digest the packaged file set so a release id cannot alias different code."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*'), key=lambda item: item.as_posix()):
        relative = path.relative_to(root)
        if any(part in IGNORED_NAMES for part in relative.parts):
            continue
        if path.is_symlink():
            raise InstallError('release source must not contain symbolic links')
        if path.is_dir() or path.name.endswith(('.pyc', '.log', '.env', '.key')) or path.name == '.env':
            continue
        digest.update(relative.as_posix().encode('utf-8') + b'\0')
        digest.update(path.read_bytes())
    return digest.hexdigest()


def validate_release(release):
    """Reject incomplete or link-substituted deployment artifacts."""
    for relative in REQUIRED_RELEASE_FILES:
        path = release / relative
        if path.is_symlink() or not path.is_file():
            raise InstallError(f'release artifact is missing: {relative}')


def install_release(source, releases, release_id):
    """Copy an immutable release once and normalize its public code modes."""
    destination = releases / release_id
    source_digest = _release_digest(source)
    if destination.exists():
        if not destination.is_dir() or _release_digest(destination) != source_digest:
            raise InstallError('release id already exists with different content')
    else:
        shutil.copytree(source, destination, ignore=_ignore)
    normalize_release_permissions(destination)
    validate_release(destination)
    return destination


def activate_release(root, release):
    """Atomically point current at the selected immutable release."""
    current = root / 'current'
    if current.is_symlink() and current.resolve() == release.resolve():
        return
    temporary = root / f'.current-{os.getpid()}'
    try:
        temporary.unlink()
    except FileNotFoundError:
        pass
    temporary.symlink_to(release, target_is_directory=True)
    os.replace(temporary, current)


def current_release(root):
    """Return a bounded active release and reject ambiguous current paths."""
    current = root / 'current'
    if not os.path.lexists(current):
        return None
    if not current.is_symlink():
        raise InstallError('current must be a symbolic link managed by the installer')
    try:
        target = current.resolve(strict=True)
        target.relative_to((root / 'releases').resolve())
    except (FileNotFoundError, ValueError) as exc:
        raise InstallError('current points outside the managed release directory') from exc
    return target


def _dsn(user, password):
    return (f'postgresql://{quote(user, safe="")}:{quote(password, safe="")}@'
             'postgres:5432/netbox_sync?connect_timeout=5')


def _atomic_write(path, payload):
    """Atomically replace one protected file only when its bytes changed."""
    encoded = payload.encode('utf-8')
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise InstallError(f'invalid config path: {path.name}')
        if path.read_bytes() == encoded:
            path.chmod(0o600)
            return False
    temporary = path.with_name(path.name + f'.tmp-{os.getpid()}')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    path.chmod(0o600)
    return True


def _migrated_legacy_value(value):
    """Translate only exact product-state tokens inside a reviewed product key."""
    return (value.replace('/opt/infra-sync', '/opt/netbox-sync')
            .replace('/run/infra-sync', '/run/netbox-sync')
            .replace('infra-sync-', 'netbox-sync-')
            .replace('infra_sync_', 'netbox_sync_')
            .replace('/infra_sync?', '/netbox_sync?')
            .replace('/infra_sync', '/netbox_sync')
            if value not in {'infra-sync', 'infra_sync'} else
            {'infra-sync': 'netbox-sync', 'infra_sync': 'netbox_sync'}[value])


def migrate_legacy_environment(root, *, apply=False):
    """Translate only reviewed INFRA_SYNC keys without exposing their values."""
    root = Path(root)
    prepared = {}
    migrated = 0
    for filename in CONFIG_NAMES:
        path = root / 'config' / filename
        if filename == 'broker.env' and not path.exists():
            continue  # UI-6 adds this file after validating/translating an older bundle.
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise InstallError(f'invalid config path: {filename}')
        lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
        values = {}
        for line in lines:
            stripped = line.rstrip('\r\n')
            if not stripped or stripped.lstrip().startswith('#'):
                continue
            key, separator, value = stripped.partition('=')
            if not separator or not ENV_KEY_PATTERN.fullmatch(key) or key in values:
                raise InstallError(f'invalid config file: {filename}')
            values[key] = value
        output = []
        for line in lines:
            stripped = line.rstrip('\r\n')
            key, separator, value = stripped.partition('=')
            if not separator or not key.startswith('INFRA_SYNC_'):
                output.append(line)
                continue
            suffix = key.removeprefix('INFRA_SYNC_')
            if suffix not in LEGACY_ENV_SUFFIXES:
                raise InstallError(f'unrecognized legacy environment key in {filename}')
            target = 'NETBOX_SYNC_' + suffix
            value = _migrated_legacy_value(value)
            if target in values:
                if values[target] != value:
                    raise InstallError(f'conflicting legacy environment key in {filename}')
                migrated += 1
                continue
            ending = line[len(stripped):] or '\n'
            output.append(f'{target}={value}{ending}')
            migrated += 1
        prepared[path] = ''.join(output)
    if apply:
        for path, payload in prepared.items():
            _atomic_write(path, payload)
    return migrated


def write_config(path, values):
    """Write a protected Docker env-file; it is deliberately not shell syntax."""
    _atomic_write(path, ''.join(f'{key}={value}\n' for key, value in values.items()))


def _merged_config(path, defaults, replacements=None):
    """Preserve existing env lines verbatim and append only missing known keys."""
    replacements = replacements or {}
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise InstallError(f'invalid config path: {path.name}')
        original = path.read_text(encoding='utf-8')
    else:
        original = ''
    lines = original.splitlines(keepends=True)
    seen = set()
    output = []
    for line in lines:
        stripped = line.rstrip('\r\n')
        if not stripped or stripped.lstrip().startswith('#'):
            output.append(line)
            continue
        key, separator, _value = stripped.partition('=')
        if not separator or not ENV_KEY_PATTERN.fullmatch(key) or key in seen:
            raise InstallError(f'invalid config file: {path.name}')
        seen.add(key)
        ending = line[len(stripped):] or '\n'
        output.append(f'{key}={replacements[key]}{ending}' if key in replacements else line)
    if output and not output[-1].endswith(('\n', '\r')):
        output[-1] += '\n'
    for key, value in defaults.items():
        if key not in seen:
            output.append(f'{key}={replacements.get(key, value)}\n')
    return ''.join(output)


def _configuration_values(root, image):
    """Return generated defaults without treating operator settings as secrets."""
    secret_root = root / 'secrets' / 'infrastructure'
    passwords = {
        name: ensure_secret(secret_root / f'{name}_password') for name in PASSWORD_NAMES
    }
    dsns = {key: _dsn(user, passwords[key]) for key, user in ROLE_USERS.items()}
    common = {'NETBOX_SYNC_REGISTRY_SCHEMA': 'netbox_sync'}
    return {
        'compose.env': {
            'NETBOX_SYNC_COMPOSE_PROJECT': 'netbox-sync', 'NETBOX_SYNC_IMAGE': image,
            'NETBOX_SYNC_CONFIG_DIR': str(root / 'config'),
            'NETBOX_SYNC_INFRA_SECRET_DIR': str(secret_root),
            'NETBOX_SYNC_SOURCE_SECRET_DIR': str(root / 'secrets' / 'sources'),
            'NETBOX_SYNC_NETBOX_SECRET_DIR': str(root / 'secrets' / 'netbox'),
            'NETBOX_SYNC_APPLY_LOCK_DIR': '/run/netbox-sync',
            'NETBOX_SYNC_POSTGRES_VOLUME': 'netbox-sync-postgres-data',
        },
        'api.env': {
            **common, 'NETBOX_SYNC_REGISTRY_DSN': dsns['web_reader'],
            'NETBOX_SYNC_REGISTRATION_DSN': dsns['registration_writer'],
            'NETBOX_SYNC_BROKER_SOCKET': '/run/netbox-sync-broker/broker.sock',
            'NETBOX_SYNC_LIFECYCLE_SOCKET': '/run/netbox-sync-lifecycle/worker.sock',
            'NETBOX_SYNC_BOOTSTRAP_SOCKET': '/run/netbox-sync-bootstrap/worker.sock',
            'NETBOX_SYNC_DISCOVERY_SOCKET': '/run/netbox-sync-discovery/worker.sock',
            'NETBOX_SYNC_APPLY_SOCKET': '/run/netbox-sync-apply/worker.sock',
            'NETBOX_SYNC_SCHEDULE_SOCKET': '/run/netbox-sync-schedule/worker.sock',
            'NB_API_URL': '', 'NB_API_TOKEN_FILE': '',
            'NETBOX_SYNC_WRITE_HOSTS': '127.0.0.1:8000,localhost:8000',
        },
        'broker.env': {
            **common, 'NETBOX_SYNC_LIFECYCLE_WRITER_DSN': dsns['lifecycle_writer'],
            'NETBOX_SYNC_APPLY_LOCK_PATH': '/run/netbox-sync-lock/apply.lock',
        },
        'discovery.env': {
            **common, 'NETBOX_SYNC_DISCOVERY_REGISTRY_DSN': dsns['discovery_reader'],
            'NETBOX_SYNC_OPERATION_WRITER_DSN': dsns['operation_writer'],
            'NETBOX_SYNC_DISCOVERY_NB_API_URL': '',
            'NETBOX_SYNC_NETBOX_CONFIG_FILE': '/run/secrets/netbox/bootstrap.json',
        },
        'apply.env': {
            **common, 'NETBOX_SYNC_APPLY_REGISTRY_DSN': dsns['apply_registry_reader'],
            'NETBOX_SYNC_RUN_WRITER_DSN': dsns['run_writer'],
            'NETBOX_SYNC_APPLY_NB_API_URL': '',
            'NETBOX_SYNC_NETBOX_CONFIG_FILE': '/run/secrets/netbox/bootstrap.json',
        },
        'schedule.env': {
            **common, 'NETBOX_SYNC_SCHEDULE_WRITER_DSN': dsns['schedule_writer'],
        },
        'scheduler.env': {
            **common, 'SYNC_MODE': 'apply', 'SOURCE_CONFIG_MODE': 'registry-all',
            'APPLY_SCOPE': 'full', 'APPLY_CONFIRM': 'FULL_WRITE',
            'NETBOX_SYNC_REGISTRY_DSN': dsns['registry_reader'],
            'NETBOX_SYNC_RUN_WRITER_DSN': dsns['run_writer'],
            'NETBOX_SYNC_SOURCE_SECRET_DIR': '/run/secrets/netbox-sync-sources',
            'NETBOX_SYNC_NETBOX_CONFIG_FILE': '/run/secrets/netbox/bootstrap.json',
            'NB_API_URL': '', 'NB_APPLY_API_TOKEN_FILE': '/run/secrets/netbox/apply-token',
        },
    }


def generate_configuration(root, image, *, destination=None):
    """Generate role-separated env files from protected infrastructure secrets."""
    destination = destination or root / 'config'
    ensure_directory(destination, 0o700)
    values = _configuration_values(root, image)
    for name in CONFIG_NAMES:
        replacements = ({'NETBOX_SYNC_IMAGE': image,
                         'NETBOX_SYNC_CONFIG_DIR': str(destination)}
                        if name == 'compose.env' else {})
        payload = _merged_config(root / 'config' / name, values[name], replacements)
        _atomic_write(destination / name, payload)


def prepare_layout(root, source, release_id, image):
    """Stage a validated release and merged config without changing current."""
    for directory, mode in (
            (root, 0o755), (root / 'releases', 0o755), (root / 'config', 0o750),
            (root / 'secrets', 0o700), (root / 'secrets' / 'infrastructure', 0o700),
            (root / 'secrets' / 'sources', 0o700), (root / 'secrets' / 'netbox', 0o700),
            (root / 'backups', 0o700), (root / 'state', 0o750)):
        ensure_directory(directory, mode)
    release = install_release(source, root / 'releases', release_id)
    staging = Path(tempfile.mkdtemp(prefix=f'prepare-{release_id}-', dir=root / 'state'))
    config = staging / 'config'
    generate_configuration(root, image, destination=config)
    ensure_directory(Path('/run/netbox-sync') if root == Path('/opt/netbox-sync')
                     else root / 'run', 0o750)
    return PreparedDeployment(root, release, config, image)


def compose_command(root, *arguments, release=None, config=None, overrides=()):
    """Build one argv using Compose env-file semantics, never shell sourcing."""
    release = release or root / 'current'
    config = config or root / 'config'
    files = ['-f', str(release / 'compose.production.yml')]
    if ingress_mode_from_config(config / 'compose.env') == 'external':
        files.extend(('-f', str(release / 'compose.external-ingress.yml')))
    for override in overrides:
        files.extend(('-f', str(override)))
    return ['docker', 'compose', '--env-file', str(config / 'compose.env'),
            *files, *arguments]


def _wait_for_postgres(root, release, config):
    """Wait for the bundled database without exposing connection material."""
    for _attempt in range(60):
        status = run(compose_command(
            root, 'exec', '-T', 'postgres', 'pg_isready', '-U',
            'netbox_sync_bootstrap', '-d', 'netbox_sync', release=release, config=config),
                     check=False)
        if status.returncode == 0:
            return
        time.sleep(2)
    raise InstallError('bundled PostgreSQL did not become healthy')


def prepare_stack(prepared):
    """Validate/build/provision against staged artifacts before activation."""
    root, release, config = prepared.root, prepared.release, prepared.config
    run(compose_command(root, 'config', '--quiet', release=release, config=config))
    run(compose_command(root, 'build', 'netbox-sync-api', release=release, config=config))
    run(compose_command(root, 'up', '-d', 'postgres', release=release, config=config))
    _wait_for_postgres(root, release, config)
    for service in ('netbox-sync-db-roles', 'netbox-sync-migrate', 'netbox-sync-db-grants'):
        run(compose_command(root, '--profile', 'tools', 'run', '--rm', '--no-deps',
                            service, release=release, config=config))


def _runtime_services():
    return ('netbox-sync-proxy', 'netbox-sync-api', 'netbox-sync-secret-broker', 'netbox-sync-lifecycle-worker', 'netbox-sync-bootstrap-worker', 'netbox-sync-discovery-worker',
            'netbox-sync-apply-worker', 'netbox-sync-schedule-worker')


def start_runtime(prepared, *, overrides=()):
    """Start the prepared application and require every long-running service."""
    run(compose_command(prepared.root, '--profile', 'tools', 'run', '--rm', '--no-deps',
        'netbox-sync-http-init', release=prepared.release, config=prepared.root/'config', overrides=overrides))
    command = compose_command(prepared.root, 'up', '-d', *_runtime_services(),
                              release=prepared.release, config=prepared.root / 'config',
                              overrides=overrides)
    run(command)
    for _attempt in range(30):
        status = run(compose_command(
            prepared.root, 'ps', '--status', 'running', '--services',
            release=prepared.release, config=prepared.root / 'config',
            overrides=overrides),
                     check=False, capture_output=True)
        running = set(status.stdout.split()) if status.returncode == 0 else set()
        if set(_runtime_services()).issubset(running):
            health = run(compose_command(
                prepared.root, 'exec', '-T', 'netbox-sync-api', 'python', '-m', 'netbox_sync.web_runtime', 'health',
                release=prepared.release, config=prepared.root / 'config',
                overrides=overrides),
                         check=False)
            proxy = run(compose_command(prepared.root, 'exec', '-T', 'netbox-sync-proxy',
                'wget', '-q', '--spider', 'http://127.0.0.1:8081/health',
                release=prepared.release, config=prepared.root/'config', overrides=overrides),check=False)
            if health.returncode == 0 and proxy.returncode == 0:
                return
        time.sleep(2)
    raise InstallError('application services did not become ready')


def _config_snapshot(root):
    """Capture only the bounded canonical files for activation rollback."""
    result = {}
    for name in CONFIG_NAMES:
        path = root / 'config' / name
        result[name] = path.read_bytes() if path.exists() else None
    return result


def publish_configuration(prepared):
    """Publish staged config atomically per file after successful preparation."""
    snapshot = _config_snapshot(prepared.root)
    for name in CONFIG_NAMES:
        source = prepared.config / name
        if name == 'compose.env':
            payload = _merged_config(
                source, {}, {'NETBOX_SYNC_CONFIG_DIR': str(prepared.root / 'config')})
        else:
            payload = source.read_text(encoding='utf-8')
        _atomic_write(prepared.root / 'config' / name, payload)
    return snapshot


def restore_configuration(root, snapshot):
    """Restore the pre-activation canonical config without reconstructing values."""
    for name, payload in snapshot.items():
        path = root / 'config' / name
        if payload is None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        else:
            _atomic_write(path, payload.decode('utf-8'))


def restore_current(root, previous):
    """Restore the old current link, or remove a failed fresh activation."""
    current = root / 'current'
    if previous is None:
        try:
            current.unlink()
        except FileNotFoundError:
            pass
    else:
        activate_release(root, previous)


def quiesce_uncertain_runtime(prepared):
    """Best-effort stop of write entrypoints after a partial runtime activation."""
    run(compose_command(
        prepared.root, 'stop', 'netbox-sync-api', 'netbox-sync-apply-worker',
        'netbox-sync-schedule-worker', 'netbox-sync-lifecycle-worker', 'netbox-sync-bootstrap-worker', release=prepared.release,
        config=prepared.root / 'config'), check=False)


def _timer_active():
    return run(['systemctl', 'is-active', '--quiet', 'netbox-sync.timer'],
               check=False).returncode == 0


def stop_timer():
    """Stop new scheduled entries without killing an already active apply."""
    was_active = _timer_active()
    if was_active:
        run(['systemctl', 'stop', 'netbox-sync.timer'])
    return was_active


@contextlib.contextmanager
def shared_apply_lock(path, timeout_seconds=120):
    """Wait boundedly for the same inode used by scheduled and manual apply."""
    if os.name != 'posix':
        raise InstallError('safe activation lock requires a POSIX host')
    import fcntl  # pylint: disable=import-outside-toplevel,import-error
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags, 0o600)
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise InstallError(
                        'active synchronization did not release the shared lock') from None
                time.sleep(1)
        yield
    finally:
        os.close(descriptor)


def check_legacy_dropin(root):
    """Require explicit operator removal of the one known obsolete override."""
    if root != Path('/opt/netbox-sync'):
        return
    legacy = Path('/etc/systemd/system/infra-netbox-sync.timer.d/web8-fixed-tick.conf')
    if legacy.exists():
        raise InstallError('remove the known legacy WEB-8 timer drop-in before activation')


def activate_prepared(prepared, *, install_units, start_services):
    """Publish config/current once, rolling both back on bounded activation failure."""
    root = prepared.root
    previous = current_release(root)
    snapshot = _config_snapshot(root)
    switched = False
    runtime_attempted = False
    try:
        publish_configuration(prepared)
        activate_release(root, prepared.release)
        switched = True
        if install_units:
            install_systemd(root, start=False)
        if start_services:
            runtime_attempted = True
            start_runtime(prepared)
    except Exception:
        if runtime_attempted:
            try:
                quiesce_uncertain_runtime(prepared)
            except (OSError, subprocess.SubprocessError):
                pass
        if switched:
            restore_current(root, previous)
        restore_configuration(root, snapshot)
        raise


def _cleanup_prepared(prepared):
    try:
        shutil.rmtree(prepared.config.parent)
    except FileNotFoundError:
        pass


def install_systemd(root, *, start=True):
    """Install tracked units idempotently; never used by tests implicitly."""
    if root != Path('/opt/netbox-sync'):
        raise InstallError('systemd installation requires canonical /opt/netbox-sync root')
    unit_root = root / 'current' / 'deploy' / 'systemd'
    for name in ('netbox-sync.service', 'netbox-sync.timer'):
        destination = Path('/etc/systemd/system') / name
        shutil.copy2(unit_root / name, destination)
        destination.chmod(0o644)
    run(['systemctl', 'daemon-reload'])
    if start:
        run(['systemctl', 'enable', '--now', 'netbox-sync.timer'])


# Load the shared stdlib-only contract without importing the application's runtime
# dependencies on the Debian host. The path belongs to this reviewed release.
_tls = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'netbox_sync/tls_config.py'))
public_authority = _tls['public_authority']
TLSConfigurationError = _tls['TLSConfigurationError']


def ingress_mode_from_config(path):
    """Missing setting is the existing standalone contract; unknown values fail closed."""
    values = []
    if path.exists():
        values = [line.split('=', 1)[1] for line in path.read_text(encoding='utf-8').splitlines()
                  if line.startswith('NETBOX_SYNC_INGRESS_MODE=')]
    if len(values) > 1 or (values and values[0] not in ('standalone', 'external')):
        raise InstallError('invalid or duplicate ingress mode')
    return values[0] if values else 'standalone'


def resolve_ingress_mode(root, explicit=None):
    current = ingress_mode_from_config(root / 'config/compose.env')
    return explicit or current


def validate_ingress_prerequisites(mode):
    if mode != 'external':
        return
    result = run(['docker', 'compose', 'version', '--short'], capture_output=True)
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?', result.stdout.strip())
    if not match or tuple(map(int, match.groups())) < (2, 24, 4):
        raise InstallError('external ingress requires Docker Compose >=2.24.4')


def configure_ingress(prepared, mode):
    path = prepared.config / 'compose.env'
    values = {'NETBOX_SYNC_INGRESS_MODE': mode,
              'NETBOX_SYNC_INGRESS_DIR': str(prepared.root / 'ingress')}
    _atomic_write(path, _merged_config(path, values, values))


def initialize_ingress_directory(root):
    """Persistent parent survives reboot; socket itself is disposable, never backed up."""
    path = root / 'ingress'
    if path.is_symlink():
        raise InstallError('ingress directory must not be a symlink')
    if path.exists():
        info = path.stat()
        if not path.is_dir() or (os.name == 'posix' and
                (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (10001, 10001, 0o750)):
            raise InstallError('ingress directory ownership or permissions are invalid')
        return
    path.mkdir(mode=0o750)
    if os.name == 'posix':
        os.chown(path, 10001, 10001)
    path.chmod(0o750)


def validate_netbox_ca(root):
    ca = root / 'secrets/ca/netbox-ca.pem'
    if ca.exists() or ca.is_symlink():
        _tls['validate_ca'](_tls['protected_file'](ca, 0o644))


def initialize_tls_layout(root):
    for path, mode, gid in ((root,0o755,0),(root/'secrets',0o700,0),
                           (root/'secrets/tls',0o750,10001),(root/'secrets/ca',0o755,0)):
        if path.is_symlink():raise InstallError('TLS layout contains a symbolic link')
        if path.exists():
            info=path.stat()
            if not path.is_dir() or (os.name=='posix' and (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))!=(0,gid,mode)):
                raise InstallError('TLS layout ownership or permissions are invalid')
        else:
            path.mkdir(parents=True,mode=mode)
            if os.name=='posix':os.chown(path,0,gid)
            path.chmod(mode)


def resolve_public_url(root, explicit=None):
    path=root/'config/api.env'
    current=''
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.startswith('NETBOX_SYNC_PUBLIC_URL='):current=line.split('=',1)[1]
    if current and explicit and current!=explicit:
        raise InstallError('public URL change requires a separately reviewed transition')
    selected=explicit or current
    public_authority(selected)
    return selected


def validate_tls_material(root, public_url):
    host=public_authority(public_url)
    directory=root/'secrets/tls'
    for name in ('fullchain.pem','privkey.pem'):
        _tls['protected_file'](directory/name,0o640,10001)
    try:
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(directory/'fullchain.pem',directory/'privkey.pem',password=lambda: '')
        for args in (['-checkend','0'],['-checkhost',host]):
            result=subprocess.run(['openssl','x509','-in',str(directory/'fullchain.pem'),'-noout',*args],
                                  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
            if result.returncode:raise ValueError()
    except (ValueError,OSError,ssl.SSLError,subprocess.SubprocessError):
        raise InstallError('TLS certificate/key invalid, expired, encrypted or hostname mismatch') from None
    validate_netbox_ca(root)


def configure_tls(prepared, public_url):
    authority=public_authority(public_url)
    for name, defaults in {
        'compose.env': {'NETBOX_SYNC_TLS_DIR':str(prepared.root/'secrets/tls'),
                        'NETBOX_SYNC_CA_DIR':str(prepared.root/'secrets/ca'),
                        'NETBOX_SYNC_PUBLIC_HOST':authority},
        'api.env': {'NETBOX_SYNC_PUBLIC_URL':public_url,'NETBOX_SYNC_WRITE_HOSTS':authority},
    }.items():
        path=prepared.config/name
        # Explicitly reviewed HTTP -> HTTPS transition updates the old loopback allowlist.
        _atomic_write(path,_merged_config(path,defaults,{'NETBOX_SYNC_WRITE_HOSTS':authority} if name=='api.env' else defaults))

def parse_args(argv=None):
    """Parse bounded non-interactive installer options."""
    parser = argparse.ArgumentParser(description='Prepare a NetBox Sync v1 foundation')
    parser.add_argument('--ingress-mode', choices=('standalone', 'external'),
                        help='Explicit ingress mode; fresh default standalone, existing setting preserved')
    parser.add_argument('--public-url', help='Canonical https://FQDN, required for first HTTPS installation')
    parser.add_argument('--init-tls-layout', action='store_true', help='Create TLS/CA directories only; no certificates or deployment')
    parser.add_argument('--check-tls', action='store_true', help='Validate public URL and operator TLS/CA files only')
    parser.add_argument('--check', action='store_true', help='validate only; make no changes')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--no-start', action='store_true')
    parser.add_argument('--no-systemd', action='store_true')
    parser.add_argument('--root', type=Path, default=Path('/opt/netbox-sync'))
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--release-id')
    parser.add_argument('--image', help='immutable app image/tag; defaults to the release id')
    return parser.parse_args(argv)


def main(argv=None):
    """Validate or prepare a deployment foundation."""
    args = parse_args(argv)
    if not (args.check or args.init_tls_layout or args.check_tls) and not args.release_id:
        raise SystemExit('--release-id is required')
    if args.release_id is not None and not RELEASE_PATTERN.fullmatch(args.release_id):
        raise SystemExit('invalid release id')
    try:
        root=args.root.resolve()
        if args.init_tls_layout:
            initialize_tls_layout(root)
            print('TLS layout ready; operator certificates must be supplied separately')
            return 0
        mode = resolve_ingress_mode(root, args.ingress_mode)
        if args.check_tls:
            public_authority(resolve_public_url(root,args.public_url))
            if mode == 'standalone':
                validate_tls_material(root,resolve_public_url(root,args.public_url))
            else:
                validate_netbox_ca(root)
            print('Local TLS/CA preflight OK; external ingress certificate verification is operator-owned'
                  if mode == 'external' else 'TLS material and public URL OK')
            return 0
        validate_prerequisites(require_systemd=not args.no_systemd)
        validate_ingress_prerequisites(mode)
        if args.check:
            print('deployment prerequisites OK')
            return 0
        image = args.image or f'netbox-sync:{args.release_id}'
        root = args.root.resolve()
        public_url=resolve_public_url(root,args.public_url)
        initialize_tls_layout(root)
        if mode == 'standalone':
            validate_tls_material(root,public_url)
        else:
            validate_netbox_ca(root)
        prepared = prepare_layout(root, args.source.resolve(), args.release_id, image)
        configure_tls(prepared,public_url)
        configure_ingress(prepared,mode)
        if mode == 'external':
            initialize_ingress_directory(root)
        upgrading = current_release(root) is not None
        if upgrading and shutil.which('systemctl') is None:
            raise InstallError('systemctl is required to coordinate an existing installation')
        try:
            if upgrading:
                stop_timer()
            check_legacy_dropin(root)
            lock_path = (Path('/run/netbox-sync/apply.lock') if root == Path('/opt/netbox-sync')
                         else root / 'run/apply.lock')
            with shared_apply_lock(lock_path):
                prepare_stack(prepared)
                if not args.prepare_only:
                    activate_prepared(prepared, install_units=not args.no_systemd,
                                      start_services=not args.no_start)
                    if not args.no_systemd and not args.no_start:
                        run(['systemctl', 'enable', '--now', 'netbox-sync.timer'])
                else:
                    print(f'prepared release {args.release_id}; activation was not attempted')
        finally:
            _cleanup_prepared(prepared)
    except TLSConfigurationError as error:
        print(str(error),file=sys.stderr)
        return 1
    except (InstallError, OSError, subprocess.SubprocessError):
        print('deployment preparation failed; check TLS material/public URL, then inspect host prerequisites and protected config',
              file=sys.stderr)
        return 1
    print('NetBox Sync deployment foundation prepared')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
