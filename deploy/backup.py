#!/usr/bin/env python3
"""Supported NetBox Sync backup, inspection, verification and fresh restore tool."""

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from psycopg import pq
from psycopg.conninfo import conninfo_to_dict, make_conninfo

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import install
from netbox_sync.deployment import PASSWORD_FILES, RESTORE_BOOTSTRAP_FILE


FORMAT_VERSION = 1
ALEMBIC_CHAIN = (
    '0001_registry_baseline', '0002_sync_run_history', '0003_netbox_sync_naming',
    '0004_source_operations', '0005_source_tombstones')
ALEMBIC_HEAD = ALEMBIC_CHAIN[-1]
PRODUCT = 'NetBox Sync'
DATABASE_NAME = 'netbox_sync'
SCHEMA_NAME = 'netbox_sync'
LEGACY_PRODUCT = 'Infra Sync'
LEGACY_DATABASE_NAME = 'infra_sync'
LEGACY_SCHEMA_NAME = 'infra_sync'
CONFIG_FILES = install.CONFIG_NAMES
STATE_DIRS = ('config', 'secrets')
REQUIRED_SECRET_DIRS = ('infrastructure', 'sources', 'netbox')
BROKER_XATTR_SETS = (
    ('user.netbox_sync.operation', 'user.netbox_sync.receipt', 'user.netbox_sync.complete'),
    ('user.infra_sync.operation', 'user.infra_sync.receipt', 'user.infra_sync.complete'),
)
BROKER_XATTRS = tuple(attribute for group in BROKER_XATTR_SETS for attribute in group)
VALID_BROKER_XATTR_SETS = frozenset({
    frozenset(BROKER_XATTR_SETS[0]), frozenset(BROKER_XATTR_SETS[1]),
    frozenset(BROKER_XATTRS),
})
PAYLOAD_FILES = ('database.dump', 'state.tar', 'manifest.json')
FOUNDATION_TABLES = ('alembic_version', 'schema_meta', 'source_operations',
                     'source_tombstones', 'sources', 'sync_runs')
SAFE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
SAFE_SCHEMA = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,62}$')
MAINTENANCE_SERVICES = (
    'netbox-sync-api', 'netbox-sync-secret-broker', 'netbox-sync-discovery-worker',
    'netbox-sync-apply-worker', 'netbox-sync-schedule-worker')
HOST_LOCAL_COMPOSE_KEYS = (
    'NETBOX_SYNC_COMPOSE_PROJECT', 'NETBOX_SYNC_IMAGE', 'NETBOX_SYNC_CONFIG_DIR',
    'NETBOX_SYNC_INFRA_SECRET_DIR', 'NETBOX_SYNC_SOURCE_SECRET_DIR',
    'NETBOX_SYNC_NETBOX_SECRET_DIR', 'NETBOX_SYNC_APPLY_LOCK_DIR',
    'NETBOX_SYNC_POSTGRES_VOLUME', 'NETBOX_SYNC_WEB_PORT')


class BackupError(RuntimeError):
    """Sanitized operator-facing backup/restore failure."""


def _failure_code(command, error):
    """Map internal failures to a small secret-free operator taxonomy."""
    message = str(error)
    if 'active synchronization did not release' in message:
        return 'BACKUP_LOCKED' if command == 'create' else 'RESTORE_LOCKED'
    if command == 'restore':
        if 'target contains registry' in message or 'exact Foundation schema' in message:
            return 'RESTORE_TARGET_NOT_EMPTY'
        if 'newer or unsupported' in message or 'PostgreSQL major is older' in message:
            return 'RESTORE_INCOMPATIBLE'
        return 'RESTORE_INVALID'
    if command in ('verify', 'inspect'):
        return 'BACKUP_INVALID'
    return 'BACKUP_FAILED'


def _compose_command(root, *arguments, mode='bundled'):
    overrides = ((root / 'current/compose.external-postgres.yml',)
                 if mode == 'external' else ())
    return install.compose_command(root, *arguments, overrides=overrides)


def _utc_now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _application_version():
    try:
        return importlib.metadata.version('netbox-sync')
    except importlib.metadata.PackageNotFoundError:
        return 'unpackaged'


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _fsync_path(path):
    if os.name != 'posix':
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_text(path, text, mode=0o600):
    temporary = path.with_name(path.name + f'.tmp-{os.getpid()}')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        os.fchmod(descriptor, mode)
        os.write(descriptor, text.encode('utf-8'))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _safe_relative(value):
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in ('', '.', '..') for part in path.parts):
        raise BackupError('backup contains an unsafe path')
    return path


def _read_env(path):
    values = {}
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError as exc:
        raise BackupError('canonical compose configuration is unavailable') from exc
    for line in lines:
        if not line or line.lstrip().startswith('#'):
            continue
        key, separator, value = line.partition('=')
        if not separator or not key:
            raise BackupError('canonical compose configuration is invalid')
        values[key] = value
    return values


