"""Offline safety and failure-order contracts for the dedicated test updater."""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from deploy import update_test as updater

SHA = "a" * 40


@pytest.fixture
def config(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "secrets/netbox/selectel").mkdir(parents=True)
    (tmp_path / "config/compose.env").write_text(
        "NETBOX_SYNC_INGRESS_MODE=external\n" f'NETBOX_SYNC_NETBOX_SECRET_DIR={tmp_path / "secrets/netbox"}\n'
    )
    (tmp_path / "config/api.env").write_text(f"NETBOX_SYNC_PUBLIC_URL={updater.PUBLIC_URL}\n")
    (tmp_path / "secrets/netbox/bootstrap.json").write_text(
        json.dumps({"url": updater.NETBOX_URL, "status": "READY", "completed": True, "read_token": "PRIVATE"})
    )
    return tmp_path


def test_expected_config_and_uncertain_selectel_remain_unchanged(config):
    path = config / "secrets/netbox/selectel/29916.json"
    original = json.dumps(
        {"schedule": {"kind": "off"}, "next_run": None, "status": "attention", "error": "IMPORT_UNCONFIRMED"}
    )
    path.write_text(original)
    updater.check_configuration(config)
    assert path.read_text() == original


@pytest.mark.parametrize("patch", [{"url": "https://netbox.indeed-id.hq"}, {"status": "PENDING"}, {"completed": False}])
def test_wrong_target_or_unready_bootstrap_rejected(config, patch):
    path = config / "secrets/netbox/bootstrap.json"
    state = json.loads(path.read_text())
    state.update(patch)
    path.write_text(json.dumps(state))
    with pytest.raises(updater.UpdateError, match="target or bootstrap") as error:
        updater.check_configuration(config)
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize(
    "state", [{"schedule": {"kind": "daily"}}, {"next_run": 1}, {"status": "running"}, {"lifecycle_pending": True}]
)
def test_selectel_work_blocks_bootstrap_start(config, state):
    (config / "secrets/netbox/selectel/1.json").write_text(json.dumps(state))
    with pytest.raises(updater.UpdateError, match="Selectel"):
        updater.check_configuration(config)


@pytest.mark.parametrize(
    "file,text",
    [
        ("api.env", "NETBOX_SYNC_PUBLIC_URL=https://production.invalid\n"),
        ("compose.env", "NETBOX_SYNC_INGRESS_MODE=standalone\n"),
    ],
)
def test_wrong_ingress_or_public_url_rejected(config, file, text):
    (config / "config" / file).write_text(text)
    with pytest.raises(updater.UpdateError, match="configuration"):
        updater.check_configuration(config)


