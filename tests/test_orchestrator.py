"""Multi-source sequencing, dispatch, and failure-isolation tests."""

from dataclasses import replace

from netbox_sync.orchestrator import HistoryStatus, run_sources
from netbox_sync.run_history import RunStatus
from netbox_sync.source_executor import SourceExecutorDispatch

from tests.sample_data import sample_source_config


def source(source_id, source_type='proxmox'):
    """Build a distinct immutable source for orchestration tests."""

    return replace(
        sample_source_config(address=f'{source_id}.test.example'),
        id=source_id,
        source_instance=source_id,
        source_type=source_type,
    )


def test_two_sources_execute_deterministically_with_isolated_instances():
    seen = []
    dispatch = SourceExecutorDispatch({
        'proxmox': lambda config: seen.append(
            (config.id, config.source_instance)
        ),
    })

    result = run_sources(
        (source('pve-b'), source('pve-a')),
        dispatch.execute,
    )

    assert seen == [('pve-a', 'pve-a'), ('pve-b', 'pve-b')]
    assert [item.source_instance for item in result.results] == [
        'pve-a', 'pve-b',
    ]
    assert (result.total, result.succeeded, result.failed) == (2, 2, 0)
    assert result.skipped == 0


def test_first_source_failure_does_not_stop_second():
    seen = []

    def execute(config):
        seen.append(config.id)
        if config.id == 'pve-a':
            raise RuntimeError('first failed')

    result = run_sources((source('pve-a'), source('pve-b')), execute)

    assert seen == ['pve-a', 'pve-b']
    assert [item.success for item in result.results] == [False, True]
    assert (result.succeeded, result.failed) == (1, 1)


def test_second_source_failure_is_reported_separately():
    def execute(config):
        if config.id == 'pve-b':
            raise ValueError('second failed')

    result = run_sources((source('pve-a'), source('pve-b')), execute)

    assert result.results[0].success is True
    assert result.results[1].success is False
    assert result.results[1].error_type == 'ValueError'
    assert result.results[1].error_summary == 'source execution failed'


def test_system_exit_from_one_source_is_isolated():
    seen = []

    def execute(config):
        seen.append(config.id)
        if config.id == 'pve-a':
            raise SystemExit(2)

    result = run_sources((source('pve-a'), source('pve-b')), execute)

    assert seen == ['pve-a', 'pve-b']
    assert result.failed == 1
    assert result.results[0].error_type == 'SystemExit'


def test_unknown_source_type_fails_only_that_source():
    seen = []
    dispatch = SourceExecutorDispatch({
        'proxmox': lambda config: seen.append(config.id),
    })

    result = run_sources(
        (source('future-source', 'esxi'), source('pve-b')),
        dispatch.execute,
    )

    assert seen == ['pve-b']
    assert result.results[0].source_id == 'future-source'
    assert result.results[0].success is False
    assert result.results[0].error_type == 'UnsupportedSourceTypeError'
    assert result.results[1].success is True


def test_run_result_never_contains_exception_or_secret_text():
    secret = 'FAKE_ORCHESTRATOR_SECRET_MUST_NOT_APPEAR'

    def fail(_config):
        raise RuntimeError(f'credential was {secret}')

    result = run_sources((source('pve-a'),), fail)

    assert secret not in repr(result)
    assert 'credential was' not in repr(result)
    assert result.results[0].error_type == 'RuntimeError'
    assert result.results[0].started_at.tzinfo is not None
    assert result.results[0].finished_at.tzinfo is not None


class RunRecorder:
    def __init__(self):
        self.started = []
        self.finished = []

    def scheduled_reconciliation_required(self, source_instance):
        return False

    def start_run(self, source_instance, source_type, trigger, created_by):
        run = type('Run', (), {'run_id': source_instance})()
        self.started.append((source_instance, source_type, trigger.value, created_by))
        return run

    def finish_run(self, run_id, status, **values):
        self.finished.append((run_id, status, values))


class FailingRunRecorder(RunRecorder):
    def __init__(self, start_failure=None, finish_failure=None):
        super().__init__()
        self.start_failure = start_failure
        self.finish_failure = finish_failure

    def start_run(self, source_instance, source_type, trigger, created_by):
        if source_instance == self.start_failure:
            raise RuntimeError('RAW_DATABASE_START_SECRET')
        return super().start_run(source_instance, source_type, trigger, created_by)

    def finish_run(self, run_id, status, **values):
        if run_id == self.finish_failure:
            raise RuntimeError('RAW_DATABASE_FINISH_SECRET')
        return super().finish_run(run_id, status, **values)


