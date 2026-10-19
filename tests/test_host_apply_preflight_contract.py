"""All-host preflight refusals precede reporting and writes."""
from copy import deepcopy
import pytest
from tests.fakes import FakeRecord, FakeProxmox
from tests.sample_data import sample_source_config, proxmox_responses
from tests.test_host_apply_targets_contract import setup
from netbox_sync.proxmox_discovery import discover_hosts
from netbox_sync.netbox_apply import apply_hosts, HostApplyError


def prepared(api):
    config, _, _, _ = setup(api)
    hosts = discover_hosts(FakeProxmox(proxmox_responses()), sample_source_config())
    first = hosts[0]
    second = deepcopy(first)
    second.source_id = 'second-host'
    second.normalized_name = 'second-host'
    second.original_name = 'second-host'
    return config, [first, second]


@pytest.mark.parametrize('confirmed', [False, True])
@pytest.mark.parametrize('conflict', ['name', 'interfaces', 'management', 'foreign_ip', 'duplicate_ip'])
def test_later_host_refusal_blocks_entire_batch(fake_netbox, capsys, confirmed, conflict):
    config, hosts = prepared(fake_netbox)
    second = hosts[1]
    if conflict == 'name':
        fake_netbox.dcim.devices.add(FakeRecord(id=801, name=second.normalized_name))
        message = 'Device adoption candidate'
    elif conflict == 'interfaces':
        second.interfaces.append(deepcopy(second.interfaces[0]))
        message = 'Duplicate discovered interface'
    elif conflict == 'management':
        second.management_ip = '203.0.113.99'
        message = 'Expected exactly one management'
    else:
        # A unique second-host address makes the first host valid.
        from netbox_sync.discovery import DiscoveredHostInterface
        second.interfaces = [DiscoveredHostInterface(name='mgmt', addresses=['203.0.113.99/24'])]
        second.management_ip = '203.0.113.99'
        for identity in ([801, 802] if conflict == 'duplicate_ip' else [801]):
            fake_netbox.ipam.ip_addresses.add(FakeRecord(id=identity, address='203.0.113.99/24',
                assigned_object_type='dcim.interface', assigned_object_id=999))
        message = 'IP conflict:' if conflict == 'duplicate_ip' else 'already assigned'
    capsys.readouterr()
    with pytest.raises(HostApplyError, match=message):
        apply_hosts(fake_netbox, hosts, config, confirmed=confirmed)
    assert fake_netbox.mutations == []
    assert capsys.readouterr().out == ''


def test_network_disabled_skips_network_validation(fake_netbox, capsys):
    config, hosts = prepared(fake_netbox)
    hosts[1].interfaces.append(deepcopy(hosts[1].interfaces[0]))
    hosts[1].management_ip = '203.0.113.99'
    apply_hosts(fake_netbox, hosts, config, confirmed=False, host_networking=False)
    output = capsys.readouterr().out
    assert 'PRECHECK PASSED' in output
    assert 'management=None:None' in output
    assert fake_netbox.mutations == []
