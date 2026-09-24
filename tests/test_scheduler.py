"""WEB-8 deterministic scheduling and fixed-tick execution tests."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pathlib import Path

import pytest

from netbox_sync.application.scheduling import SchedulerState, evaluate_schedule
from netbox_sync.scheduler_runtime import run_scheduler_tick, scheduler_summary_lines
from netbox_sync.source_registry import SourceLoadResult
from netbox_sync.source_bootstrap import load_scheduler_source_configs
from tests.sample_data import sample_source_config

NOW = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)


def source(instance='pve-a', interval=600, **changes):
    return replace(sample_source_config(), id=instance, source_instance=instance,
                   sync_interval_seconds=interval, **changes)


def run(instance='pve-a', age=300, status='SUCCEEDED'):
    return SimpleNamespace(source_instance=instance, started_at=NOW - timedelta(seconds=age),
                           status=SimpleNamespace(value=status))


def decision(config, latest=None, running=None):
    return evaluate_schedule(config, latest, running, NOW, 7200)


def test_schedule_states_and_exact_due_boundary():
    assert decision(source(sync_enabled=False)).state is SchedulerState.DISABLED
    assert decision(source(enabled=False)).state is SchedulerState.DISABLED
    assert decision(source()).state is SchedulerState.DUE
    assert decision(source(), run(age=599)).state is SchedulerState.WAITING
    assert decision(source(), run(age=600)).state is SchedulerState.DUE
    assert decision(source(), run(age=1900)).state is SchedulerState.DELAYED


def test_recent_running_blocks_but_stale_running_does_not_and_cadence_is_started_at():
    recent = run(age=100, status='RUNNING')
    assert decision(source(interval=60), recent, recent).state is SchedulerState.RUNNING
    stale = run(age=8000, status='RUNNING')
    result = decision(source(), stale, stale)
    assert result.state is SchedulerState.DELAYED
    assert result.next_expected_at == stale.started_at + timedelta(seconds=600)


class Repository:
    def __init__(self, scheduled=(), running=(), start_failure=None):
        self.scheduled, self.running = scheduled, running
        self.started, self.finished, self.start_failure = [], [], start_failure

    def latest_by_source(self, *, trigger=None, status=None):
        assert trigger == 'scheduled'
        return self.running if status == 'RUNNING' else self.scheduled

    def scheduled_reconciliation_required(self, source_instance):
        return False

    def start_run(self, instance, source_type, trigger, created_by):
        if instance == self.start_failure:
            raise RuntimeError('history failed')
        self.started.append(instance)
        return SimpleNamespace(run_id=instance)

    def finish_run(self, run_id, status, **_values):
        self.finished.append((run_id, status.value))


def test_tick_executes_only_due_once_with_different_intervals_and_no_catchup():
    repo = Repository((run('pve-a', 301), run('pve-b', 599)))
    seen = []
    tick = run_scheduler_tick((source('pve-a', 300), source('pve-b', 600)),
                              lambda config: seen.append(config.source_instance), repo,
                              clock=lambda: NOW)
    assert seen == ['pve-a']
    assert repo.started == ['pve-a']
    assert tick.counts['due'] == 1 and tick.counts['waiting'] == 1


def test_proxmox_and_esxi_keep_independent_cadence_and_history_keys():
    repo = Repository((run('pve-a', 301), run('esxi-b', 599)))
    configs = (
        source('pve-a', 300),
        source(
            'esxi-b', 600, source_type='esxi', legacy_identity_owner=False,
        ),
    )
    seen = []

    tick = run_scheduler_tick(
        configs,
        lambda config: seen.append((config.source_instance, config.source_type)),
        repo,
        clock=lambda: NOW,
    )

    assert seen == [('pve-a', 'proxmox')]
    assert repo.started == ['pve-a']
    assert [(item.source_instance, item.state) for item in tick.decisions] == [
        ('esxi-b', SchedulerState.WAITING),
        ('pve-a', SchedulerState.DUE),
    ]


def test_recent_running_skips_one_stale_allows_one_and_failure_is_isolated():
    recent, stale = run('pve-a', 60, 'RUNNING'), run('pve-b', 8000, 'RUNNING')
    repo = Repository((recent, stale), (recent, stale))
    seen = []
    def execute(config):
        seen.append(config.source_instance)
        if config.source_instance == 'pve-b':
            raise RuntimeError('safe isolation')
    tick = run_scheduler_tick((source('pve-a'), source('pve-b'), source('pve-c')),
                              execute, repo, clock=lambda: NOW)
    assert seen == ['pve-b', 'pve-c']
    assert tick.execution.failed == 1 and tick.execution.succeeded == 1
    assert tick.counts['running'] == 1
    assert repo.finished[0][0] == 'pve-b' and repo.finished[1][0] == 'pve-c'


def test_disabled_source_creates_no_run_and_reenabled_overdue_is_due():
    old = run(age=10000)
    repo = Repository((old,))
    tick = run_scheduler_tick((source(sync_enabled=False),), lambda _source: None,
                              repo, clock=lambda: NOW)
    assert tick.counts['disabled'] == 1 and repo.started == []
    assert decision(source(), old).state is SchedulerState.DELAYED


def test_inventory_tick_evaluates_without_provider_or_history_writes():
    repo = Repository()
    tick = run_scheduler_tick((source(),), lambda _source: pytest.fail('must not execute'),
                              repo, clock=lambda: NOW, execute_due=False)
    assert tick.counts['due'] == 1
    assert tick.execution.total == 0 and repo.started == []


def test_tracked_fixed_tick_is_final_and_shared_lock_is_unchanged():
    timer = Path('deploy/systemd/netbox-sync.timer').read_text(encoding='utf-8')
    service = Path('deploy/systemd/netbox-sync.service').read_text(encoding='utf-8')
    wrapper = Path('scripts/run-scheduled-sync.sh').read_text(encoding='utf-8')
    assert 'OnUnitActiveSec=60s' in timer
    assert 'AccuracySec=5s' in timer
    assert '/usr/bin/flock -n /run/netbox-sync/apply.lock' in wrapper
    assert '/usr/bin/flock' not in service


def test_scheduler_loader_includes_disabled_waiting_and_runnable_sources():
    configs = (source('disabled', enabled=False), source('manual', sync_enabled=False),
               source('active'))
    records = tuple(SimpleNamespace(to_source_config=lambda value=value: value)
                    for value in configs)
    registry = SimpleNamespace(list_sources_isolated=lambda: tuple(
        SourceLoadResult(record, True) for record in records))
    loaded = load_scheduler_source_configs({
        'SOURCE_CONFIG_MODE': 'registry-all', 'NETBOX_SYNC_REGISTRY_DSN': 'fixture',
        'NETBOX_SYNC_REGISTRY_SCHEMA': 'netbox_sync'},
        registry_factory=lambda _dsn, _schema: registry)
    assert tuple(item.config for item in loaded) == configs


def test_evaluation_failure_is_isolated_and_due_source_executes(monkeypatch):
    real_evaluate = evaluate_schedule

    def isolated(config, *args):
        if config.source_instance == 'pve-a':
            raise RuntimeError('RAW SECRET EVALUATION DETAIL')
        return real_evaluate(config, *args)

    monkeypatch.setattr('netbox_sync.scheduler_runtime.evaluate_schedule', isolated)
    repo, seen = Repository(), []
    tick = run_scheduler_tick((source('pve-a'), source('pve-b')),
                              lambda config: seen.append(config.source_instance), repo,
                              clock=lambda: NOW)
    summary = '\n'.join(scheduler_summary_lines(tick))
    assert seen == ['pve-b'] and repo.started == ['pve-b']
    assert tick.evaluation_failed == 1 and tick.failed is True
    assert 'evaluation_failed=1' in summary and 'RAW SECRET' not in summary
    assert tick.counts['due'] == 1


def test_malformed_conversion_is_isolated_before_due_execution():
    valid = SimpleNamespace(to_source_config=lambda: source('pve-b'))
    registry = SimpleNamespace(list_sources_isolated=lambda: (
        SourceLoadResult(None, False), SourceLoadResult(valid, True)))
    loaded = load_scheduler_source_configs({
        'SOURCE_CONFIG_MODE': 'registry-all', 'NETBOX_SYNC_REGISTRY_DSN': 'fixture',
        'NETBOX_SYNC_REGISTRY_SCHEMA': 'netbox_sync'},
        registry_factory=lambda _dsn, _schema: registry)
    repo, seen = Repository(), []
    tick = run_scheduler_tick(loaded, lambda config: seen.append(config.source_instance),
                              repo, clock=lambda: NOW)
    assert seen == ['pve-b'] and repo.started == ['pve-b']
    assert tick.evaluation_failed == 1 and len(tick.decisions) == 2


def test_evaluation_failure_with_waiting_source_still_has_summary(monkeypatch):
    real_evaluate = evaluate_schedule

    def isolated(config, *args):
        if config.source_instance == 'pve-a':
            raise RuntimeError('private detail')
        return real_evaluate(config, *args)

    monkeypatch.setattr('netbox_sync.scheduler_runtime.evaluate_schedule', isolated)
    repo = Repository((run('pve-b', 10),))
    tick = run_scheduler_tick((source('pve-a'), source('pve-b')),
                              lambda _config: pytest.fail('must not execute'), repo,
                              clock=lambda: NOW)
    assert tick.execution.total == 0 and tick.counts['waiting'] == 1
    assert 'evaluation_failed=1' in scheduler_summary_lines(tick)


def test_one_evaluation_failure_does_not_block_two_due_sources(monkeypatch):
    real_evaluate = evaluate_schedule

    def isolated(config, *args):
        if config.source_instance == 'pve-a':
            raise RuntimeError('private detail')
        return real_evaluate(config, *args)

    monkeypatch.setattr('netbox_sync.scheduler_runtime.evaluate_schedule', isolated)
    repo, seen = Repository(), []
    tick = run_scheduler_tick((source('pve-a'), source('pve-b'), source('pve-c')),
                              lambda config: seen.append(config.source_instance), repo,
                              clock=lambda: NOW)
    assert seen == ['pve-b', 'pve-c'] and tick.counts['due'] == 2
    assert tick.evaluation_failed == 1


def test_manual_history_does_not_shift_scheduled_cadence():
    scheduled = run(age=600)
    manual = run(age=300)
    scheduled.trigger, manual.trigger = 'scheduled', 'manual'

    class MixedHistory(Repository):
        history = (scheduled, manual)

        def latest_by_source(self, *, trigger=None, status=None):
            assert trigger == 'scheduled'
            if status == 'RUNNING':
                return ()
            matches = tuple(item for item in self.history if item.trigger == trigger)
            return (max(matches, key=lambda item: item.started_at),)

    tick = run_scheduler_tick((source(interval=600),), lambda _config: None,
                              MixedHistory(), clock=lambda: NOW, execute_due=False)
    assert manual.started_at > scheduled.started_at
    assert tick.decisions[0].next_expected_at == scheduled.started_at + timedelta(seconds=600)
    assert tick.decisions[0].state is SchedulerState.DUE