def _file_metadata(root):  # pylint: disable=too-many-locals,too-many-nested-blocks
    records = []
    for top in STATE_DIRS:
        base = root / top
        if base.is_symlink() or not base.is_dir():
            raise BackupError(f'required persistent directory is unavailable: {top}')
        for directory, names, filenames in os.walk(base, followlinks=False):
            current = Path(directory)
            current_info = current.stat(follow_symlinks=False)
            if (os.name == 'posix' and current.relative_to(root).parts[0] == 'secrets'
                    and stat.S_IMODE(current_info.st_mode) != 0o700):
                raise BackupError('secret directory permissions must be 0700')
            if (getattr(os, 'geteuid', lambda: -1)() == 0
                    and (current_info.st_uid, current_info.st_gid) != (0, 0)):
                raise BackupError('persistent state must be owned by root')
            names.sort()
            filenames.sort()
            for name in names:
                path = current / name
                if path.is_symlink() or not path.is_dir():
                    raise BackupError('persistent state contains a link or special directory')
            for name in filenames:
                path = current / name
                if path.is_symlink() or not path.is_file():
                    raise BackupError('persistent state contains a link or special file')
                relative = path.relative_to(root).as_posix()
                info = path.stat(follow_symlinks=False)
                mode = stat.S_IMODE(info.st_mode)
                if os.name == 'posix' and mode != 0o600:
                    raise BackupError('persistent config and secret files must be 0600')
                if (getattr(os, 'geteuid', lambda: -1)() == 0
                        and (info.st_uid, info.st_gid) != (0, 0)):
                    raise BackupError('persistent state must be owned by root')
                xattrs = {}
                if relative.startswith('secrets/sources/'):
                    try:
                        present = set(os.listxattr(path, follow_symlinks=False)).intersection(
                            BROKER_XATTRS)
                    except (AttributeError, OSError) as exc:
                        raise BackupError('source secret xattr contract is unavailable') from exc
                    if present and frozenset(present) not in VALID_BROKER_XATTR_SETS:
                        raise BackupError('broker source secret xattrs are incomplete')
                    for attribute in sorted(present):
                        try:
                            value = os.getxattr(path, attribute, follow_symlinks=False)
                        except (AttributeError, OSError) as exc:
                            raise BackupError(
                                'source secret xattr contract is unavailable') from exc
                        # The receipt authorizes broker rollback, so the manifest
                        # records only an integrity fingerprint.  The value itself
                        # remains solely inside the protected tar payload.
                        fingerprint = hashlib.sha256(value).hexdigest()
                        xattrs[attribute] = 'sha256:' + fingerprint
                records.append({
                    'path': relative, 'uid': info.st_uid, 'gid': info.st_gid,
                    'mode': f'{mode:04o}', 'size': info.st_size, 'xattrs': xattrs,
                })
    return records


def _validate_canonical_files(root):
    missing = [name for name in CONFIG_FILES if not (root / 'config' / name).is_file()]
    if missing:
        raise BackupError('canonical configuration is incomplete')
    if {path.name for path in (root / 'config').iterdir()} != set(CONFIG_FILES):
        raise BackupError('config directory contains non-canonical entries')
    secret_root = root / 'secrets'
    if ({path.name for path in secret_root.iterdir()} != set(REQUIRED_SECRET_DIRS)
            or any(not path.is_dir() for path in secret_root.iterdir())):
        raise BackupError('secret directory contains non-canonical entries')
    for directory in REQUIRED_SECRET_DIRS:
        path = root / 'secrets' / directory
        if path.is_symlink() or not path.is_dir():
            raise BackupError('canonical secret layout is incomplete')
    for filename in PASSWORD_FILES.values():
        path = root / 'secrets/infrastructure' / filename
        if path.is_symlink() or not path.is_file():
            raise BackupError('infrastructure password set is incomplete')


def _active_release(root):
    try:
        release = install.current_release(root)
    except install.InstallError as exc:
        raise BackupError('active release is invalid') from exc
    if release is None:
        raise BackupError('active release is unavailable')
    return release.name


