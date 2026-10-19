"""Golden precheck output captured before extracting the VM reporter."""
from pathlib import Path
import pytest
from tests.test_esxi_network_bootstrap import _managed_setup, _network_records, _manual_primary
from netbox_sync.netbox_vm_network_apply import apply_vm_networks

CASES = {
    'create': (1, 0, 0, 1, 0, 1, 0, 1, 0, 0),
    'match': (0, 0, 1, 0, 1, 0, 1, 0, 1, 0),
    'update': (0, 1, 0, 0, 1, 0, 1, 0, 1, 0),
    'manual_primary': (0, 0, 1, 0, 1, 0, 1, 0, 0, 1),
    'no_addresses': (1, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    'ipv6_only': (1, 0, 0, 1, 0, 1, 0, 0, 0, 0),
    'mixed': (1, 1, 0, 1, 1, 1, 1, 1, 1, 0),
    'empty': (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
}
KEYS = ('interface_create', 'interface_update', 'interface_skip', 'mac_create',
        'mac_match', 'ip_create', 'ip_match', 'primary_set', 'primary_match',
        'primary_preserve_manual')


@pytest.mark.parametrize('confirmed', [False, True])
@pytest.mark.parametrize('scenario', CASES)
def test_vm_precheck_output_and_counters(fake_netbox, capsys, scenario, confirmed):
    _, target, hosts, records, _ = _managed_setup(fake_netbox, count=2 if scenario == 'mixed' else 1)
    vm = hosts[0].virtual_machines[0]
    nic = vm.interfaces[0]
    if scenario in ('match', 'update', 'manual_primary', 'mixed'):
        interface, _, _ = _network_records(fake_netbox, records[0], vm)
        interface.name = 'VM Network'
        if scenario in ('update', 'mixed'):
            interface.enabled = False
        if scenario == 'manual_primary':
            _manual_primary(fake_netbox, records[0])
    if scenario == 'no_addresses':
        nic.mac_address = None
        nic.ip_addresses = []
    elif scenario == 'ipv6_only':
        nic.ip_addresses = ['2001:db8::1/64']
        nic.vlan_id = 0
    elif scenario == 'empty':
        hosts = []
    capsys.readouterr()
    apply_vm_networks(fake_netbox, hosts, target, confirmed=confirmed)
    output = capsys.readouterr().out
    report, marker, suffix = output.partition('PRECHECK PASSED\n')
    assert marker
    report += marker
    snapshot = Path(__file__).parent / 'fixtures' / 'vm_network_reports' / (scenario + '.txt')
    assert report == snapshot.read_text(encoding='utf-8')
    summary = report.split('PRECHECK SUMMARY\n', 1)[1].split('\n\n', 1)[0]
    assert summary == '\n'.join(f'  {key}={value}' for key, value in zip(KEYS, CASES[scenario]))
    if not confirmed:
        assert suffix == ('APPLY_CONFIRM=VM_NETWORK_WRITE is not set.\n'
                          'No changes were written to NetBox.\n')
        assert fake_netbox.mutations == []
    else:
        assert suffix.startswith('\n=== VM NETWORK APPLY ===\n')
        assert 'VM NETWORK APPLY SUMMARY' in suffix