def test_child_input_is_devnull_and_no_shell(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="OK\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert updater.run("python3", "install.py") == "OK"
    assert calls[0][1]["stdin"] == subprocess.DEVNULL
    assert not calls[0][1].get("shell", False)
    assert calls[0][1]["check"] is True


@pytest.mark.parametrize("timer,services", [("active", ""), ("inactive", updater.SCHEDULER)])
def test_scheduler_must_remain_off(monkeypatch, tmp_path, timer, services):
    monkeypatch.setattr(updater, "run", lambda *args: timer)
    monkeypatch.setattr(updater, "compose", lambda *args: services)
    with pytest.raises(updater.UpdateError):
        updater.check_schedulers(tmp_path)


def test_cli_defaults_to_read_only_and_apply_needs_idle_ack(monkeypatch):
    calls = []
    monkeypatch.setattr(updater, "preflight", lambda *args: calls.append("check"))
    monkeypatch.setattr(updater, "update", lambda *args: calls.append("write"))
    assert updater.main(["--commit", SHA]) == 0
    assert calls == ["check"]
    with pytest.raises(SystemExit):
        updater.main(["--commit", SHA, "--apply"])
    assert calls == ["check"]
    assert updater.main(["--commit", SHA, "--apply", "--idle-confirmed"]) == 0
    assert calls[-1] == "write"


@pytest.mark.parametrize("value", ["main", "abc123", "../main", "A" * 40])
def test_cli_rejects_unpinned_release(value):
    with pytest.raises(SystemExit):
        updater.main(["--commit", value])


@pytest.fixture
def workflow(monkeypatch, tmp_path):
    calls = []
    previous = tmp_path / "releases/old"
    stage_failure = {"value": None}
    real_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == tmp_path / "current":
            return tmp_path / "releases" / SHA
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(updater, "preflight", lambda *args: previous)
    monkeypatch.setattr(updater, "check_configuration", lambda *args: calls.append(("config",)))
    monkeypatch.setattr(updater, "check_schedulers", lambda *args: calls.append(("schedulers",)))
    monkeypatch.setattr(updater, "verify_runtime", lambda *args: calls.append(("verified",)))

    def command(*args):
        calls.append(args)
        if stage_failure["value"] in args:
            raise subprocess.CalledProcessError(1, args)
        return ""

    monkeypatch.setattr(updater, "run", command)
    return tmp_path, calls, stage_failure


def test_update_without_backups_orders_install_start_and_keeps_schedules_off(workflow):
    root, calls, _ = workflow
    updater.update(root, root / "repo", SHA)
    install = next(i for i, call in enumerate(calls) if "--no-start" in call)
    start = next(i for i, call in enumerate(calls) if "up" in call)
    assert install < start
    assert not any("backup.py" in str(call) or "pg_dump" in call or "tar" in call for call in calls)
    assert "--ingress-mode" in calls[install] and "external" in calls[install]
    assert calls[start][-len(updater.SERVICES) :] == updater.SERVICES
    assert updater.SCHEDULER not in calls[start]
    assert not any("enable" in call or "--now" in call for call in calls)
    assert calls[-1] == ("verified",)


def test_combined_update_without_backup_updates_guard_then_reads_receipts(workflow, monkeypatch):
    root, calls, _ = workflow
    class Guard:
        def __init__(self, *args):
            pass
        def preflight(self):
            calls.append(("guard-preflight",))
        def apply(self):
            calls.append(("guard-apply",))
    monkeypatch.setattr(updater, "GuardUpdate", Guard)
    original = updater.run
    def run(*args):
        if args[-1] == "netbox_sync.selectel_recovery":
            calls.append(args)
            return json.dumps({"compatible": True, "accounts": [{"account": "29916", "error": "IMPORT_UNCONFIRMED"}]})
        return original(*args)
    monkeypatch.setattr(updater, "run", run)
    updater.update(root, root / "repo", SHA, with_guard=True)
    guard = calls.index(("guard-apply",))
    install = next(i for i, call in enumerate(calls) if "--no-start" in call)
    reconcile = next(i for i, call in enumerate(calls) if "netbox_sync.selectel_recovery" in call)
    assert guard < install < calls.index(("verified",)) < reconcile
    assert not any("netbox_sync.selectel_runner" in call for call in calls)


@pytest.mark.parametrize("failure", ["stop", "--no-start", "up"])
def test_failure_stops_without_retry_or_rollback(workflow, capsys, failure):
    root, calls, fail = workflow
    fail["value"] = failure
    with pytest.raises(subprocess.CalledProcessError):
        updater.update(root, root / "repo", SHA)
    assert failure in calls[-1]
    assert not any("restore" in call for call in calls)
    output = capsys.readouterr()
    assert "UPDATE_FAILED_STAGE:" in output.err
    assert "UPDATE_OK" not in output.out


@pytest.mark.parametrize("problem", ["image", "stopped", "unhealthy", "https"])
def test_runtime_verification_rejects_partial_success(monkeypatch, tmp_path, problem):
    containers = [
        {"Name": "/" + service, "State": {"Running": True}, "Config": {"Image": "netbox-sync:" + SHA}}
        for service in updater.SERVICES
    ]
    if problem == "image":
        containers[0]["Config"]["Image"] = "netbox-sync:old"
    elif problem == "stopped":
        containers[0]["State"]["Running"] = False
    elif problem == "unhealthy":
        containers[0]["State"]["Health"] = {"Status": "unhealthy"}
    monkeypatch.setattr(updater, "run", lambda *args: json.dumps(containers) if args[0] == "docker" else "502")
    monkeypatch.setattr(updater, "check_schedulers", lambda *args: None)
    with pytest.raises(updater.UpdateError):
        updater.verify_runtime(tmp_path, SHA)


def test_wrong_host_rejected_before_commands(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.socket, "gethostname", lambda: "production")
    monkeypatch.setattr(updater, "run", lambda *args: pytest.fail("No command may run"))
    with pytest.raises(updater.UpdateError):
        updater.preflight(tmp_path, tmp_path / "repo", SHA)


@pytest.mark.parametrize("problem", ["dirty", "head", "origin", "ancestry", "disk", "root"])
def test_preflight_rejects_unsafe_checkout_before_deployment(monkeypatch, tmp_path, problem):
    root = tmp_path / "installation"
    root.mkdir()
    monkeypatch.setattr(updater, "ROOT", root)
    monkeypatch.setattr(updater, "os", SimpleNamespace(name="posix", geteuid=lambda: 0))
    monkeypatch.setattr(updater.socket, "gethostname", lambda: "netbox-test")
    resolve = Path.resolve
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda path, *args, **kwargs: (
            root / "releases/old" if path == root / "current" else resolve(path, *args, **kwargs)
        ),
    )
    monkeypatch.setattr(
        updater.shutil, "disk_usage", lambda path: SimpleNamespace(free=0 if problem == "disk" else 5 * 1024**3)
    )
    calls = []

    def command(*args):
        calls.append(args)
        assert args[0] == "git", "Deployment must not run after a rejected checkout"
        if "status" in args:
            return " M file" if problem == "dirty" else ""
        if "rev-parse" in args:
            return "b" * 40 if problem == "head" else SHA
        if "remote" in args:
            return "https://other.invalid/repo" if problem == "origin" else "https://github.com/CloseName/netbox-sync"
        if problem == "ancestry":
            raise subprocess.CalledProcessError(1, args)
        return ""

    monkeypatch.setattr(updater, "run", command)
    with pytest.raises((updater.UpdateError, subprocess.CalledProcessError)):
        updater.preflight(root if problem != "root" else tmp_path / "other", root / "repo", SHA)