class DatabaseTool:
    """Run standard PostgreSQL client tools without credentials in argv."""

    def __init__(self, root, mode='bundled', environ=None):
        self.root = root
        self.mode = mode
        self.environ = dict(environ or os.environ)
        if mode not in ('bundled', 'external'):
            raise BackupError('unsupported PostgreSQL mode')
        if mode == 'external' and not self.environ.get('NETBOX_SYNC_BACKUP_DSN', '').strip():
            raise BackupError('external PostgreSQL backup DSN is not configured')

    def _command(self, executable, *arguments):
        if self.mode == 'bundled':
            return _compose_command(
                self.root, 'exec', '-T', 'postgres', executable, *arguments,
                mode=self.mode)
        resolved = shutil.which(executable)
        if resolved is None:
            raise BackupError(f'required PostgreSQL client is missing: {executable}')
        return [resolved, *arguments]

    def _environment(self):
        environment = self.environ.copy()
        if self.mode == 'external':
            dsn = environment.pop('NETBOX_SYNC_BACKUP_DSN')
            try:
                settings = conninfo_to_dict(dsn)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                raise BackupError('external PostgreSQL backup DSN is invalid') from exc
            options = {
                option.keyword.decode(): option.envvar.decode()
                for option in pq.Conninfo.get_defaults() if option.envvar
            }
            for key, value in settings.items():
                env_name = options.get(key)
                if env_name:
                    environment[env_name] = value
        return environment

    def _connection_arguments(self):
        return (() if self.mode == 'external' else
                ('--username', 'netbox_sync_bootstrap', '--dbname', DATABASE_NAME))

    def _restore_connection_arguments(self):
        if self.mode != 'external':
            return '--username', 'netbox_sync_bootstrap', '--dbname', DATABASE_NAME
        try:
            database = conninfo_to_dict(self.environ['NETBOX_SYNC_BACKUP_DSN']).get('dbname')
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise BackupError('external PostgreSQL backup DSN is invalid') from exc
        if not database:
            raise BackupError('external PostgreSQL backup database is unavailable')
        return '--dbname', database

    def _run(  # pylint: disable=too-many-arguments
            self, executable, arguments, *, input_file=None, output_file=None, text=False):
        input_stream = input_file.open('rb') if input_file else None
        output_stream = output_file.open('wb') if output_file else None
        try:
            result = subprocess.run(  # noqa: S603
                self._command(executable, *arguments),
                stdin=input_stream or subprocess.DEVNULL,
                stdout=output_stream or subprocess.PIPE,
                stderr=subprocess.PIPE, text=text, env=self._environment(), check=False)
        finally:
            if input_stream:
                input_stream.close()
            if output_stream:
                output_stream.close()
        if result.returncode:
            raise BackupError(f'{executable} failed; inspect PostgreSQL availability')
        return result.stdout

    def query(self, sql_text):
        """Return non-empty scalar/record lines from a fixed read-only query."""
        output = self._run('psql', (
            '--no-psqlrc', '--tuples-only', '--no-align', '--quiet',
            *self._connection_arguments(),
            '--command', sql_text), text=True)
        return [line.strip() for line in output.splitlines() if line.strip()]

    def metadata(self):
        """Read version and count metadata included in the safe manifest."""
        values = self.query(
            "SELECT current_setting('server_version_num'), "
            f"COALESCE((SELECT version_num FROM {SCHEMA_NAME}.alembic_version LIMIT 1), ''), "
            f"(SELECT count(*) FROM {SCHEMA_NAME}.sources), "
            f"(SELECT count(*) FROM {SCHEMA_NAME}.sync_runs)")
        if len(values) != 1 or len(values[0].split('|')) != 4:
            raise BackupError('database metadata is unavailable')
        version, revision, sources, runs = values[0].split('|')
        return {
            'postgres_major': int(version) // 10000,
            'alembic_revision': revision,
            'source_count': int(sources), 'run_count': int(runs),
        }

    def source_secret_references(self):
        """Read logical credential references without resolving secret values."""
        tombstones = self.query(f"SELECT to_regclass('{SCHEMA_NAME}.source_tombstones') IS NOT NULL") == ['t']
        active = (f'WHERE NOT EXISTS (SELECT 1 FROM {SCHEMA_NAME}.source_tombstones t '
                  'WHERE t.source_instance=sources.source_instance) ' if tombstones else '')
        rows = self.query(
            'SELECT source_instance, token_id_provider, token_id_key, '
            f'token_secret_provider, token_secret_key FROM {SCHEMA_NAME}.sources '
            + active + 'ORDER BY source_instance')
        references = []
        for row in rows:
            values = row.split('|')
            if len(values) != 5:
                raise BackupError('source secret reference metadata is invalid')
            references.append(dict(zip((
                'source_instance', 'token_id_provider', 'token_id_key',
                'token_secret_provider', 'token_secret_key'), values)))
        return references

    def dump(self, destination):
        """Write one standard PostgreSQL custom-format dump."""
        connection = (() if self.mode == 'external' else
                      ('--username', 'netbox_sync_owner', '--dbname', DATABASE_NAME))
        self._run('pg_dump', (
            '--format=custom', '--no-owner', '--no-acl', f'--schema={SCHEMA_NAME}',
            *connection),
            output_file=destination)

    def verify_dump(self, dump):
        """Require pg_restore to list the custom-format dump."""
        self._run('pg_restore', ('--list',), input_file=dump)

    def target_counts(self):
        """Return registry/history counts, treating absent Foundation tables as empty."""
        values = self.query(
            f"SELECT CASE WHEN to_regclass('{SCHEMA_NAME}.sources') IS NULL THEN 0 "
            f"ELSE (SELECT count(*) FROM {SCHEMA_NAME}.sources) END, "
            f"CASE WHEN to_regclass('{SCHEMA_NAME}.sync_runs') IS NULL THEN 0 "
            f"ELSE (SELECT count(*) FROM {SCHEMA_NAME}.sync_runs) END")
        if len(values) != 1:
            raise BackupError('restore target state is unavailable')
        sources, runs = values[0].split('|')
        return int(sources), int(runs)

    def validate_empty_target(self):
        """Refuse replacement of any retained registry, history or lifecycle state."""
        if self.target_counts() != (0, 0):
            raise BackupError('fresh restore target contains registry or run-history rows')
        values = self.query(
            f'SELECT (SELECT count(*) FROM {SCHEMA_NAME}.source_operations), '
            f'(SELECT count(*) FROM {SCHEMA_NAME}.source_tombstones)')
        if values != ['0|0']:
            raise BackupError('fresh restore target contains operation or tombstone rows')

    def validate_foundation_target(self):
        """Reject unknown schemas even when their application tables are empty."""
        values = self.query(
            "SELECT COALESCE(string_agg(tablename, ',' ORDER BY tablename), '') "
            f"FROM pg_tables WHERE schemaname='{SCHEMA_NAME}'")
        if values != [','.join(FOUNDATION_TABLES)]:
            raise BackupError('fresh restore target is not an exact Foundation schema')

    def reconcile_operations(self):
        """Restored process/confirmation state cannot authorize resumption or apply."""
        self.query(f"UPDATE {SCHEMA_NAME}.source_operations SET "
                   "status=CASE WHEN operation_kind='PLAN' AND status='READY' THEN 'STALE' ELSE 'FAILED' END, "
                   "safe_error_code='OPERATION_INTERRUPTED', result=NULL, "
                   "updated_at=clock_timestamp(), finished_at=clock_timestamp() "
                   "WHERE status IN ('RUNNING','READY')")

    def postgres_major(self):
        """Return the connected server major version."""
        values = self.query("SELECT current_setting('server_version_num')")
        if len(values) != 1:
            raise BackupError('PostgreSQL version is unavailable')
        return int(values[0]) // 10000

    def restore(self, dump):
        """Replace Foundation-only schema objects from the verified dump."""
        connection = self._restore_connection_arguments()
        self._run('pg_restore', (
            '--exit-on-error', '--clean', '--if-exists', '--no-owner', '--no-acl',
            '--role=netbox_sync_owner', *connection), input_file=dump)

    def restore_fresh(self, dump, maintenance, source_schema=SCHEMA_NAME):
        """Replace only an exact, empty Foundation target under maintenance."""
        if not maintenance.authorizes_fresh_restore(self.root, self.mode):
            raise BackupError('fresh restore maintenance boundary is unavailable')
        self.validate_foundation_target()
        self.validate_empty_target()
        # Older reviewed dumps cannot name objects introduced by newer revisions.
        # Delete only the exact, prevalidated Foundation allowlist; never CASCADE.
        cleanup = '; '.join(
            f'DROP TABLE IF EXISTS {SCHEMA_NAME}.{name}'
            for name in reversed(FOUNDATION_TABLES)
        ) + f'; DROP FUNCTION IF EXISTS {SCHEMA_NAME}.guard_source_credential_refs(); DROP SCHEMA {SCHEMA_NAME}'
        self._run('psql', (
            '--no-psqlrc', '--quiet', *self._connection_arguments(),
            '--command', cleanup))
        connection = self._restore_connection_arguments()
        self._run('pg_restore', (
            '--exit-on-error', '--no-owner', '--no-acl',
            '--role=netbox_sync_owner', *connection), input_file=dump)
        if source_schema == LEGACY_SCHEMA_NAME:
            self._run('psql', (
                '--no-psqlrc', '--quiet', *self._connection_arguments(), '--command',
                f'ALTER SCHEMA {LEGACY_SCHEMA_NAME} RENAME TO {SCHEMA_NAME}'))
        elif source_schema != SCHEMA_NAME:
            raise BackupError('backup schema metadata is unsupported')


