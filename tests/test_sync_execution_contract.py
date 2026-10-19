"""Shared execution routing and no-write gates, with external clients replaced."""
from unittest.mock import Mock
import pytest
import netbox_sync as runtime
from tests.sample_data import sample_source_config


@pytest.fixture
def pipeline(monkeypatch):
    for key in ('SOURCE_CONFIG_MODE', 'NETBOX_SYNC_NETBOX_CONFIG_FILE', 'APPLY_SCOPE', 'APPLY_CONFIRM'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('NB_API_URL', 'https://fixture.invalid')
    api, objects, hosts = Mock(), {}, []
    connect = Mock(return_value=api)
    secret = Mock(return_value='fixture-token')
    monkeypatch.setattr(runtime.pynetbox, 'api', connect)
    monkeypatch.setattr(runtime, '_read_secret', secret)
    monkeypatch.setattr('netbox_sync.netbox_tls.configure_session', Mock())
    load = Mock(return_value=objects)
    monkeypatch.setattr(runtime, '_load_nb_objects', load)
    stages = Mock()
    monkeypatch.setattr(runtime, '_scheduled_stage', stages)
    return sample_source_config(), hosts, api, objects, connect, secret, load, stages


@pytest.mark.parametrize('scope,executor,confirmation', [
    ('host', 'apply_hosts', 'HOST_WRITE'),
    ('vm', 'apply_virtual_machines', 'VM_WRITE'),
    ('vm-network', 'apply_vm_networks', 'VM_NETWORK_WRITE'),
    ('lxc', 'apply_lxc_containers', 'LXC_WRITE'),
    ('lxc-network', 'apply_lxc_networks', 'LXC_NETWORK_WRITE'),
])
@pytest.mark.parametrize('confirmed', [False, True])
def test_scoped_apply_dispatch(pipeline, monkeypatch, scope, executor, confirmation, confirmed):
    source, hosts, api, _, connect, secret, load, stages = pipeline
    monkeypatch.setenv('APPLY_SCOPE', scope)
    monkeypatch.setenv('APPLY_CONFIRM', confirmation if confirmed else 'WRONG_CONFIRMATION')
    names = ['apply_hosts', 'apply_virtual_machines', 'apply_vm_networks',
             'apply_lxc_containers', 'apply_lxc_networks', 'apply_full_sync']
    executors = {name: Mock() for name in names}
    for name, callback in executors.items():
        monkeypatch.setattr(runtime, name, callback)
    assert runtime.execute_discovered_source(source, hosts, 'apply') is None
    secret.assert_called_once_with('NB_APPLY_API_TOKEN')
    connect.assert_called_once_with(url='https://fixture.invalid', token='fixture-token')
    load.assert_called_once_with(api)
    executors[executor].assert_called_once_with(api, hosts, source.target, confirmed=confirmed)
    for name in names:
        if name != executor:
            executors[name].assert_not_called()
    assert [call.args for call in stages.call_args_list] == [('netbox',), ('legacy_read',), ('apply',)]


@pytest.mark.parametrize('scope', ['', 'unknown'])
def test_invalid_apply_scope_stops_before_credentials_or_connection(pipeline, monkeypatch, scope):
    source, hosts, _, _, connect, secret, load, stages = pipeline
    monkeypatch.setenv('APPLY_SCOPE', scope)
    with pytest.raises(SystemExit, match='No changes were written'):
        runtime.execute_discovered_source(source, hosts, 'apply')
    connect.assert_not_called()
    secret.assert_not_called()
    load.assert_not_called()
    stages.assert_not_called()


@pytest.mark.parametrize('mode', ['inventory', 'plan'])
def test_read_modes_use_read_token(pipeline, monkeypatch, mode):
    source, hosts, api, objects, _, secret, _, stages = pipeline
    inventory, plan = Mock(), Mock()
    monkeypatch.setattr(runtime, '_run_inventory', inventory)
    monkeypatch.setattr(runtime, 'plan_hosts', plan)
    assert runtime.execute_discovered_source(source, hosts, mode) is None
    secret.assert_called_once_with('NB_API_TOKEN')
    if mode == 'inventory':
        inventory.assert_called_once_with(objects, hosts)
        plan.assert_not_called()
    else:
        plan.assert_called_once_with(api, objects, hosts, source.target)
        inventory.assert_not_called()
    assert [call.args for call in stages.call_args_list] == [('netbox',), ('legacy_read',)]