def test_failed_preflight_never_pauses_services(monkeypatch, tmp_path):
    def reject(*args):
        raise updater.UpdateError("Not ready")

    monkeypatch.setattr(updater, "preflight", reject)
    monkeypatch.setattr(updater, "run", lambda *args: pytest.fail("No mutations"))
    with pytest.raises(updater.UpdateError):
        updater.update(tmp_path, tmp_path / "repo", SHA)


def test_duplicate_configuration_rejected(config):
    path = config / "config/api.env"
    path.write_text(path.read_text() * 2)
    with pytest.raises(updater.UpdateError, match="duplicate"):
        updater.check_configuration(config)


def test_runtime_success_checks_public_tls_without_following_redirects(monkeypatch, tmp_path):
    calls = []
    containers = [
        {"Name": "/" + name, "State": {"Running": True}, "Config": {"Image": "netbox-sync:" + SHA}}
        for name in updater.SERVICES
    ]

    def command(*args):
        calls.append(args)
        return json.dumps(containers) if args[0] == "docker" else "200"

    monkeypatch.setattr(updater, "run", command)
    monkeypatch.setattr(updater, "check_schedulers", lambda *args: calls.append(("schedulers",)))
    updater.verify_runtime(tmp_path, SHA)
    assert calls[-1][0] == "curl"
    assert calls[-1][-1] == updater.PUBLIC_URL + "/"
    assert "--insecure" not in calls[-1] and "-k" not in calls[-1]
    assert "--location" not in calls[-1]
    assert ("schedulers",) in calls


def test_matching_evidence_preserves_decisions_without_raw_identifiers():
    from deploy.selectel_matching_evidence import report
    commands = []
    document = dict(account='29916', writes_performed=False, hosts=[
        dict(id=28, name='Existing host', status='collected', identifiers=[
            dict(kind='system_serial', value='PRIVATE-SERIAL')])], pending_dedicated=[
        dict(key='provider-key', name='Unlinked server', action='blocked',
             reason='identity_needs_confirmation', hardware=dict(status='collected',
             identifiers=[dict(kind='system_serial', value='PRIVATE-SERIAL')]), candidates=[
             dict(resource='device', id=28, name='Existing host', host_device_id=28,
                  evidence=dict(stable_identity=False, same_name=True, hardware_conflict=False,
                                public_ips=['PRIVATE-IP'], observed_guest_wans=[]))])])
    def manage(*args):
        commands.append(args)
        return "loaded config '/private/path'\n" + json.dumps(document)
    result = report(manage, '29916')
    assert commands == [('provider_hardware_check', '--account', '29916', '--actor', 'netbox-sync-selectel')]
    assert result['pending_dedicated'][0]['reason'] == 'identity_needs_confirmation'
    assert result['pending_dedicated'][0]['candidates'][0]['public_ip_match_count'] == 1
    assert result['decisions'] == {'blocked': 1}
    assert result['host_coverage'] == {'collected': 1}
    assert result['writes_performed'] is False
    assert 'PRIVATE' not in json.dumps(result) and '/private/path' not in json.dumps(result)


