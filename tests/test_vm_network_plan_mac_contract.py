"""MAC planning contracts exercised through the original full planner."""
import pytest
from tests.fakes import FakeRecord
from tests.test_esxi_network_bootstrap import _managed_setup, _network_records
from netbox_sync.netbox_vm_network_planner import plan_vm_networks


@pytest.mark.parametrize('scenario', ['absent', 'create', 'free', 'owned', 'foreign', 'wrong_type', 'partial', 'duplicate'])
def test_mac_output_counters_and_ip_continuation(fake_netbox, capsys, scenario):
    cluster, target, hosts, records, _ = _managed_setup(fake_netbox)
    vm = hosts[0].virtual_machines[0]
    nic = vm.interfaces[0]
    canonical = nic.mac_address.upper()
    nic.mac_address = '  ' + canonical.lower() + '  '
    expected = ''
    counts = (0, 0, 0)
    if scenario == 'absent':
        nic.mac_address = None
    elif scenario == 'create':
        expected = f'        CREATE MAC {canonical}'
        counts = (1, 0, 0)
    elif scenario == 'owned':
        interface, mac, _ = _network_records(fake_netbox, records[0], vm)
        interface.name = 'VM Network'
        expected = f'        MATCH MAC id={mac.id} {canonical}'
        counts = (0, 1, 0)
    else:
        assigned_type, assigned_id = {
            'free': (None, None), 'foreign': ('virtualization.vminterface', 999),
            'wrong_type': ('dcim.interface', 999), 'partial': (None, 999),
            'duplicate': (None, None),
        }[scenario]
        for identity in ([801, 802] if scenario == 'duplicate' else [801]):
            fake_netbox.dcim.mac_addresses.add(FakeRecord(id=identity, mac_address=canonical.lower(),
                assigned_object_type=assigned_type, assigned_object_id=assigned_id))
        if scenario == 'free':
            expected = f'        MATCH MAC id=801 {canonical}'
            counts = (0, 1, 0)
        elif scenario == 'duplicate':
            expected = f'        CONFLICT MAC {canonical} matches=2'
            counts = (0, 0, 1)
        else:
            expected = f'        CONFLICT MAC id=801 {canonical} assigned={assigned_type}:{assigned_id}'
            counts = (0, 0, 1)
    capsys.readouterr()
    plan_vm_networks(fake_netbox, hosts[0], cluster, fake_netbox.dcim.sites.get(slug=target.site_slug))
    output = capsys.readouterr().out
    lines = output.splitlines()
    assert [line for line in lines if ' MAC ' in line] == ([expected] if expected else [])
    for key, value in zip(('mac_create', 'mac_match', 'mac_conflict'), counts):
        assert f'      {key}={value}' in lines
    ip_line = next(line for line in lines if 'MATCH IP ' in line or 'CREATE IP ' in line)
    if expected:
        assert lines.index(expected) < lines.index(ip_line)
    assert '    VM NETWORK PLAN SUMMARY' in lines
    assert fake_netbox.mutations == []
