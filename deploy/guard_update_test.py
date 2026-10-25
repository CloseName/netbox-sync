"""Explicit optional Guard stage for the known test updater. No production defaults."""

import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import time
from contextlib import contextmanager

ROOT = Path('/netbox-test')
BACKUPS = Path('/netbox-sync-test/backups')
PYTHON = '/opt/netbox/venv/bin/python'
MANAGE = '/opt/netbox/netbox/manage.py'


class GuardUpdateError(RuntimeError):
    """Bounded operator-facing failure; underlying command output stays private."""


def compose_identity(container):
    """Use the running container's exact Compose files, restricted to the test root."""
    labels = container['Config'].get('Labels', {})
    if labels.get('com.docker.compose.project.working_dir') != '/netbox-test':
        raise GuardUpdateError('GUARD_WRONG_TEST_PROJECT')
    project = labels.get('com.docker.compose.project', '')
    files = labels.get('com.docker.compose.project.config_files', '').split(',')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', project) or any(
        not p.startswith('/netbox-test/') or '..' in PurePosixPath(p).parts for p in files
    ):
        raise GuardUpdateError('GUARD_COMPOSE_PATH_INVALID')
    return project, files


def marked(output, marker):
    """Ignore framework startup messages; require exactly one bounded JSON result."""
    rows = [line[len(marker):] for line in output.splitlines() if line.startswith(marker)]
    if len(rows) != 1:
        raise GuardUpdateError('GUARD_CHECK_INVALID')
    return json.loads(rows[0])


