"""Guard release automation must reject unknown targets and preserve backup ordering."""
import pytest
from contextlib import nullcontext
from deploy import guard_update_test as guard
import json
from pathlib import Path
from copy import deepcopy


def test_read_only_preflight_rejects_other_compose_project():
    with pytest.raises(guard.GuardUpdateError):
        guard.compose_identity({"Config": {"Labels": {
            "com.docker.compose.project.working_dir": "/netbox-production"}}})


@pytest.mark.parametrize("files", ["/etc/compose.yml", "/netbox-test/../production/compose.yml", ""])
def test_compose_files_cannot_escape_test_root(files):
    with pytest.raises(guard.GuardUpdateError):
        guard.compose_identity({"Config": {"Labels": {
            "com.docker.compose.project.working_dir": "/netbox-test",
            "com.docker.compose.project": "netbox-test",
            "com.docker.compose.project.config_files": files}}})


def test_apply_does_not_start_before_backup_and_migrations(monkeypatch):
    monkeypatch.setattr(guard, 'apply_lock', nullcontext)
    calls = []
    update = guard.GuardUpdate(lambda *args: calls.append(args) or "", None, "a" * 40)
    for name in ("preflight", "build", "backup", "activate", "verify"):
        monkeypatch.setattr(update, name, lambda name=name: calls.append(name))
    update.apply()
    assert calls == ["preflight", "build", "backup", "activate", "verify"]


@pytest.mark.parametrize("failure", ["preflight", "build", "backup", "activate", "verify"])
def test_failure_never_retries_or_rolls_back(monkeypatch, failure):
    monkeypatch.setattr(guard, 'apply_lock', nullcontext)
    calls = []
    update = guard.GuardUpdate(lambda *args: "", None, "a" * 40)
    def stage(name):
        calls.append(name)
        if name == failure:
            raise guard.GuardUpdateError("failed")
    for name in ("preflight", "build", "backup", "activate", "verify"):
        monkeypatch.setattr(update, name, lambda name=name: stage(name))
    with pytest.raises(guard.GuardUpdateError):
        update.apply()
    assert calls[-1] == failure and calls.count(failure) == 1


@pytest.fixture
def installation(monkeypatch):
    # Exercise the complete preflight without Docker or a server.
    monkeypatch.setattr(Path, 'resolve', lambda path: path)
    labels = {'com.docker.compose.project.working_dir': '/netbox-test',
              'com.docker.compose.config-hash': 'a'*64,
              'com.docker.compose.project': 'netbox-test',
              'com.docker.compose.project.config_files': '/netbox-test/docker-compose.yml'}
    container = dict(Image='sha256:' + 'a'*64, Config=dict(Image='netbox-with-sync-guard:test', Labels=labels),
                     State=dict(Running=True), Mounts=[])
    containers = [deepcopy(container), deepcopy(container)]
    services = {'netbox': {'image': 'netbox-with-sync-guard:test'},
                'netbox-worker': {'image': 'netbox-with-sync-guard:test'}, 'postgres': {}}
    calls = []
    def run(*args):
        calls.append(args)
        if args[0] == 'curl':
            return '200'
        if '--hash' in args:
            return args[-1] + ' ' + 'a'*64
        if args[:3] == ('docker', 'inspect', 'netbox'):
            return json.dumps(containers[:1])
        if args[:3] == ('docker', 'inspect', 'worker-id'):
            return json.dumps(containers[1:])
        if args[:3] == ('docker', 'inspect', 'database-id'):
            return json.dumps([container])
        if 'config' in args and '--format' in args:
            return json.dumps({'services': services})
        if 'shell' in args:
            return 'GUARD_DB:' + json.dumps(dict(HOST='postgres', NAME='netbox', USER='netbox', NATIVE=False))
        if args[-3:] == ('ps', '-q', 'postgres'):
            return 'database-id'
        if args[-3:] == ('ps', '-q', 'netbox-worker'):
            return 'worker-id'
        return ''
    update = guard.GuardUpdate(run, Path(__file__).parents[1], 'b'*40)
    return update, containers, services, calls


def test_preflight_is_read_only_and_checks_source_fingerprint(installation):
    update, _, _, calls = installation
    update.preflight()
    assert len(update.fingerprint) == 64
    assert not any(word in call for call in calls for word in ('up', 'stop', 'build', 'tag', 'run'))
    assert all('--check' in call for call in calls if 'migrate' in call)


