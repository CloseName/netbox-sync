"""WEB-7 safe diagnostics aggregation and API tests."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from tests.auth_support import authenticated_app as create_app
from netbox_sync.api.settings import ApiSettings
from netbox_sync.application.diagnostics import (DiagnosticStatus, DiagnosticsService,
                                                      HistorySnapshot)
from netbox_sync.run_history import ActionCounts, RunStatus, RunTrigger, SyncRun


NOW = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)


class Sources:
    def __init__(self, values=None, failure=False):
        self.values = values or ()
        self.failure = failure

    def list_sources(self):
        if self.failure:
            raise RuntimeError('RAW_REGISTRY_SECRET')
        return self.values


class History:
    def __init__(self, snapshot=None, failure=False):
        self.snapshot = snapshot or HistorySnapshot((), (), (), (), ())
        self.failure = failure

    def diagnostics_snapshot(self, _before, limit):
        assert limit == 100
        if self.failure:
            raise RuntimeError('RAW_DATABASE_SECRET')
        return self.snapshot


class Worker:
    def __init__(self, healthy=True, raw=False):
        self.healthy = healthy
        self.raw = raw

    def health(self):
        if self.raw:
            raise OSError('RAW_SOCKET_SECRET')
        return self.healthy


def source(instance='pve-test', source_type='proxmox', enabled=True, sync_enabled=True,
           interval=600):
    return SimpleNamespace(source_instance=instance, type=source_type, enabled=enabled,
                           sync_enabled=sync_enabled, sync_interval_seconds=interval)


def run(instance='pve-test', source_type='proxmox', status=RunStatus.SUCCEEDED,
        trigger=RunTrigger.SCHEDULED,
        age=60, identifier='11111111-1111-4111-8111-111111111111'):
    started = NOW - timedelta(seconds=age)
    return SyncRun(UUID(identifier), instance, source_type, trigger, started,
                   None if status is RunStatus.RUNNING else started + timedelta(seconds=1),
                   None if status is RunStatus.RUNNING else 1000, status, None, None,
                   ActionCounts(), None, None, 'system/scheduler')


def service(sources=None, snapshot=None, registry_failure=False, history_failure=False,
            discovery=True, apply=True):
    return DiagnosticsService(
        Sources(sources, registry_failure), History(snapshot, history_failure),
        Worker(discovery, raw=discovery == 'raw'), Worker(apply, raw=apply == 'raw'),
        stale_seconds=7200, clock=lambda: NOW)


def test_all_healthy_and_no_run_source_unknown():
    successful = run()
    result = service((source(),), HistorySnapshot(
        (successful,), (successful,), (successful,), (), ())).check()
    assert result.overall_status is DiagnosticStatus.HEALTHY
    assert result.sources[0].status is DiagnosticStatus.HEALTHY
    assert result.components['scheduler'].status is DiagnosticStatus.HEALTHY
    empty = service((source('new-source'),)).check()
    assert empty.sources[0].status is DiagnosticStatus.UNKNOWN
    assert empty.components['scheduler'].status is DiagnosticStatus.UNKNOWN


def test_stale_running_is_read_only_warning_and_recent_running_is_not_stale():
    stale = run(status=RunStatus.RUNNING, age=8000)
    previous = run(age=9000, trigger=RunTrigger.MANUAL,
                   identifier='22222222-2222-4222-8222-222222222222')
    snapshot = HistorySnapshot((stale,), (previous,), (), (previous,), (stale,))
    result = service((source(),), snapshot).check()
    assert result.overall_status is DiagnosticStatus.DEGRADED
    assert result.sources[0].warnings == ('STALE_RUNNING',)
    assert result.stale_runs[0].age_seconds == 8000
    assert result.stale_runs[0].source_type == 'proxmox'
    assert result.stale_runs[0].trigger == 'scheduled'
    assert 'Automatic retry was not performed.' in result.stale_runs[0].safe_message
    recent = run(status=RunStatus.RUNNING, age=60)
    recent_result = service((source(),), HistorySnapshot((recent,), (), (), (), ())).check()
    assert recent_result.stale_runs == ()


def test_partial_failures_are_isolated_and_raw_errors_are_hidden():
    result = service((source(),), history_failure=True, discovery='raw', apply=False).check()
    assert result.overall_status is DiagnosticStatus.DEGRADED
    assert result.components['run_history'].safe_code == 'RUN_HISTORY_UNAVAILABLE'
    assert result.components['discovery_worker'].safe_code == 'DISCOVERY_WORKER_UNAVAILABLE'
    assert result.components['apply_worker'].safe_code == 'APPLY_WORKER_UNAVAILABLE'
    assert not any(secret in repr(result) for secret in (
        'RAW_DATABASE_SECRET', 'RAW_SOCKET_SECRET'))


def test_registry_unavailable_is_unhealthy_but_response_remains_available():
    result = service(registry_failure=True).check()
    assert result.overall_status is DiagnosticStatus.UNHEALTHY
    assert result.components['registry'].safe_code == 'REGISTRY_UNAVAILABLE'
    assert result.sources == ()
    assert 'RAW_REGISTRY_SECRET' not in repr(result)


def test_latest_failure_with_previous_success_and_delayed_schedule_is_degraded():
    failed = run(status=RunStatus.FAILED, age=60)
    old_success = run(age=4000, identifier='22222222-2222-4222-8222-222222222222')
    result = service((source(),), HistorySnapshot(
        (failed,), (old_success,), (old_success,), (), ())).check()
    assert result.overall_status is DiagnosticStatus.DEGRADED
    assert result.sources[0].status is DiagnosticStatus.DEGRADED
    assert result.sources[0].warnings == ('SCHEDULED_ACTIVITY_DELAYED',)
    assert result.components['scheduler'].status is DiagnosticStatus.DEGRADED


def test_terminal_failure_without_any_success_is_unhealthy():
    failed = run(status=RunStatus.FAILED, age=60)
    result = service((source(),), HistorySnapshot((failed,), (), (failed,), (), ())).check()
    assert result.overall_status is DiagnosticStatus.UNHEALTHY
    assert result.sources[0].status is DiagnosticStatus.UNHEALTHY


def test_disabled_and_sync_disabled_sources_do_not_claim_scheduler_failure():
    result = service((source('disabled', enabled=False),
                      source('manual-only', sync_enabled=False))).check()
    assert [item.status for item in result.sources] == [DiagnosticStatus.UNKNOWN] * 2
    assert result.components['scheduler'].status is DiagnosticStatus.UNKNOWN


def test_esxi_source_uses_the_same_history_status_rules():
    successful = run('esxi-test', source_type='esxi')
    result = service((source('esxi-test', 'esxi'),), HistorySnapshot(
        (successful,), (successful,), (successful,), (), (), (successful,))).check()
    assert result.sources[0].source_type == 'esxi'
    assert result.sources[0].status is DiagnosticStatus.HEALTHY


def test_esxi_failure_is_scoped_without_degrading_healthy_proxmox_source():
    proxmox = run('pve-test', source_type='proxmox')
    esxi = run(
        'esxi-test', source_type='esxi', status=RunStatus.FAILED,
        identifier='22222222-2222-4222-8222-222222222222',
    )
    result = service(
        (source('pve-test', 'proxmox'), source('esxi-test', 'esxi')),
        HistorySnapshot(
            (proxmox, esxi), (proxmox,), (proxmox, esxi), (), (),
            (proxmox, esxi),
        ),
    ).check()
    by_source = {item.source_instance: item for item in result.sources}

    assert by_source['pve-test'].status is DiagnosticStatus.HEALTHY
    assert by_source['esxi-test'].status is DiagnosticStatus.UNHEALTHY


def test_diagnostics_api_is_200_with_allowlisted_dto_and_health_stays_lightweight():
    diagnostic = service((source(),)).check()
    with TestClient(create_app(ApiSettings(), diagnostics_service=SimpleNamespace(
            check=lambda: diagnostic))) as client:
        health = client.get('/api/v1/health')
        response = client.get('/api/v1/diagnostics')
    assert health.status_code == 200 and health.json() == {'status': 'healthy'}
    assert response.status_code == 200
    assert response.json()['overall_status'] == 'HEALTHY'
    serialized = repr(response.json())
    assert not any(value in serialized.casefold() for value in (
        'password', 'token_secret', 'dsn', 'traceback', 'socket_path'))


def test_diagnostics_adds_no_privileged_api_boundary():
    compose = Path('compose.web.yml').read_text(encoding='utf-8')
    api = compose.split('  netbox-sync-secret-broker:', 1)[0]
    assert 'NETBOX_SYNC_RUN_WRITER_DSN' not in api
    assert '/run/secrets/netbox-sync' not in api
    assert 'netbox-apply-token' not in api
    assert 'docker.sock' not in compose
    diagnostics_code = ''.join(path.read_text(encoding='utf-8') for path in (
        Path('netbox_sync/api/app.py'), Path('netbox_sync/api/worker_health.py'),
        Path('netbox_sync/application/diagnostics.py')))
    assert not any(value in diagnostics_code for value in (
        'systemctl', 'subprocess.', '/run/systemd', 'docker.sock'))


def test_stale_threshold_environment_is_bounded_and_has_safe_default():
    assert ApiSettings.from_environment({
        'NETBOX_SYNC_DIAGNOSTICS_STALE_SECONDS': '900',
    }).diagnostics_stale_seconds == 900
    for value in ('not-a-number', '299', '604801'):
        assert ApiSettings.from_environment({
            'NETBOX_SYNC_DIAGNOSTICS_STALE_SECONDS': value,
        }).diagnostics_stale_seconds == 7200
