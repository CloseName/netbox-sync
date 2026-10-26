"""Guard release automation must reject unknown targets and preserve pause ordering without backups."""
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


def test_apply_pauses_before_activation_without_backups(monkeypatch):
    monkeypatch.setattr(guard, 'apply_lock', nullcontext)
    calls = []
    update = guard.GuardUpdate(lambda *args: calls.append(args) or "", None, "a" * 40)
    for name in ("preflight", "build", "pause", "activate", "verify"):
        monkeypatch.setattr(update, name, lambda name=name: calls.append(name))
    update.apply()
    assert calls == ["preflight", "build", "pause", "activate", "verify"]


@pytest.mark.parametrize("failure", ["preflight", "build", "pause", "activate", "verify"])
def test_failure_never_retries_or_rolls_back(monkeypatch, failure):
    monkeypatch.setattr(guard, 'apply_lock', nullcontext)
    calls = []
    update = guard.GuardUpdate(lambda *args: "", None, "a" * 40)
    def stage(name):
        calls.append(name)
        if name == failure:
            raise guard.GuardUpdateError("failed")
    for name in ("preflight", "build", "pause", "activate", "verify"):
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
    assert not any(word in call for call in calls for word in ('pg_dump', 'pg_restore', 'tar'))
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


def test_pause_only_stops_test_services_without_archives(monkeypatch, tmp_path):
    calls = []
    update = guard.GuardUpdate(lambda *args: calls.append(args), tmp_path, 'a'*40)
    update.command = ('docker', 'compose')
    update.pause()
    assert calls == [('docker', 'compose', 'stop', 'netbox-worker', 'netbox')]
    assert list(tmp_path.iterdir()) == []


def test_drift_report_has_service_and_comparison_without_secrets(installation, capsys):
    update, containers, services, calls = installation
    containers[0]['Config']['Labels']['com.docker.compose.config-hash'] = 'f'*64
    containers[0]['Config']['Env'] = ['PRIVATE=hidden-value']
    services['netbox']['environment'] = {'PRIVATE': 'different-secret'}
    services['netbox']['env_file'] = [{'path': '/netbox-test/private.env'}]
    with pytest.raises(guard.GuardUpdateError, match='CONFIG_DRIFT'):
        update.preflight()
    out = capsys.readouterr().out
    report = json.loads(next(line.split(': ', 1)[1] for line in out.splitlines() if line.startswith('GUARD_CONFIG_REPORT: ')))
    row = report['services'][0]
    assert row['service'] == 'netbox' and row['hash_matches'] is False
    assert row['configured_environment_matches_runtime'] is False
    assert row['env_file_count'] == 1
    assert not any(secret in out for secret in ('PRIVATE', 'hidden-value', 'different-secret', 'private.env'))
    assert not any(word in call for call in calls for word in ('stop','up','build','tag','pg_dump'))


def test_drift_diagnostic_failure_does_not_hide_block_or_expose_output(installation, capsys):
    import subprocess
    update, containers, _, calls = installation
    containers[0]['Config']['Labels']['com.docker.compose.config-hash'] = 'f'*64
    original = update.run
    def run(*args):
        if args[-2:] == ('version', '--short'):
            raise subprocess.CalledProcessError(1, args, output='private-output', stderr='secret-error')
        return original(*args)
    update.run = run
    with pytest.raises(guard.GuardUpdateError, match='CONFIG_DRIFT'):
        update.preflight()
    out = capsys.readouterr().out
    assert '"details_available": false' in out
    assert 'private-output' not in out and 'secret-error' not in out
    assert not any('stop' in call or 'up' in call for call in calls)
