"""Proxmox adapter ordering, credential selection and failure propagation."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import netbox_sync as runtime
from tests.sample_data import sample_source_config


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('failure_at', [None, 'credentials', 'connect', 'tls', 'discover', 'select'])
def test_proxmox_connection_discovery_contract(monkeypatch, legacy, failure_at):
    source = sample_source_config()
    events = []
    failure = RuntimeError('fixture failure')
    credentials = SimpleNamespace(username='sync@pve', token_id='sync@pve!sync', token_secret='fixture-secret')
    api, hosts, selected, result = object(), [], [], object()
    def step(name, value):
        events.append(name)
        if name == failure_at:
            raise failure
        return value
    resolver = Mock()
    resolver.resolve_credentials.side_effect = lambda value: step('credentials', credentials)
    chosen, unused = Mock(return_value=resolver), Mock()
    monkeypatch.setattr(runtime, 'LegacyFileSecretResolver' if legacy else 'FileSecretResolver', chosen)
    monkeypatch.setattr(runtime, 'FileSecretResolver' if legacy else 'LegacyFileSecretResolver', unused)
    connect = Mock(side_effect=lambda **kwargs: step('connect', api))
    tls = Mock(side_effect=lambda *args: step('tls', None))
    discover = Mock(side_effect=lambda *args: step('discover', hosts))
    select = Mock(side_effect=lambda *args: step('select', selected))
    reconcile = Mock(side_effect=lambda *args, **kwargs: step('reconcile', result))
    monkeypatch.setattr(runtime, 'ProxmoxAPI', connect)
    monkeypatch.setattr(runtime, 'discover_hosts', discover)
    monkeypatch.setattr(runtime, 'execute_discovered_source', reconcile)
    monkeypatch.setattr('netbox_sync.source_tls.configure_proxmox', tls)
    monkeypatch.setattr('netbox_sync.host_primary_ip.select_endpoint', select)
    monkeypatch.setattr(runtime, '_scheduled_stage', lambda name: events.append('stage:' + name))
    order = ['stage:credentials', 'credentials', 'stage:provider', 'connect', 'tls', 'discover', 'select', 'reconcile']
    if failure_at:
        with pytest.raises(RuntimeError) as caught:
            runtime.execute_proxmox_source(source, 'plan', legacy_secrets=legacy)
        assert caught.value is failure
        assert events == order[:order.index(failure_at) + 1]
        reconcile.assert_not_called()
    else:
        assert runtime.execute_proxmox_source(source, 'plan', legacy_secrets=legacy) is result
        assert events == order
        connect.assert_called_once_with(host=source.address, user='sync@pve', token_name='sync',
            token_value='fixture-secret', verify_ssl=source.verify_ssl, port=source.api_port)
        tls.assert_called_once_with(api, source.verify_ssl)
        discover.assert_called_once_with(api, source)
        select.assert_called_once_with(hosts, source)
        reconcile.assert_called_once_with(source, selected, 'plan', pve_api=api)
    chosen.assert_called_once_with()
    unused.assert_not_called()
    resolver.resolve_credentials.assert_called_once_with(source.credentials)
