"""IP/prefix planner output, ownership and continuation contracts."""
from pathlib import Path
import pytest
from tests.fakes import FakeRecord
from tests.test_esxi_network_bootstrap import _managed_setup, _network_records
from netbox_sync.netbox_vm_network_planner import plan_vm_networks

CASES = {
    'create': (1, 0, 0, 1, 1), 'free': (0, 1, 0, 1, 1),
    'owned': (0, 1, 0, 1, 0), 'foreign': (1, 0, 1, 2, 0),
    'duplicate_vrf': (1, 0, 1, 2, 0), 'ignored': (0, 0, 0, 0, 0),
    'ipv6': (1, 0, 0, 1, 0), 'site_prefix': (1, 0, 0, 0, 1),
    'global_prefix': (1, 0, 0, 0, 1), 'foreign_prefix': (1, 0, 0, 1, 1),
    'ambiguous_prefix': (1, 0, 0, 1, 1),
    'conflict_primary': (0, 0, 1, 1, 1),
}


@pytest.mark.parametrize('scenario', CASES)
def test_ip_prefix_output_and_counters(fake_netbox, capsys, scenario):
    cluster, target, hosts, records, _ = _managed_setup(fake_netbox)
    site = fake_netbox.dcim.sites.get(slug=target.site_slug)
    vm = hosts[0].virtual_machines[0]
    nic = vm.interfaces[0]
    nic.vlan_id = None
    address = nic.ip_addresses[0]
    if scenario == 'owned':
        interface, _, _ = _network_records(fake_netbox, records[0], vm)
        interface.name = 'VM Network'
    elif scenario in ('free', 'foreign', 'duplicate_vrf', 'conflict_primary'):
        for identity, vrf in ([(801, None), (802, 42)] if scenario == 'duplicate_vrf' else [(801, None)]):
            foreign = scenario in ('foreign', 'conflict_primary')
            fake_netbox.ipam.ip_addresses.add(FakeRecord(id=identity, address=address, vrf=vrf,
                assigned_object_type='virtualization.vminterface' if foreign else None,
                assigned_object_id=999 if foreign else None))
        if scenario in ('foreign', 'duplicate_vrf'):
            nic.ip_addresses.append('198.51.100.1/24')
    elif scenario == 'ignored':
        nic.ip_addresses = ['invalid', '127.0.0.1/8', '169.254.1.1/16', '224.0.0.1/24', '0.0.0.0/32']
    elif scenario == 'ipv6':
        nic.ip_addresses = ['2001:db8::1/64']
    elif scenario.endswith('_prefix'):
        scopes = {
            'site_prefix': [(None, None), ('dcim.site', site.id)],
            'global_prefix': [(None, None)],
            'foreign_prefix': [('dcim.site', 999)],
            'ambiguous_prefix': [('dcim.site', site.id), ('dcim.site', site.id)],
        }[scenario]
        for identity, (scope_type, scope_id) in enumerate(scopes, 801):
            fake_netbox.ipam.prefixes.add(FakeRecord(id=identity, prefix='192.0.2.0/24',
                scope_type=scope_type, scope_id=scope_id))
    capsys.readouterr()
    plan_vm_networks(fake_netbox, hosts[0], cluster, site)
    output = capsys.readouterr().out
    snapshot = Path(__file__).parent / 'fixtures' / 'vm_network_plan_ip' / (scenario + '.txt')
    assert output == snapshot.read_text(encoding='utf-8')
    for key, count in zip(('ip_create', 'ip_match', 'ip_conflict', 'warnings', 'primary_set'), CASES[scenario]):
        assert f'      {key}={count}' in output.splitlines()
    if scenario in ('foreign', 'duplicate_vrf'):
        assert output.index('CONFLICT IP') < output.index('CREATE IP address=198.51.100.1/24')
    assert fake_netbox.mutations == []
