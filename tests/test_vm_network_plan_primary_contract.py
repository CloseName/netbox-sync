"""Legacy primary IPv4 planning policy, distinct from write preflight."""
import pytest
from tests.fakes import FakeRecord
from tests.test_esxi_network_bootstrap import _managed_setup
from netbox_sync.netbox_vm_network_planner import plan_vm_networks


@pytest.mark.parametrize('scenario', ['none', 'ipv6', 'set', 'keep', 'replace', 'missing_record',
                                     'empty_record', 'duplicate', 'ambiguous', 'mask_change', 'invalid_current'])
def test_primary_output_counter_and_no_writes(fake_netbox, capsys, scenario):
    cluster, target, hosts, records, _ = _managed_setup(fake_netbox)
    nic = hosts[0].virtual_machines[0].interfaces[0]
    candidate = nic.ip_addresses[0]
    expected = f'      SET PRIMARY IPv4 {candidate}'
    count = 1
    if scenario in ('none', 'ipv6'):
        nic.ip_addresses = [] if scenario == 'none' else ['2001:db8::1/64']
        expected = '      PRIMARY IPv4 action=unchanged reason=no-discovered-address'
        count = 0
    elif scenario == 'duplicate':
        nic.ip_addresses = [candidate, candidate]
    elif scenario == 'ambiguous':
        nic.ip_addresses = ['198.51.100.2/24', candidate, '198.51.100.2/24']
        expected = '      PRIMARY IPv4 action=unchanged reason=ambiguous candidates=192.0.2.51/24,198.51.100.2/24'
        count = 0
    elif scenario == 'missing_record':
        records[0].primary_ip4 = 999
    elif scenario in ('keep', 'replace', 'empty_record', 'mask_change', 'invalid_current'):
        address = {'keep': candidate, 'replace': '198.51.100.9/24', 'empty_record': None,
                   'mask_change': '192.0.2.51/32', 'invalid_current': 'invalid'}[scenario]
        records[0].primary_ip4 = fake_netbox.ipam.ip_addresses.add(FakeRecord(
            id=801, address=address, assigned_object_type='virtualization.vminterface', assigned_object_id=999))
        if scenario == 'keep':
            expected = f'      KEEP PRIMARY IPv4 {candidate}'
            count = 0
    before = records[0].serialize()
    capsys.readouterr()
    site = fake_netbox.dcim.sites.get(slug=target.site_slug)
    if scenario == 'invalid_current':
        with pytest.raises(ValueError):
            plan_vm_networks(fake_netbox, hosts[0], cluster, site)
        output = capsys.readouterr().out
        assert 'VM NETWORK PLAN SUMMARY' not in output
        assert 'PRIMARY IPv4' not in output
    else:
        plan_vm_networks(fake_netbox, hosts[0], cluster, site)
        output = capsys.readouterr().out
        assert [line for line in output.splitlines() if 'PRIMARY IPv4' in line] == [expected]
        assert f'      primary_set={count}' in output.splitlines()
        if scenario == 'keep':
            assert 'CONFLICT IP' in output
    assert records[0].serialize() == before
    assert fake_netbox.mutations == []
