"""Mutation order, partial failure and replay contracts for VM network writes."""
import json
from pathlib import Path
import pytest
from tests.fakes import FakeRecord
from tests.fakes.netbox import FakeEndpoint
from tests.test_esxi_network_bootstrap import _managed_setup, _network_records, _manual_primary
from netbox_sync.netbox_vm_network_apply import apply_vm_networks


@pytest.mark.parametrize('failure_at', range(1, 11))
def test_write_failure_stops_at_original_boundary(fake_netbox, monkeypatch, capsys, failure_at):
    _, target, hosts, _, _ = _managed_setup(fake_netbox, count=2)
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
        apply_vm_networks(fake_netbox, hosts, target, confirmed=True)
    assert caught.value is failure
    assert len(attempts) == failure_at
    assert len(fake_netbox.mutations) == failure_at - 1
    expected = [('create', 'virtualization.interfaces'), ('create', 'dcim.mac_addresses'),
                ('update', 'virtualization.interfaces'), ('create', 'ipam.ip_addresses'),
                ('update', 'virtualization.virtual_machines')] * 2
    assert [(m[0], m[1]) for m in fake_netbox.mutations] == expected[:failure_at - 1]
    output = capsys.readouterr().out
    assert 'PRECHECK PASSED' in output
    assert 'VM NETWORK APPLY SUMMARY' not in output


@pytest.mark.parametrize('scenario', ['create', 'reuse', 'manual_primary'])
def test_write_payloads_output_and_replay(fake_netbox, capsys, scenario):
    _, target, hosts, records, _ = _managed_setup(fake_netbox)
    vm = hosts[0].virtual_machines[0]
    nic = vm.interfaces[0]
    nic.ip_vrf_id = 42
    if scenario == 'reuse':
        fake_netbox.dcim.mac_addresses.add(FakeRecord(id=801, mac_address=nic.mac_address,
            assigned_object_type=None, assigned_object_id=None))
        fake_netbox.ipam.ip_addresses.add(FakeRecord(id=802, address=nic.ip_addresses[0], vrf=42,
            assigned_object_type=None, assigned_object_id=None))
    elif scenario == 'manual_primary':
        interface, _, ip = _network_records(fake_netbox, records[0], vm)
        ip.vrf = 42
        interface.name = 'VM Network'
        interface.enabled = False
        _manual_primary(fake_netbox, records[0])
    capsys.readouterr()
    apply_vm_networks(fake_netbox, hosts, target, confirmed=True)
    output = capsys.readouterr().out.split('=== VM NETWORK APPLY ===\n', 1)[1]
    actual = {'mutations': json.loads(json.dumps(fake_netbox.mutations)), 'output': output}
    snapshot = Path(__file__).parent / 'fixtures' / 'vm_network_writes' / (scenario + '.json')
    assert actual == json.loads(snapshot.read_text(encoding='utf-8'))
    if scenario == 'manual_primary':
        assert records[0].primary_ip4.id == 192
    fake_netbox.clear_mutations()
    apply_vm_networks(fake_netbox, hosts, target, confirmed=True)
    assert fake_netbox.mutations == []
