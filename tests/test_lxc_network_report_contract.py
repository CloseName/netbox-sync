"""Golden precheck output captured before extracting the LXC reporter."""
from pathlib import Path
import pytest
from tests.test_lxc_network_preflight_contract import _two_containers
from tests.test_esxi_network_bootstrap import _network_records
from netbox_sync.interface_display import interface_display_name
from netbox_sync.netbox_lxc_network_apply import apply_lxc_networks

CASES = {
    'create': (1, 0, 0, 1, 0, 1, 0, 1),
    'match': (0, 0, 1, 0, 1, 0, 1, 1),
    'update': (0, 1, 0, 0, 1, 0, 1, 1),
    'existing_primary': (0, 0, 1, 0, 1, 0, 1, 1),
    'no_addresses': (1, 0, 0, 0, 0, 0, 0, 0),
    'ipv6_only': (1, 0, 0, 1, 0, 1, 0, 0),
    'mixed': (1, 1, 0, 1, 1, 1, 1, 2),
    'empty': (0, 0, 0, 0, 0, 0, 0, 0),
}
KEYS = ('interface_create', 'interface_update', 'interface_skip', 'mac_create',
        'mac_match', 'ip_create', 'ip_match', 'primary_candidates')


@pytest.mark.parametrize('confirmed', [False, True])
@pytest.mark.parametrize('scenario', CASES)
def test_lxc_precheck_output_and_counters(fake_netbox, capsys, scenario, confirmed):
    target, hosts, records, vm, _ = _two_containers(fake_netbox)
    if scenario != 'mixed':
        hosts[0].containers = [vm]
    nic = vm.interfaces[0]
    if scenario in ('match', 'update', 'existing_primary', 'mixed'):
        interface, _, _ = _network_records(fake_netbox, records[0], vm)
        interface.name = interface_display_name(vm, nic)
        if scenario in ('update', 'mixed'):
            interface.enabled = False
        if scenario == 'existing_primary':
            records[0].primary_ip4 = 999
    if scenario == 'no_addresses':
        nic.mac_address = None
        nic.ip_addresses = []
    elif scenario == 'ipv6_only':
        nic.ip_addresses = ['2001:db8::1/64']
        nic.vlan_id = 0
    elif scenario == 'empty':
        hosts = []
    capsys.readouterr()
    apply_lxc_networks(fake_netbox, hosts, target, confirmed=confirmed)
    output = capsys.readouterr().out
    report, marker, suffix = output.partition('PRECHECK PASSED\n')
    assert marker
    report += marker
    snapshot = Path(__file__).parent / 'fixtures' / 'lxc_network_reports' / (scenario + '.txt')
    assert report == snapshot.read_text(encoding='utf-8')
    summary = report.split('LXC NETWORK PRECHECK SUMMARY\n', 1)[1].split('\n\n', 1)[0]
    assert summary == '\n'.join(f'  {key}={value}' for key, value in zip(KEYS, CASES[scenario]))
    if not confirmed:
        assert suffix == ('APPLY_CONFIRM=LXC_NETWORK_WRITE is not set.\n'
                          'No changes were written to NetBox.\n')
        assert fake_netbox.mutations == []
    else:
        assert suffix.startswith('\n=== LXC NETWORK APPLY ===\n')
        assert 'LXC NETWORK APPLY SUMMARY' in suffix
