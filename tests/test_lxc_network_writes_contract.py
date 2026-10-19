"""Mutation order, partial failure and replay contracts for LXC network writes."""
import json
from pathlib import Path
import pytest
from tests.fakes import FakeRecord
from tests.fakes.netbox import FakeEndpoint
from tests.test_lxc_network_preflight_contract import _two_containers
from tests.test_esxi_network_bootstrap import _network_records, _manual_primary
from netbox_sync.interface_display import interface_display_name
from netbox_sync.netbox_lxc_network_apply import apply_lxc_networks


@pytest.mark.parametrize('failure_at', range(1, 11))
def test_write_failure_stops_at_original_boundary(fake_netbox, monkeypatch, capsys, failure_at):
    target, hosts, _, _, _ = _two_containers(fake_netbox)
    attempts = []
    failure = RuntimeError('injected write failure')
    def guard(original, instance, *args, **kwargs):
        attempts.append(len(attempts) + 1)
        if len(attempts) == failure_at:
            raise failure
        return original(instance, *args, **kwargs)
    create, update = FakeEndpoint.create, FakeRecord.update
    monkeypatch.setattr(FakeEndpoint, 'create', lambda self, **kw: guard(create, self, **kw))
    monkeypatch.setattr(FakeRecord, 'update', lambda self, changes: guard(update, self, changes))
    with pytest.raises(RuntimeError) as caught:
        apply_lxc_networks(fake_netbox, hosts, target, confirmed=True)
    assert caught.value is failure
    assert len(attempts) == failure_at
    assert len(fake_netbox.mutations) == failure_at - 1
    expected = [('create', 'virtualization.interfaces'), ('create', 'dcim.mac_addresses'),
                ('update', 'virtualization.interfaces'), ('create', 'ipam.ip_addresses'),
                ('update', 'virtualization.virtual_machines')] * 2
    assert [(m[0], m[1]) for m in fake_netbox.mutations] == expected[:failure_at - 1]
    output = capsys.readouterr().out
    assert 'PRECHECK PASSED' in output
    assert 'LXC NETWORK APPLY SUMMARY' not in output


@pytest.mark.parametrize('scenario', ['create', 'reuse', 'existing_primary'])
def test_write_payloads_output_and_replay(fake_netbox, capsys, scenario):
    target, hosts, records, vm, _ = _two_containers(fake_netbox)
    hosts[0].containers = [vm]
    nic = vm.interfaces[0]
    nic.ip_vrf_id = 42
    if scenario == 'reuse':
        fake_netbox.dcim.mac_addresses.add(FakeRecord(id=801, mac_address=nic.mac_address,
            assigned_object_type=None, assigned_object_id=None))
        fake_netbox.ipam.ip_addresses.add(FakeRecord(id=802, address=nic.ip_addresses[0], vrf=42,
            assigned_object_type=None, assigned_object_id=None))
    elif scenario == 'existing_primary':
        interface, _, ip = _network_records(fake_netbox, records[0], vm)
        ip.vrf = 42
        interface.name = interface_display_name(vm, nic)
        interface.enabled = False
        _manual_primary(fake_netbox, records[0])
    capsys.readouterr()
    apply_lxc_networks(fake_netbox, hosts, target, confirmed=True)
    output = capsys.readouterr().out.split('=== LXC NETWORK APPLY ===\n', 1)[1]
    actual = {'mutations': json.loads(json.dumps(fake_netbox.mutations)), 'output': output}
    snapshot = Path(__file__).parent / 'fixtures' / 'lxc_network_writes' / (scenario + '.json')
    assert actual == json.loads(snapshot.read_text(encoding='utf-8'))
    if scenario == 'existing_primary':
        assert records[0].primary_ip4 == ip.id
        assert fake_netbox.ipam.ip_addresses.get(id=192) is not None
    fake_netbox.clear_mutations()
    apply_lxc_networks(fake_netbox, hosts, target, confirmed=True)
    assert fake_netbox.mutations == []
