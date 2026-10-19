"""Exact final summary output and accumulated counters through the planner."""
import pytest
from tests.test_esxi_network_bootstrap import _managed_setup, _network_records
from netbox_sync.netbox_vm_network_planner import plan_vm_networks

KEYS = ('vm_match', 'vm_blocked', 'interface_create', 'interface_match',
        'interface_conflict', 'mac_create', 'mac_match', 'mac_conflict',
        'ip_create', 'ip_match', 'ip_conflict', 'primary_set', 'warnings')
CASES = {
    'empty': (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    'create': (1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 2),
    'match': (1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 2),
    'blocked': (0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    'mixed': (1, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 2),
}


@pytest.mark.parametrize('scenario', CASES)
def test_exact_final_summary(fake_netbox, capsys, scenario):
    cluster, target, hosts, records, _ = _managed_setup(fake_netbox, count=2 if scenario == 'mixed' else 1)
    if scenario == 'empty':
        hosts[0].virtual_machines = []
    elif scenario in ('blocked', 'mixed'):
        records[-1].custom_fields = {}
    elif scenario == 'match':
        interface, _, _ = _network_records(fake_netbox, records[0], hosts[0].virtual_machines[0])
        interface.name = 'VM Network'
    capsys.readouterr()
    plan_vm_networks(fake_netbox, hosts[0], cluster, fake_netbox.dcim.sites.get(slug=target.site_slug))
    output = capsys.readouterr().out
    heading = '\n    VM NETWORK PLAN SUMMARY\n'
    assert output.count(heading) == 1
    expected = heading + ''.join(f'      {key}={value}\n' for key, value in zip(KEYS, CASES[scenario]))
    assert output[output.index(heading):] == expected
    assert fake_netbox.mutations == []