@pytest.mark.parametrize('payload', [
    'not json PRIVATE', '{}',
    json.dumps(dict(account='other', writes_performed=False)),
    json.dumps(dict(account='29916', writes_performed=True)),
])
def test_matching_evidence_rejects_bad_or_wrong_account_document(payload):
    from deploy.selectel_matching_evidence import report
    with pytest.raises(ValueError):
        report(lambda *args: payload, '29916')


@pytest.mark.parametrize('extra', [
    ['--apply', '--idle-confirmed'], ['--with-guard'],
    ['--diagnose-selectel', '29916', 'old-run'],
])
def test_matching_diagnostic_cannot_mutate_or_mix_modes(monkeypatch, extra):
    monkeypatch.setattr(updater, 'preflight', lambda *args: pytest.fail('Must reject before commands'))
    with pytest.raises(SystemExit):
        updater.main(['--commit', SHA, '--diagnose-selectel-matching', '29916', *extra])


def test_matching_diagnostic_uses_both_test_preflights_only(monkeypatch, capsys):
    from deploy import selectel_matching_evidence
    calls = []
    monkeypatch.setattr(updater, 'preflight', lambda *args: calls.append('sync-preflight'))
    class Guard:
        def __init__(self, *args):
            pass
        def preflight(self):
            calls.append('guard-preflight')
        def manage(self, *args):
            return 'unused'
    monkeypatch.setattr(updater, 'GuardUpdate', Guard)
    monkeypatch.setattr(selectel_matching_evidence, 'report',
                        lambda manage, account: calls.append(account) or dict(writes_performed=False))
    monkeypatch.setattr(updater, 'update', lambda *args, **kwargs: pytest.fail('No deployment'))
    assert updater.main(['--commit', SHA, '--diagnose-selectel-matching', '29916']) == 0
    assert calls == ['sync-preflight', 'guard-preflight', '29916']
    assert 'SELECTEL_MATCHING_EVIDENCE:' in capsys.readouterr().out


def test_matching_evidence_bounds_and_closed_labels():
    from deploy.selectel_matching_evidence import report
    document = dict(account='29916', writes_performed=False, hosts=[], pending_dedicated=[
        dict(key='key', name='server', action='PRIVATE-ACTION', reason='PRIVATE-REASON',
             hardware=dict(status='PRIVATE-STATUS', identifiers=[
                 dict(kind='PRIVATE-KIND', value='PRIVATE-VALUE')]), candidates=[])])
    result = report(lambda *args: json.dumps(document), '29916')
    assert 'PRIVATE' not in json.dumps(result)
    assert result['pending_dedicated'][0]['reason'] == 'unknown'
    document['pending_dedicated'] *= 2001
    with pytest.raises(ValueError):
        report(lambda *args: json.dumps(document), '29916')
    with pytest.raises(ValueError):
        report(lambda *args: pytest.fail('Invalid account must not run a command'), '--apply')


def test_matching_guard_preflight_failure_never_reads_inventory(monkeypatch):
    monkeypatch.setattr(updater, 'preflight', lambda *args: None)
    class Guard:
        def __init__(self, *args):
            pass
        def preflight(self):
            raise updater.GuardUpdateError('GUARD_CONFIG_DRIFT')
        def manage(self, *args):
            pytest.fail('Wrong installation must not be read')
    monkeypatch.setattr(updater, 'GuardUpdate', Guard)
    assert updater.main(['--commit', SHA, '--diagnose-selectel-matching', '29916']) == 1
