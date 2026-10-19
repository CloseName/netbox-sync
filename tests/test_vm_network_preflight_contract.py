"""All VMs must pass validation before any network write or report."""
import pytest

from netbox_sync.netbox_vm_network_apply import VMNetworkApplyError, apply_vm_networks
from tests.fakes import FakeRecord
from tests.test_esxi_network_bootstrap import _managed_setup


@pytest.mark.parametrize('confirmed', [False, True])
@pytest.mark.parametrize('conflict', ['duplicate_mac', 'duplicate_ip', 'foreign_mac', 'foreign_ip', 'foreign_primary', 'missing_identity'])
def test_later_vm_conflict_prevents_all_writes(fake_netbox, capsys, confirmed, conflict):
    _, target, hosts, records, _ = _managed_setup(fake_netbox, count=2)
    first, second = hosts[0].virtual_machines
    nic = second.interfaces[0]
    if conflict == 'duplicate_mac':
        nic.mac_address = first.interfaces[0].mac_address
        message = 'Duplicate discovered MACs:'
    elif conflict == 'duplicate_ip':
        nic.ip_addresses = list(first.interfaces[0].ip_addresses)
        message = 'Duplicate discovered IPs:'
    elif conflict == 'foreign_mac':
        fake_netbox.dcim.mac_addresses.add(FakeRecord(
            id=801, mac_address=nic.mac_address,
            assigned_object_type='virtualization.vminterface', assigned_object_id=999))
        message = 'already assigned to another interface'
    elif conflict == 'foreign_ip':
        fake_netbox.ipam.ip_addresses.add(FakeRecord(
            id=802, address=nic.ip_addresses[0],
            assigned_object_type='virtualization.vminterface', assigned_object_id=999))
        message = 'already assigned to virtualization.vminterface:999'
    elif conflict == 'foreign_primary':
        records[1].primary_ip4 = fake_netbox.ipam.ip_addresses.add(FakeRecord(
            id=803, address='198.51.100.1/24',
            assigned_object_type='virtualization.vminterface', assigned_object_id=999))
        message = 'Existing primary IPv4 conflicts on APP-2:'
    else:
        records[1].custom_fields = {}
        message = 'Expected exactly one NetBox VM'
    capsys.readouterr()
    with pytest.raises(VMNetworkApplyError, match=message):
        apply_vm_networks(fake_netbox, hosts, target, confirmed=confirmed)
    assert fake_netbox.mutations == []
    assert capsys.readouterr().out == ''
