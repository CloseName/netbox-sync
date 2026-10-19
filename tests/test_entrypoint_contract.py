"""Entrypoint contracts with external executors and persistence replaced by fakes."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import netbox_sync as app
import netbox_sync.scheduler_runtime as scheduler
import netbox_sync.source_bootstrap as bootstrap


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for key in ('SYNC_MODE', 'SOURCE_CONFIG_MODE', 'NETBOX_SYNC_RUN_WRITER_DSN',
                'NETBOX_SYNC_REGISTRY_DSN', 'NETBOX_SYNC_REGISTRY_SCHEMA',
                'NETBOX_SYNC_DIAGNOSTICS_STALE_SECONDS'):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize('value,expected', [(None, 'inventory'), (' PLAN ', 'plan'), ('Apply', 'apply')])
def test_sync_mode_normalization(monkeypatch, value, expected):
    if value is not None:
        monkeypatch.setenv('SYNC_MODE', value)
    assert app._get_sync_mode() == expected


@pytest.mark.parametrize('value', ['', 'unknown'])
def test_invalid_mode_exits_before_source_loading(monkeypatch, capsys, value):
    monkeypatch.setenv('SYNC_MODE', value)
    load = Mock()
    monkeypatch.setattr(app, 'load_runtime_source_config', load)
    with pytest.raises(SystemExit) as error:
        app.main()
    assert error.value.code == 2
    assert capsys.readouterr().out == f'Invalid SYNC_MODE="{value}". Allowed values: apply, inventory, plan.\n'
    load.assert_not_called()


@pytest.mark.parametrize('source_mode', ['legacy', 'registry'])
@pytest.mark.parametrize('sync_mode', ['inventory', 'plan', 'apply'])
def test_single_source_dispatch(monkeypatch, capsys, source_mode, sync_mode):
    monkeypatch.setenv('SYNC_MODE', sync_mode)
    monkeypatch.setenv('SOURCE_CONFIG_MODE', source_mode)
    source = object()
    load = Mock(return_value=source)
    legacy = Mock()
    dispatch = Mock()
    factory = Mock(return_value=dispatch)
    monkeypatch.setattr(app, 'load_runtime_source_config', load)
    monkeypatch.setattr(app, 'execute_proxmox_source', legacy)
    monkeypatch.setattr(app, '_source_dispatch', factory)
    assert app.main() is None
    load.assert_called_once_with()
    if source_mode == 'legacy':
        legacy.assert_called_once_with(source, sync_mode, legacy_secrets=True)
        factory.assert_not_called()
    else:
        legacy.assert_not_called()
        factory.assert_called_once_with(sync_mode)
        dispatch.execute.assert_called_once_with(source)
    assert capsys.readouterr().out == f'SYNC_MODE={sync_mode}\n'


@pytest.mark.parametrize('sync_mode', ['inventory', 'plan', 'apply'])
@pytest.mark.parametrize('failed', [False, True])
def test_registry_all_scheduler_contract(monkeypatch, capsys, sync_mode, failed):
    monkeypatch.setenv('SYNC_MODE', sync_mode)
    monkeypatch.setenv('SOURCE_CONFIG_MODE', 'registry-all')
    monkeypatch.setenv('NETBOX_SYNC_RUN_WRITER_DSN', 'writer')
    monkeypatch.setenv('NETBOX_SYNC_REGISTRY_DSN', 'reader')
    monkeypatch.setenv('NETBOX_SYNC_REGISTRY_SCHEMA', 'fixture')
    monkeypatch.setenv('NETBOX_SYNC_DIAGNOSTICS_STALE_SECONDS', '900')
    calls = []
    configs, history, source = object(), object(), object()
    def load():
        calls.append('load')
        return configs
    def dispatch_factory(mode):
        assert mode == sync_mode
        calls.append('dispatch')
        def execute(config):
            assert config is source
            print('executor output must stay hidden')
            return 'executed'
        return SimpleNamespace(execute=execute)
    def repository(dsn, schema):
        assert (dsn, schema) == ('writer' if sync_mode == 'apply' else 'reader', 'fixture')
        calls.append('history')
        return history
    result = SimpleNamespace(results=[], total=0, succeeded=0, failed=0, history_failures=0)
    tick = SimpleNamespace(execution=result, failed=failed)
    def run(config, execute, repo, **kwargs):
        assert config is configs and repo is history
        assert kwargs == {'stale_seconds': 900, 'execute_due': sync_mode == 'apply'}
        calls.append('tick')
        assert execute(source) == 'executed'
        return tick
    monkeypatch.setattr(bootstrap, 'load_scheduler_source_configs', load)
    monkeypatch.setattr(app, '_source_dispatch', dispatch_factory)
    monkeypatch.setattr(app, 'postgres_run_repository', repository)
    monkeypatch.setattr(scheduler, 'run_scheduler_tick', run)
    monkeypatch.setattr(scheduler, 'scheduler_summary_lines', lambda value: ['SCHEDULER SUMMARY'] if value is tick else [])
    if failed:
        with pytest.raises(SystemExit) as error:
            app.main()
        assert error.value.code == 1
    else:
        assert app.main() is None
    assert calls == ['load', 'dispatch', 'history', 'tick']
    assert capsys.readouterr().out == (f'SYNC_MODE={sync_mode}\n\nMULTI-SOURCE SUMMARY\n'
        'total=0\nsucceeded=0\nfailed=0\nhistory_failures=0\nSCHEDULER SUMMARY\n')


def test_source_summary_output(capsys):
    rows = [SimpleNamespace(source_id='one', success=True, history_error_code=None),
            SimpleNamespace(source_id='two', success=False, error_type='Refused', error_summary='safe reason',
                            history_error_code='HISTORY_UNAVAILABLE', history_status=SimpleNamespace(value='failed'))]
    app._print_multi_source_result(SimpleNamespace(results=rows, total=2, succeeded=1, failed=1, history_failures=1))
    assert capsys.readouterr().out == ('SOURCE one SUCCESS\nSOURCE two FAILED Refused: safe reason\n'
        'SOURCE two HISTORY failed HISTORY_UNAVAILABLE\n\nMULTI-SOURCE SUMMARY\n'
        'total=2\nsucceeded=1\nfailed=1\nhistory_failures=1\n')


def test_single_source_failure_propagates(monkeypatch):
    monkeypatch.setenv('SOURCE_CONFIG_MODE', 'legacy')
    failure = RuntimeError('fixture failure')
    monkeypatch.setattr(app, 'load_runtime_source_config', Mock(side_effect=failure))
    execute = Mock()
    monkeypatch.setattr(app, 'execute_proxmox_source', execute)
    with pytest.raises(RuntimeError) as error:
        app.main()
    assert error.value is failure
    execute.assert_not_called()