def test_changed_compose_definition_is_rejected_before_any_stop(installation):
    update, containers, _, calls = installation
    containers[0]['Config']['Labels']['com.docker.compose.config-hash'] = 'f'*64
    with pytest.raises(guard.GuardUpdateError, match='CONFIG_DRIFT'):
        update.preflight()
    assert not any('stop' in call for call in calls)


@pytest.mark.parametrize('problem', ['worker-image', 'stopped', 'foreign-image', 'source-mount', 'external-mount'])
def test_preflight_rejects_unsafe_installations(installation, problem):
    update, containers, services, calls = installation
    if problem == 'worker-image':
        containers[1]['Image'] = 'sha256:' + 'c'*64
    elif problem == 'stopped':
        containers[0]['State']['Running'] = False
    elif problem == 'foreign-image':
        services['netbox']['image'] = 'production/netbox:latest'
    else:
        containers[0]['Mounts'] = [dict(Type='bind', Source='/production/config' if problem == 'external-mount' else '/netbox-test/plugin',
                                       Destination='/etc/netbox/config' if problem == 'external-mount' else '/opt/netbox-sync-guard')]
    with pytest.raises(guard.GuardUpdateError):
        update.preflight()
    assert not any('stop' in call or 'build' in call for call in calls)


def test_build_uses_installed_base_without_pull(installation):
    update, _, _, calls = installation
    update.preflight()
    old = update.run
    def run(*args):
        if args[:3] == ('docker', 'image', 'inspect'):
            return json.dumps([{'Id': 'sha256:' + 'd'*64}])
        return old(*args)
    update.run = run
    update.build()
    build = next(call for call in calls if call[:2] == ('docker', 'build'))
    assert '--pull=false' in build
    assert 'NETBOX_BASE_IMAGE=netbox-with-sync-guard:base-' + 'a'*64 in build
    assert not any('stop' in call for call in calls)


def test_activation_starts_only_netbox_services_after_migration(installation):
    update, _, _, calls = installation
    update.preflight()
    update.new_image = 'sha256:' + 'd'*64
    calls.clear()
    update.activate()
    assert len(calls) == 5
    assert 'migrate' in calls[3]
    assert calls[4][-2:] == ('netbox', 'netbox-worker')
    assert '--no-deps' in calls[4] and '--no-build' in calls[4] and '--pull' in calls[4]


@pytest.mark.parametrize('failure', [None, 'pg_dump', 'pg_restore', 'tar'])
def test_backup_failure_never_reports_verified_or_changes_configured_image(monkeypatch, tmp_path, capsys, failure):
    import subprocess
    monkeypatch.setattr(guard, 'BACKUPS', tmp_path)
    calls = []
    def run(*args):
        calls.append(args)
        if args[0] == failure:
            raise subprocess.CalledProcessError(1, args)
        return ''
    def process(args, **kwargs):
        calls.append(tuple(args))
        if failure in args:
            raise subprocess.CalledProcessError(1, args)
        if 'pg_dump' in args:
            assert kwargs['stdin'] == subprocess.DEVNULL
            kwargs['stdout'].write(b'PGDMP-fixture')
        else:
            assert kwargs['stdin'].read() == b'PGDMP-fixture'
        return None
    monkeypatch.setattr(subprocess, 'run', process)
    update = guard.GuardUpdate(run, tmp_path, 'a'*40)
    update.command = ('docker', 'compose')
    update.database, update.db = 'db-id', dict(USER='netbox', NAME='netbox')
    update.old_image, update.tag = 'sha256:' + 'b'*64, 'netbox-with-sync-guard:test'
    update.fingerprint, update.backup_paths = 'c'*64, {'/netbox-test/config'}
    if failure:
        with pytest.raises(subprocess.CalledProcessError):
            update.backup()
    else:
        update.backup()
        assert (update.bundle / 'database.dump').read_bytes() == b'PGDMP-fixture'
        assert json.loads((update.bundle / 'release.json').read_text())['previous_image'] == update.old_image
    output = capsys.readouterr().out
    assert ('GUARD_BACKUP_VERIFIED:' in output) == (failure is None)
    assert calls[0] == ('docker', 'compose', 'stop', 'netbox-worker', 'netbox')
    assert not any('migrate' in call or 'up' in call or update.tag in call for call in calls)