@contextmanager
def apply_lock():
    """Same inode as every Sync writer; do not wait behind a newly started import."""
    import fcntl
    fd = os.open('/run/netbox-sync/apply.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise GuardUpdateError('GUARD_SYNC_WRITE_ACTIVE') from None
        yield
    finally:
        os.close(fd)


class GuardUpdate:
    """Discover, back up, replace and verify only the two known NetBox services."""

    def __init__(self, run, source, commit):
        self.run, self.source, self.commit = run, source, commit
        self.command = ()
        self.bundle = None

    def compose(self, *args):
        return self.run(*self.command, *args)

    def manage(self, *args):
        return self.run('docker', 'exec', 'netbox', PYTHON, MANAGE, *args)

    def https(self):
        status = self.run('curl', '--silent', '--show-error', '--max-time', '30', '--output', '/dev/null',
                          '--write-out', '%{http_code}', 'https://netbox-test.indeed-id.hq/login/')
        if status != '200':
            raise GuardUpdateError('GUARD_HTTPS_FAILED')

    def check_config_hashes(self):
        """Do not apply unrelated pending Compose/env changes during a Guard update."""
        for service, expected in self.config_hashes.items():
            actual = self.compose('config', '--hash', service).split()
            if not re.fullmatch(r'[0-9a-f]{64}', expected) or actual != [service, expected]:
                raise GuardUpdateError('GUARD_CONFIG_DRIFT')

    def _compose_installation(self):
        """Identify the running services and reject configuration/image drift."""
        if ROOT.resolve() != ROOT:
            raise GuardUpdateError('GUARD_ROOT_SYMLINK_OUTSIDE_TEST')
        main = json.loads(self.run('docker', 'inspect', 'netbox'))[0]
        identity = compose_identity(main)
        project, files = identity
        if any(Path(p).resolve().parent != ROOT and ROOT not in Path(p).resolve().parents for p in files):
            raise GuardUpdateError('GUARD_COMPOSE_SYMLINK_OUTSIDE_TEST')
        self.command = ('docker', 'compose', '--project-directory', str(ROOT), '-p', project,
                        *(item for p in files for item in ('-f', p)))
        worker = self.compose('ps', '-q', 'netbox-worker').split()
        if len(worker) != 1:
            raise GuardUpdateError('GUARD_WORKER_AMBIGUOUS')
        containers = [main, json.loads(self.run('docker', 'inspect', worker[0]))[0]]
        if compose_identity(containers[1]) != identity:
            raise GuardUpdateError('GUARD_PROJECT_MISMATCH')
        self.config_hashes = {service: container['Config']['Labels'].get('com.docker.compose.config-hash', '')
                              for service, container in zip(('netbox', 'netbox-worker'), containers)}
        self.check_config_hashes()
        config = json.loads(self.compose('config', '--no-env-resolution', '--format', 'json'))
        services = config['services']
        self.tag = services['netbox']['image']
        if not re.fullmatch(r'netbox-with-sync-guard:[a-zA-Z0-9_.-]+', self.tag):
            raise GuardUpdateError('GUARD_IMAGE_NOT_MANAGED')
        self.old_image = containers[0]['Image']
        if any(c['Image'] != self.old_image or c['Config']['Image'] != self.tag or
               not c['State']['Running'] for c in containers) or services['netbox-worker']['image'] != self.tag:
            raise GuardUpdateError('GUARD_RUNNING_IMAGE_MISMATCH')
        return identity, files, containers, config

    def _backup_configuration(self, files, containers, config):
        """Select only discovered configuration files and test-local bind sources."""
        self.backup_paths = set(files)
        if (ROOT / '.env').exists():
            self.backup_paths.add(str(ROOT / '.env'))
        for service in config["services"].values():
            for env in service.get('env_file', []):
                self.backup_paths.add(env['path'] if isinstance(env, dict) else env)
        for kind in ('configs', 'secrets'):
            for value in config.get(kind, {}).values():
                if value.get('file'):
                    self.backup_paths.add(value['file'])
                else:
                    raise GuardUpdateError('GUARD_EXTERNAL_CONFIG_UNSUPPORTED')
        if any(ROOT not in Path(p).resolve().parents for p in self.backup_paths):
            raise GuardUpdateError('GUARD_CONFIG_OUTSIDE_TEST')
        for container in containers:
            for mount in container.get('Mounts', []):
                destination = PurePosixPath(mount['Destination'])
                if (destination == PurePosixPath('/opt') or destination == PurePosixPath('/opt/netbox-sync-guard')
                        or PurePosixPath('/opt/netbox-sync-guard') in destination.parents):
                    raise GuardUpdateError('GUARD_SOURCE_OVERRIDDEN_BY_MOUNT')
                if mount['Type'] == 'bind':
                    path = Path(mount['Source']).resolve()
                    if ROOT not in path.parents:
                        raise GuardUpdateError('GUARD_MOUNT_OUTSIDE_TEST')
                    self.backup_paths.add(str(path))

    def _database_preflight(self, identity, services):
        """Verify local database identity and tools without dumping or migrating."""
        # Derive database identity from Django; never print passwords or environment.
        db = marked(self.manage('shell', '-c',
            "import json; from django.conf import settings; d=settings.DATABASES['default']; "
            "print('GUARD_DB:'+json.dumps({**{k:d[k] for k in ('HOST','NAME','USER')}, "
            "'NATIVE':settings.PLUGINS_CONFIG.get('netbox_guard',{}).get('selectel_native_reconcile') is True}))"), 'GUARD_DB:')
        self.native = db.pop('NATIVE')
        if db['HOST'] not in services:
            raise GuardUpdateError('GUARD_DATABASE_NOT_LOCAL_COMPOSE_SERVICE')
        ids = self.compose('ps', '-q', db['HOST']).split()
        if len(ids) != 1:
            raise GuardUpdateError('GUARD_DATABASE_AMBIGUOUS')
        self.database = ids[0]
        database = json.loads(self.run('docker', 'inspect', self.database))[0]
        if compose_identity(database) != identity:
            raise GuardUpdateError('GUARD_DATABASE_PROJECT_MISMATCH')
        self.db = db
        self.run('docker', 'exec', self.database, 'pg_dump', '--version')
        self.run('docker', 'exec', self.database, 'pg_restore', '--version')
        self.manage('migrate', '--check')
        self.https()

    def _source_fingerprint(self):
        """Identify all Guard content including the two Dockerfile overlays."""
        spec = importlib.util.spec_from_file_location('guard_manifest', self.source / 'deploy/netbox_guard/release_manifest.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.fingerprint = module.fingerprint(module.manifest(self.source / 'deploy/netbox_guard', {
            'hardware_identity.py': self.source / 'netbox_sync/hardware_identity.py',
            'pfsense_preview.py': self.source / 'netbox_sync/pfsense_preview.py',
        }))

    def preflight(self):
        """Validate target, backup inputs and release content before any mutation."""
        identity, files, containers, config = self._compose_installation()
        self._backup_configuration(files, containers, config)
        self._database_preflight(identity, config['services'])
        self._source_fingerprint()

    def build(self):
        # Reuse the exact installed NetBox base, not a moving upstream tag.
        self.image = 'netbox-with-sync-guard:' + self.commit
        base = 'netbox-with-sync-guard:base-' + self.old_image.removeprefix('sha256:')
        self.run('docker', 'image', 'tag', self.old_image, base)
        self.run('docker', 'build', '--pull=false', '--build-arg', 'NETBOX_BASE_IMAGE=' + base,
                 '--label', 'org.opencontainers.image.revision=' + self.commit,
                 '-f', str(self.source / 'deploy/Dockerfile.netbox-guard'), '-t', self.image, str(self.source))
        self.new_image = json.loads(self.run('docker', 'image', 'inspect', self.image))[0]['Id']

    def backup(self):
        # Sync is already paused and backed up by update_test before this stage.
        self.compose('stop', 'netbox-worker', 'netbox')
        self.bundle = BACKUPS / ('guard-' + time.strftime('%Y%m%d-%H%M%S') + '-' + self.commit[:12])
        self.bundle.mkdir(mode=0o700)
        print('GUARD_BACKUP_PATH:', self.bundle, flush=True)
        archive = self.bundle / 'database.dump'
        fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            subprocess.run(['docker', 'exec', self.database, 'pg_dump', '-Fc', '-U', self.db['USER'], self.db['NAME']],
                           stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.PIPE, check=True, timeout=900)
            stream.flush()
            os.fsync(stream.fileno())
        if archive.stat().st_size == 0:
            raise GuardUpdateError('GUARD_BACKUP_EMPTY')
        with archive.open('rb') as stream:
            subprocess.run(['docker', 'exec', '-i', self.database, 'pg_restore', '--list'], stdin=stream,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=120)
        self.run('tar', '--create', '--gzip', '--file', str(self.bundle / 'configuration.tar.gz'),
                 '--', *sorted(self.backup_paths))
        self.run('tar', '--list', '--gzip', '--file', str(self.bundle / 'configuration.tar.gz'))
        self.run('docker', 'image', 'tag', self.old_image, 'netbox-with-sync-guard:before-' + self.commit)
        (self.bundle / 'release.json').write_text(json.dumps(dict(previous_image=self.old_image,
            configured_image=self.tag, target_commit=self.commit, fingerprint=self.fingerprint)))
        print('GUARD_BACKUP_VERIFIED:', self.bundle, flush=True)

    def activate(self):
        # Preserve the operator's existing Compose image reference; both services use it.
        self.check_config_hashes()
        self.run('docker', 'image', 'tag', self.new_image, self.tag)
        self.compose('run', '--rm', '--no-deps', '-T', '--pull', 'never', '--entrypoint', PYTHON,
                     'netbox', MANAGE, 'migrate', '--no-input')
        self.compose('up', '-d', '--no-deps', '--no-build', '--force-recreate', '--pull', 'never', '--wait',
                     '--wait-timeout', '180', 'netbox', 'netbox-worker')

    def verify(self):
        ids = self.compose('ps', '-q', 'netbox', 'netbox-worker').split()
        if len(ids) != 2:
            raise GuardUpdateError('GUARD_RUNTIME_MISSING')
        for container in json.loads(self.run('docker', 'inspect', *ids)):
            if container['Image'] != self.new_image or not container['State']['Running'] or \
                    container['State'].get('Health', {}).get('Status', 'healthy') != 'healthy':
                raise GuardUpdateError('GUARD_RUNTIME_MISMATCH')
        self.manage('check')
        self.manage('migrate', '--check')
        result = marked(self.manage('sync_guard_release_check', '--expected', self.fingerprint), 'GUARD_CHECK:')
        if (result['fingerprint'] != self.fingerprint or result['selectel_protocol'] != 1
                or result['native_reconcile'] is not self.native):
            raise GuardUpdateError('GUARD_PROTOCOL_MISMATCH')
        self.https()

    def apply(self):
        with apply_lock():
            for name in ('preflight', 'build', 'backup', 'activate', 'verify'):
                print('GUARD_STAGE:', name, flush=True)
                getattr(self, name)()