def _tar_create(root, destination):
    command = [
        'tar', '--create', '--format=pax', '--xattrs',
        '--xattrs-include=user.netbox_sync.*', '--xattrs-include=user.infra_sync.*',
        '--numeric-owner',
        '--file', str(destination), '--directory', str(root), *STATE_DIRS,
    ]
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            check=False)  # noqa: S603
    if result.returncode:
        raise BackupError('persistent state archive failed')
    destination.chmod(0o600)


def _require_gnu_tar():
    result = subprocess.run(['tar', '--version'], capture_output=True, text=True,
                            check=False)  # noqa: S603
    if result.returncode or 'GNU tar' not in result.stdout:
        raise BackupError('GNU tar with xattr support is required')


def _tar_members(archive):
    try:
        with tarfile.open(archive, 'r:*') as bundle:
            members = bundle.getmembers()
    except (OSError, tarfile.TarError) as exc:
        raise BackupError('persistent state archive is unreadable') from exc
    for member in members:
        relative = _safe_relative(member.name.rstrip('/'))
        if relative.parts[0] not in STATE_DIRS or member.issym() or member.islnk():
            raise BackupError('persistent state archive contains an unsupported entry')
        if not (member.isdir() or member.isfile()):
            raise BackupError('persistent state archive contains a special file')
    return members