def test_scheduled_sources_create_distinct_terminal_history():
    recorder = RunRecorder()
    sources = (source('pve-a'), source('pve-b'))

    def execute(config):
        if config.source_instance == 'pve-b':
            raise RuntimeError('sensitive provider detail')
        return type('Plan', (), {'items': (), 'digest': 'a' * 64,
                                 'planner_version': 'web-5a-1'})()

    result = run_sources(sources, execute, run_repository=recorder)
    assert (result.succeeded, result.failed) == (1, 1)
    assert [item[0] for item in recorder.finished] == ['pve-a', 'pve-b']
    assert recorder.finished[0][1] is RunStatus.SUCCEEDED
    assert recorder.finished[1][1] is RunStatus.FAILED
    assert 'sensitive provider detail' not in str(recorder.finished)


def test_two_successful_scheduled_sources_create_two_independent_runs():
    recorder = RunRecorder()
    result = run_sources(
        (source('pve-a'), source('esxi-b', 'esxi')),
        lambda _config: type('Plan', (), {
            'items': ({'action': 'CREATE'}, {'action': 'NO_CHANGE'}),
            'digest': 'b' * 64, 'planner_version': 'web-5a-1',
        })(),
        run_repository=recorder,
    )
    assert result.succeeded == 2
    assert [item[0] for item in recorder.started] == ['esxi-b', 'pve-a']
    assert [item[0] for item in recorder.finished] == ['esxi-b', 'pve-a']
    assert all(item[1] is RunStatus.SUCCEEDED for item in recorder.finished)
    assert all(item[2]['counts'].create == 1 for item in recorder.finished)


def test_history_start_failure_skips_only_that_source_and_is_safe():
    recorder = FailingRunRecorder(start_failure='pve-a')
    executed = []
    result = run_sources(
        (source('pve-a'), source('pve-b')),
        lambda config: executed.append(config.source_instance),
        run_repository=recorder,
    )
    assert executed == ['pve-b']
    assert [item.success for item in result.results] == [False, True]
    assert result.results[0].history_status is HistoryStatus.START_FAILED
    assert result.results[0].history_error_code == 'RUN_HISTORY_UNAVAILABLE'
    assert result.history_failures == 1
    assert [item[0] for item in recorder.finished] == ['pve-b']
    assert 'RAW_DATABASE_START_SECRET' not in repr(result)


def test_successful_sync_survives_history_finalize_failure_and_continues():
    recorder = FailingRunRecorder(finish_failure='pve-a')
    executed = []
    result = run_sources(
        (source('pve-a'), source('pve-b')),
        lambda config: executed.append(config.source_instance),
        run_repository=recorder,
    )
    assert executed == ['pve-a', 'pve-b']
    assert [item.success for item in result.results] == [True, True]
    assert result.results[0].history_status is HistoryStatus.FINALIZE_FAILED
    assert result.results[0].history_error_code == 'RUN_HISTORY_UNAVAILABLE'
    assert result.results[1].history_status is HistoryStatus.RECORDED
    assert len(recorder.finished) == 1
    assert recorder.finished[0][:2] == ('pve-b', RunStatus.SUCCEEDED)
    assert 'RAW_DATABASE_FINISH_SECRET' not in repr(result)


def test_source_and_history_finalize_failures_are_independent_and_continue():
    recorder = FailingRunRecorder(finish_failure='pve-a')
    executed = []

    def execute(config):
        executed.append(config.source_instance)
        if config.source_instance == 'pve-a':
            raise RuntimeError('RAW_PROVIDER_SECRET')

    result = run_sources((source('pve-a'), source('pve-b')), execute,
                         run_repository=recorder)
    assert executed == ['pve-a', 'pve-b']
    assert [item.success for item in result.results] == [False, True]
    assert result.results[0].error_summary == 'source execution failed'
    assert result.results[0].history_status is HistoryStatus.FINALIZE_FAILED
    assert result.results[1].history_status is HistoryStatus.RECORDED
    assert recorder.finished[0][0] == 'pve-b'
    assert not any(secret in repr(result) for secret in (
        'RAW_DATABASE_FINISH_SECRET', 'RAW_PROVIDER_SECRET'))


def test_second_history_failure_does_not_change_first_terminal_run():
    recorder = FailingRunRecorder(finish_failure='pve-b')
    result = run_sources(
        (source('pve-a'), source('pve-b')),
        lambda _config: None,
        run_repository=recorder,
    )
    assert [item[0] for item in recorder.started] == ['pve-a', 'pve-b']
    assert [item[0] for item in recorder.finished] == ['pve-a']
    assert recorder.finished[0][1] is RunStatus.SUCCEEDED
    assert result.results[0].history_status is HistoryStatus.RECORDED
    assert result.results[1].history_status is HistoryStatus.FINALIZE_FAILED
    assert result.history_failures == 1


def test_uncertain_history_blocks_scheduled_execution_without_provider_calls():
    from netbox_sync.run_history import RunStatus
    recorder=RunRecorder()
    recorder.scheduled_reconciliation_required=lambda _:True
    calls=[]
    result=run_sources((source('pve-a'),),lambda config:calls.append(config),run_repository=recorder)
    assert result.failed==1 and not calls
    assert recorder.finished[0][1] is RunStatus.BLOCKED
    assert recorder.finished[0][2]['error_code']=='PLAN_BLOCKED'
