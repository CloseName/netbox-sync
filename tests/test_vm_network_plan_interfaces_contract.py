"""Interface validation keeps planner conflicts local to each VM."""
from copy import deepcopy
import pytest
from tests.fakes import FakeRecord
from tests.test_esxi_network_bootstrap import _managed_setup, _network_records
from netbox_sync.netbox_vm_network_planner import plan_vm_networks


@pytest.mark.parametrize('scenario', ['create', 'match', 'manual_name', 'duplicate_identity', 'duplicate_desired'])
def test_interface_decisions_and_next_vm(fake_netbox, capsys, scenario):
    cluster, target, hosts, records, _ = _managed_setup(fake_netbox, count=2)
    vm = hosts[0].virtual_machines[0]
    nic = vm.interfaces[0]
    if scenario in ('match', 'duplicate_identity'):
        interface, _, _ = _network_records(fake_netbox, records[0], vm)
        interface.name = 'VM Network'
        if scenario == 'duplicate_identity':
            fake_netbox.virtualization.interfaces.add(FakeRecord(id=99, name='other',
                virtual_machine=records[0], custom_fields=deepcopy(interface.custom_fields)))
    elif scenario == 'manual_name':
        fake_netbox.virtualization.interfaces.add(FakeRecord(id=99, name='VM Network',
            virtual_machine=records[0], custom_fields={}))
    elif scenario == 'duplicate_desired':
        vm.interfaces.append(deepcopy(nic))
    capsys.readouterr()
    plan_vm_networks(fake_netbox, hosts[0], cluster, fake_netbox.dcim.sites.get(slug=target.site_slug))
    output = capsys.readouterr().out
    first, second = output.split('    VM id=11', 1)
    conflict = scenario not in ('create', 'match')
    if conflict:
        assert first.count('CONFLICT INTERFACE') == 1
        assert 'CREATE MAC' not in first
        assert 'PRIMARY IPv4' not in first
    else:
        expected = '      MATCH INTERFACE id=20 name=VM Network' if scenario == 'match' else '      CREATE INTERFACE name=VM Network'
        assert expected in first.splitlines()
    assert 'CREATE INTERFACE name=VM Network' in second
    assert 'CREATE IP address=192.0.2.52/24' in second
    assert f'      interface_conflict={int(conflict)}' in output.splitlines()
    assert f'      interface_match={int(scenario == "match")}' in output.splitlines()
    assert f'      interface_create={2 if scenario == "create" else 1}' in output.splitlines()
    assert fake_netbox.mutations == []