def _tar_extract(archive, destination):
    _tar_members(archive)
    result = subprocess.run([
        'tar', '--extract', '--xattrs', '--xattrs-include=user.netbox_sync.*',
        '--xattrs-include=user.infra_sync.*',
        '--numeric-owner', '--same-owner', '--same-permissions', '--file', str(archive),
        '--directory', str(destination),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)  # noqa: S603
    if result.returncode:
        raise BackupError('persistent state archive restore failed')


def _write_checksums(directory):
    lines = [f'{_sha256(directory / name)}  {name}\n' for name in PAYLOAD_FILES]
    _atomic_text(directory / 'checksums.sha256', ''.join(lines))


def _load_manifest(bundle):
    try:
        payload = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError('backup manifest is unreadable') from exc
    required = {
        'backup_format_version', 'created_at', 'product', 'application_version',
        'release_id', 'active_release_id', 'compose_project', 'postgres_major',
        'postgres_mode', 'database_name', 'schema_name', 'alembic_revision',
        'source_count', 'run_count', 'secret_file_count', 'config_files',
        'files', 'source_secret_references', 'checksum_algorithm',
    }
    if set(payload) != required or payload['backup_format_version'] != FORMAT_VERSION:
        raise BackupError('backup format is unsupported')
    if payload['checksum_algorithm'] != 'SHA-256':
        raise BackupError('backup checksum algorithm is unsupported')
    identity = (payload['product'], payload['database_name'], payload['schema_name'])
    if identity not in {
            (PRODUCT, DATABASE_NAME, SCHEMA_NAME),
            (LEGACY_PRODUCT, LEGACY_DATABASE_NAME, LEGACY_SCHEMA_NAME)}:
        raise BackupError('backup product or database identity is unsupported')
    if not SAFE_SCHEMA.fullmatch(payload['schema_name']):
        raise BackupError('backup schema metadata is invalid')
    if not isinstance(payload['files'], list):
        raise BackupError('backup file metadata is invalid')
    for record in payload['files']:
        if set(record) != {'path', 'uid', 'gid', 'mode', 'size', 'xattrs'}:
            raise BackupError('backup file metadata is invalid')
        _safe_relative(record['path'])
        if (not isinstance(record['uid'], int) or not isinstance(record['gid'], int)
                or not isinstance(record['size'], int)
                or not re.fullmatch(r'0[0-7]{3}', record['mode'])
                or not isinstance(record['xattrs'], dict)):
            raise BackupError('backup file metadata is invalid')
        recorded_xattrs = frozenset(record['xattrs'])
        if (not recorded_xattrs.issubset(BROKER_XATTRS)
                or recorded_xattrs not in VALID_BROKER_XATTR_SETS | {frozenset()}):
            raise BackupError('backup xattr metadata is invalid')
        if not all(re.fullmatch(r'sha256:[a-f0-9]{64}', item)
                   for item in record['xattrs'].values()):
            raise BackupError('backup xattr metadata is invalid')
    for reference in payload['source_secret_references']:
        if set(reference) != {
                'source_instance', 'token_id_provider', 'token_id_key',
                'token_secret_provider', 'token_secret_key'}:
            raise BackupError('backup source reference metadata is invalid')
    return payload


def verify_bundle(bundle, database=None, require_complete=True):
    """Validate an entire bundle before any restore mutation."""
    bundle = bundle.resolve()
    manifest = _load_manifest(bundle)
    if (require_complete and ((bundle / 'COMPLETE').is_symlink()
                              or not (bundle / 'COMPLETE').is_file())):
        raise BackupError('backup is incomplete')
    try:
        lines = (bundle / 'checksums.sha256').read_text(encoding='ascii').splitlines()
    except OSError as exc:
        raise BackupError('backup checksums are unavailable') from exc
    expected = {}
    for line in lines:
        digest, separator, name = line.partition('  ')
        if not separator or name not in PAYLOAD_FILES or not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise BackupError('backup checksum file is invalid')
        if name in expected:
            raise BackupError('backup checksum file contains duplicate entries')
        expected[name] = digest
    if set(expected) != set(PAYLOAD_FILES) or len(lines) != len(PAYLOAD_FILES):
        raise BackupError('backup checksum file is incomplete')
    for name, digest in expected.items():
        path = bundle / name
        if path.is_symlink() or not path.is_file() or _sha256(path) != digest:
            raise BackupError('backup integrity verification failed')
    members = _tar_members(bundle / 'state.tar')
    archived = {record['path'] for record in manifest['files']}
    archived_payload = {member.name.rstrip('/') for member in members if member.isfile()}
    if archived_payload != archived:
        raise BackupError('backup archive and manifest file sets differ')
    config_sets = [{f'config/{name}' for name in CONFIG_FILES}]
    if manifest['alembic_revision'] in ALEMBIC_CHAIN[:3]:
        config_sets.append({f'config/{name}' for name in CONFIG_FILES if name != 'broker.env'})
    if set(manifest['config_files']) not in config_sets:
        raise BackupError('backup canonical configuration list is invalid')
    if not set(manifest['config_files']).issubset(archived):
        raise BackupError('backup canonical configuration is incomplete')
    records = {record['path']: record for record in manifest['files']}
    for member in members:
        if not member.isfile():
            continue
        actual = {}
        for attribute in BROKER_XATTRS:
            value = member.pax_headers.get('SCHILY.xattr.' + attribute)
            if value is not None:
                actual[attribute] = 'sha256:' + hashlib.sha256(
                    value.encode('utf-8')).hexdigest()
        if actual != records[member.name.rstrip('/')]['xattrs']:
            raise BackupError('backup archive xattrs differ from manifest')
    for reference in manifest['source_secret_references']:
        for provider, key in (
                (reference['token_id_provider'], reference['token_id_key']),
                (reference['token_secret_provider'], reference['token_secret_key'])):
            if provider == 'file':
                if not SAFE_NAME.fullmatch(key) or f'secrets/sources/{key}' not in archived:
                    raise BackupError('backup source secret reference is unresolved')
    if database:
        database.verify_dump(bundle / 'database.dump')
    return manifest


@dataclass
class Maintenance:
    """Short v1 maintenance window with exact prior-state restoration for backup."""

    root: Path
    restore_after: bool
    no_systemd: bool = False
    postgres_mode: str = 'bundled'

    def __post_init__(self):
        self.timer_active = False
        self.timer_stopped = False
        self.running = ()
        self.release = self.root / 'current'
        self.lock = None
        self.lock_entered = False
        self.writers_stopped = False

    def __enter__(self):
        if not self.no_systemd and self.root == Path('/opt/netbox-sync'):
            legacy_timer = install.run(
                ['systemctl', 'is-active', '--quiet', 'infra-netbox-sync.timer'],
                check=False)
            legacy_containers = install.run([
                'docker', 'ps', '--quiet', '--filter',
                'label=com.docker.compose.project=infra-sync'],
                check=False, capture_output=True)
            if legacy_timer.returncode == 0 or legacy_containers.stdout.strip():
                raise BackupError('legacy runtime must be stopped before maintenance')
        if not self.no_systemd:
            self.timer_active = install.stop_timer()
        self.timer_stopped = True
        lock = self.root / 'run/apply.lock' if self.root != Path('/opt/netbox-sync') \
            else Path('/run/netbox-sync/apply.lock')
        self.lock = install.shared_apply_lock(lock)
        try:
            self.lock.__enter__()
            self.lock_entered = True
            result = install.run(_compose_command(
                self.root, 'ps', '--status', 'running', '--services',
                mode=self.postgres_mode), capture_output=True)
            self.running = tuple(service for service in result.stdout.split()
                                 if service in MAINTENANCE_SERVICES)
            install.run(_compose_command(
                self.root, 'stop', *MAINTENANCE_SERVICES, mode=self.postgres_mode))
            self.writers_stopped = True
        except Exception:
            if self.lock_entered:
                self.lock.__exit__(*sys.exc_info())
            if self.restore_after and self.timer_active and not self.no_systemd:
                install.run(['systemctl', 'start', 'netbox-sync.timer'], check=False)
            raise
        return self

    def authorizes_fresh_restore(self, root, postgres_mode):
        """Prove destructive fresh-target work is inside this maintenance window."""
        return (
            not self.restore_after
            and self.timer_stopped
            and self.lock_entered
            and self.writers_stopped
            and self.root.resolve() == Path(root).resolve()
            and self.postgres_mode == postgres_mode
        )

    def __exit__(self, kind, value, traceback):
        try:
            if self.restore_after:
                if self.running:
                    install.run(_compose_command(
                        self.root, 'up', '-d', *self.running, mode=self.postgres_mode),
                        check=True)
                if self.timer_active and not self.no_systemd:
                    install.run(['systemctl', 'start', 'netbox-sync.timer'])
        finally:
            if self.lock_entered:
                self.lock.__exit__(kind, value, traceback)
            self.writers_stopped = False
            self.lock_entered = False
        return False


def create_backup(  # pylint: disable=too-many-arguments
        root, output, database, *, release_id=None, no_systemd=False, now=None):
    """Create, verify and atomically publish one standard backup directory."""
    root, output = root.resolve(), output.resolve()
    _require_gnu_tar()
    _validate_canonical_files(root)
    if output == root / 'config' or output == root / 'secrets' \
            or root / 'config' in output.parents or root / 'secrets' in output.parents:
        raise BackupError('backup output cannot be inside persistent input state')
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.chmod(0o700)
    created_at = now or _utc_now()
    timestamp = created_at.strftime('%Y%m%d-%H%M%S')
    name = f'netbox-sync-backup-{timestamp}'
    final = output / name
    if final.exists():
        raise BackupError('backup destination already exists')
    staging = Path(tempfile.mkdtemp(prefix=f'.{name}.tmp-', dir=output))
    staging.chmod(0o700)
    try:
        with Maintenance(root, restore_after=True, no_systemd=no_systemd,
                         postgres_mode=database.mode):
            metadata = database.metadata()
            database.dump(staging / 'database.dump')
            (staging / 'database.dump').chmod(0o600)
            _fsync_path(staging / 'database.dump')
            files = _file_metadata(root)
            _tar_create(root, staging / 'state.tar')
            _fsync_path(staging / 'state.tar')
            compose = _read_env(root / 'config/compose.env')
            active = _active_release(root)
            manifest = {
                'backup_format_version': FORMAT_VERSION,
                'created_at': created_at.isoformat().replace('+00:00', 'Z'),
                'product': PRODUCT, 'application_version': _application_version(),
                'release_id': release_id or active, 'active_release_id': active,
                'compose_project': compose.get('NETBOX_SYNC_COMPOSE_PROJECT', 'netbox-sync'),
                'postgres_major': metadata['postgres_major'],
                'postgres_mode': database.mode, 'database_name': DATABASE_NAME,
                'schema_name': SCHEMA_NAME,
                'alembic_revision': metadata['alembic_revision'],
                'source_count': metadata['source_count'], 'run_count': metadata['run_count'],
                'secret_file_count': sum(item['path'].startswith('secrets/') for item in files),
                'config_files': [f'config/{name}' for name in CONFIG_FILES],
                'files': files,
                'source_secret_references': database.source_secret_references(),
                'checksum_algorithm': 'SHA-256',
            }
            _atomic_text(staging / 'manifest.json', json.dumps(
                manifest, sort_keys=True, indent=2) + '\n')
            _write_checksums(staging)
            verify_bundle(staging, database, require_complete=False)
            _atomic_text(staging / 'COMPLETE', 'verified\n')
            os.replace(staging, final)
            if os.name == 'posix':
                _fsync_path(output)
        return final
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _compatible(manifest, target_major):
    revision = manifest['alembic_revision']
    if revision not in ALEMBIC_CHAIN:
        raise BackupError('backup database revision is newer or unsupported')
    if target_major < manifest['postgres_major']:
        raise BackupError('target PostgreSQL major is older than the backup source')


def _validate_restored_files(stage, manifest):
    actual = _file_metadata(stage)
    expected = {item['path']: item for item in manifest['files']}
    found = {item['path']: item for item in actual}
    if set(found) != set(expected):
        raise BackupError('restored persistent file set differs from manifest')
    for path, record in expected.items():
        item = found[path]
        if (item['uid'], item['gid'], item['mode'], item['xattrs']) != (
                record['uid'], record['gid'], record['mode'], record['xattrs']):
            raise BackupError('restored persistent file metadata differs from manifest')


def _extend_ui6_restored_configuration(stage):
    """Extend only older staged bundles, preserving all existing config bytes."""
    config = stage / 'config'
    discovery = _read_env(config / 'discovery.env')
    needs_operations = 'NETBOX_SYNC_OPERATION_WRITER_DSN' not in discovery
    needs_broker = not (config / 'broker.env').exists()
    # Current bundles already contain the capability files; leave their env untouched.
    if not needs_broker:
        return
    template = discovery.get('NETBOX_SYNC_DISCOVERY_REGISTRY_DSN', '')
    if not template:
        raise BackupError('older bundle lacks a reviewed discovery database configuration')
    schema = discovery.get('NETBOX_SYNC_REGISTRY_SCHEMA')
    if schema != SCHEMA_NAME:
        raise BackupError('restored lifecycle schema is unsupported')
    dsns = {}
    for role in ('operation_writer','lifecycle_writer'):
        password = install.ensure_secret(stage / 'secrets/infrastructure' / PASSWORD_FILES[role])
        dsns[role] = make_conninfo(template, user='netbox_sync_' + role, password=password)
    if needs_operations:
        defaults = {'NETBOX_SYNC_OPERATION_WRITER_DSN': dsns['operation_writer']}
        install._atomic_write(config / 'discovery.env', install._merged_config(config / 'discovery.env', defaults))
    install.write_config(config / 'broker.env', {
        'NETBOX_SYNC_REGISTRY_SCHEMA': schema,
        'NETBOX_SYNC_LIFECYCLE_WRITER_DSN': dsns['lifecycle_writer'],
        'NETBOX_SYNC_APPLY_LOCK_PATH': '/run/netbox-sync-lock/apply.lock',
    })


def _prepare_password_transition(root, restored):
    directory = Path(tempfile.mkdtemp(prefix='restore-passwords-', dir=root / 'state'))
    directory.chmod(0o700)
    current = root / 'secrets/infrastructure'
    incoming = restored / 'secrets/infrastructure'
    for key, filename in PASSWORD_FILES.items():
        source = current / filename if key == 'bootstrap' else incoming / filename
        if source.is_symlink() or not source.is_file():
            raise BackupError('required database role password file is unavailable')
        shutil.copyfile(source, directory / filename)
        (directory / filename).chmod(0o600)
    shutil.copyfile(incoming / PASSWORD_FILES['bootstrap'], directory / RESTORE_BOOTSTRAP_FILE)
    (directory / RESTORE_BOOTSTRAP_FILE).chmod(0o600)
    return directory


def _run_deployment_tool(root, service, environ=None, *, postgres_mode='bundled'):
    result = subprocess.run(  # noqa: S603
        _compose_command(root, '--profile', 'tools', 'run', '--rm', '--no-deps', service,
                         mode=postgres_mode),
        env=environ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if result.returncode:
        raise BackupError(f'database provisioning stage failed: {service}')


def _publish_restored_state(root, restored):
    rollback = Path(tempfile.mkdtemp(prefix='restore-rollback-', dir=root / 'state'))
    published = []
    try:
        for name in STATE_DIRS:
            current = root / name
            old = rollback / name
            os.replace(current, old)
            try:
                os.replace(restored / name, current)
            except Exception:
                os.replace(old, current)
                raise
            published.append(name)
    except Exception:
        for name in reversed(published):
            current, old = root / name, rollback / name
            failed = restored / name
            os.replace(current, failed)
            os.replace(old, current)
        raise
    shutil.rmtree(rollback)


def _preserve_host_local_config(root, restored):
    """Keep the new host's deployment identity while restoring portable config."""
    current = _read_env(root / 'config/compose.env')
    values = {key: current[key] for key in HOST_LOCAL_COMPOSE_KEYS if key in current}
    incoming = restored / 'config/compose.env'
    payload = install._merged_config(incoming, values, values)  # pylint: disable=protected-access
    install._atomic_write(incoming, payload)  # pylint: disable=protected-access


def _start_restored_runtime(root, postgres_mode):
    """Start ordinary services, prove liveness/diagnostics, never enable the timer."""
    prepared = install.PreparedDeployment(
        root=root, release=root / 'current', config=root / 'config', image='restored')
    try:
        overrides = ((root / 'current/compose.external-postgres.yml',)
                     if postgres_mode == 'external' else ())
        install.start_runtime(prepared, overrides=overrides)
        result = install.run(_compose_command(
            root, 'exec', '-T', 'netbox-sync-api', 'python', '-c',
            "import urllib.request; urllib.request.urlopen("
            "'http://127.0.0.1:8000/api/v1/diagnostics', timeout=5).close()",
            mode=postgres_mode), check=False)
        if result.returncode:
            raise BackupError('post-restore diagnostics did not become ready')
    except Exception:
        install.run(_compose_command(
            root, 'stop', *MAINTENANCE_SERVICES, mode=postgres_mode), check=False)
        raise


def restore_fresh(root, bundle, database, *, no_systemd=False, check_only=False):
    """Verify or restore a bundle into a Foundation-only empty destination."""
    root, bundle = root.resolve(), bundle.resolve()
    manifest = verify_bundle(bundle, database)
    _require_gnu_tar()
    _compatible(manifest, database.postgres_major())
    _validate_canonical_files(root)
    database.validate_foundation_target()
    if check_only:
        database.validate_empty_target()
        return manifest
    stage = Path(tempfile.mkdtemp(prefix='restore-state-', dir=root / 'state'))
    stage.chmod(0o700)
    with Maintenance(root, restore_after=False, no_systemd=no_systemd,
                     postgres_mode=database.mode) as maintenance:
        database.validate_foundation_target()
        database.validate_empty_target()
        _tar_extract(bundle / 'state.tar', stage)
        _validate_restored_files(stage, manifest)
        if manifest['product'] == LEGACY_PRODUCT:
            install.migrate_legacy_environment(stage, apply=True)
        # Older bundles do not contain the new role secrets or broker env file.
        # Extend only the staged restored state, after its exact metadata was verified.
        _extend_ui6_restored_configuration(stage)
        database.restore_fresh(
            bundle / 'database.dump', maintenance, manifest['schema_name'])
        _run_deployment_tool(root, 'netbox-sync-migrate', postgres_mode=database.mode)
        _run_deployment_tool(root, 'netbox-sync-db-grants', postgres_mode=database.mode)
        database.reconcile_operations()
        restored = database.metadata()
        if (restored['source_count'], restored['run_count']) != (
                manifest['source_count'], manifest['run_count']):
            raise BackupError('restored database counts differ from manifest')
        if restored['alembic_revision'] != ALEMBIC_HEAD:
            raise BackupError('restored database did not reach the target migration head')
        if database.source_secret_references() != manifest['source_secret_references']:
            raise BackupError('restored source secret references differ from manifest')
        transition = _prepare_password_transition(root, stage)
        try:
            environment = os.environ.copy()
            environment['NETBOX_SYNC_RESTORE_PASSWORD_DIR'] = str(transition)
            _run_deployment_tool(root, 'netbox-sync-db-restore-roles', environment,
                                 postgres_mode=database.mode)
        finally:
            shutil.rmtree(transition, ignore_errors=True)
        _preserve_host_local_config(root, stage)
        _publish_restored_state(root, stage)
        _start_restored_runtime(root, database.mode)
    shutil.rmtree(stage, ignore_errors=True)
    return manifest


def inspect_bundle(bundle, database=None):
    """Return a deliberately secret-free summary of a verified bundle."""
    manifest = verify_bundle(bundle, database)
    size = sum(path.stat().st_size for path in bundle.iterdir() if path.is_file())
    return {
        'created_at': manifest['created_at'],
        'application_version': manifest['application_version'],
        'release_id': manifest['release_id'], 'source_count': manifest['source_count'],
        'run_count': manifest['run_count'], 'postgres_major': manifest['postgres_major'],
        'alembic_revision': manifest['alembic_revision'], 'size_bytes': size,
        'checksum_status': 'valid',
    }


def parse_args(argv=None):
    """Parse bounded backup/restore operator commands."""
    parser = argparse.ArgumentParser(description='NetBox Sync backup and fresh restore')
    parser.add_argument('--root', type=Path, default=Path('/opt/netbox-sync'))
    parser.add_argument('--postgres-mode', choices=('bundled', 'external'), default='bundled')
    parser.add_argument('--no-systemd', action='store_true', help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create')
    create.add_argument('--output', type=Path)
    verify = commands.add_parser('verify')
    verify.add_argument('bundle', type=Path)
    inspect = commands.add_parser('inspect')
    inspect.add_argument('bundle', type=Path)
    listing = commands.add_parser('list')
    listing.add_argument('--directory', type=Path)
    restore = commands.add_parser('restore')
    restore.add_argument('bundle', type=Path)
    restore.add_argument('--check', action='store_true')
    return parser.parse_args(argv)


def main(argv=None):
    """Run one sanitized operator command and return a stable process status."""
    args = parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == 'list':
            directory = (args.directory or root / 'backups').resolve()
            bundles = set(directory.glob('netbox-sync-backup-*'))
            bundles.update(directory.glob('infra-sync-backup-*'))
            for bundle in sorted(bundles):
                try:
                    summary = inspect_bundle(bundle)
                    print(json.dumps({'bundle': bundle.name, **summary}, sort_keys=True))
                except BackupError:
                    print(json.dumps({'bundle': bundle.name, 'checksum_status': 'invalid'},
                                     sort_keys=True))
            return 0
        database = DatabaseTool(root, args.postgres_mode)
        if args.command == 'create':
            if os.name != 'posix' or getattr(os, 'geteuid', lambda: -1)() != 0:
                raise BackupError('backup creation requires root on the supported Debian host')
            bundle = create_backup(root, args.output or root / 'backups', database,
                                   no_systemd=args.no_systemd)
            print(f'backup complete: {bundle}')
        elif args.command == 'verify':
            verify_bundle(args.bundle, database)
            print('backup verification succeeded')
        elif args.command == 'inspect':
            print(json.dumps(inspect_bundle(args.bundle, database), sort_keys=True, indent=2))
        elif args.command == 'restore':
            if (not args.check and
                    (os.name != 'posix' or getattr(os, 'geteuid', lambda: -1)() != 0)):
                raise BackupError('restore requires root on the supported Debian host')
            restore_fresh(root, args.bundle, database, no_systemd=args.no_systemd,
                          check_only=args.check)
            print('restore check succeeded' if args.check else
                  'fresh restore completed; runtime and timer remain stopped')
    except (BackupError, install.InstallError, OSError, subprocess.SubprocessError) as exc:
        code = _failure_code(args.command, exc)
        print(f'{code}: backup/restore operation failed safely; '
              'inspect protected host state', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
