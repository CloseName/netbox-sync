"""Host write order, replay and post-preflight conflict contracts."""
import json
from pathlib import Path
import pytest
from tests.fakes import FakeRecord
from tests.fakes.netbox import FakeEndpoint
from tests.test_host_apply_preflight_contract import prepared
from netbox_sync.netbox_apply import apply_hosts, HostApplyError


@pytest.mark.parametrize('failure_at', range(1, 5))
def test_failure_stops_remaining_writes(fake_netbox, monkeypatch, capsys, failure_at):
    config, hosts = prepared(fake_netbox)
    hosts = hosts[:1]
    hosts[0].hardware_identity['observed_at'] = '2026-01-01T00:00:00+00:00'
    attempts = []
    failure = RuntimeError('injected write failure')
    def guard(original, obj, *args, **kwargs):
        attempts.append(1)
        if len(attempts) == failure_at:
            raise failure
        return original(obj, *args, **kwargs)
    create, update = FakeEndpoint.create, FakeRecord.update
    monkeypatch.setattr(FakeEndpoint, 'create', lambda self, **kw: guard(create, self, **kw))
    monkeypatch.setattr(FakeRecord, 'update', lambda self, changes: guard(update, self, changes))
    with pytest.raises(RuntimeError) as caught:
        apply_hosts(fake_netbox, hosts, config, confirmed=True)
    assert caught.value is failure
    assert len(attempts) == failure_at
    expected = [('create', 'dcim.devices'), ('create', 'dcim.interfaces'),
                ('create', 'ipam.ip_addresses'), ('update', 'dcim.devices')]
    assert [(m[0], m[1]) for m in fake_netbox.mutations] == expected[:failure_at - 1]
    assert 'APPLY SUMMARY' not in capsys.readouterr().out


@pytest.mark.parametrize('scenario', ['create', 'reuse', 'network_disabled'])
def test_payloads_output_and_replay(fake_netbox, capsys, scenario):
    config, hosts = prepared(fake_netbox)
    hosts = hosts[:1]
    hosts[0].hardware_identity['observed_at'] = '2026-01-01T00:00:00+00:00'
    if scenario == 'reuse':
        fake_netbox.ipam.ip_addresses.add(FakeRecord(id=801, address='10.20.30.10/24',
            assigned_object_type=None, assigned_object_id=None))
    capsys.readouterr()
    apply_hosts(fake_netbox, hosts, config, confirmed=True, host_networking=scenario != 'network_disabled')
    output = capsys.readouterr().out.split('=== HOST APPLY ===\n', 1)[1]
    actual = {'mutations': json.loads(json.dumps(fake_netbox.mutations)), 'output': output}
    snapshot = Path(__file__).parent / 'fixtures' / 'host_apply_writes' / (scenario + '.json')
    assert actual == json.loads(snapshot.read_text(encoding='utf-8'))
    fake_netbox.clear_mutations()
    apply_hosts(fake_netbox, hosts, config, confirmed=True, host_networking=scenario != 'network_disabled')
    assert fake_netbox.mutations == []


@pytest.mark.parametrize('conflict', ['duplicate', 'assignment'])
def test_changed_ip_after_preflight_stops_writes(fake_netbox, monkeypatch, capsys, conflict):
    config, hosts = prepared(fake_netbox)
    endpoint = fake_netbox.ipam.ip_addresses
    original = endpoint.filter
    calls = []
    def read(**kwargs):
        calls.append(1)
        if len(calls) == 2:
            for identity in ([801, 802] if conflict == 'duplicate' else [801]):
                endpoint.add(FakeRecord(id=identity, address='10.20.30.10/24',
                    assigned_object_type='dcim.interface', assigned_object_id=999))
        return original(**kwargs)
    monkeypatch.setattr(endpoint, 'filter', read)
    message = 'IP conflict appeared' if conflict == 'duplicate' else 'IP assignment changed'
    with pytest.raises(HostApplyError, match=message):
        apply_hosts(fake_netbox, hosts[:1], config, confirmed=True)
    assert [(m[0], m[1]) for m in fake_netbox.mutations] == [('create', 'dcim.devices'), ('create', 'dcim.interfaces')]
    assert 'APPLY SUMMARY' not in capsys.readouterr().out
