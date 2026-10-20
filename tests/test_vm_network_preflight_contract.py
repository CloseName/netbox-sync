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


@pytest.mark.parametrize('confirmed', [False, True])
@pytest.mark.parametrize('earlier', ['duplicate_mac', 'foreign_mac', 'duplicate_ip', 'foreign_ip', 'primary'])
def test_vm_error_precedence_before_batch_duplicates(fake_netbox, capsys, confirmed, earlier):
    """Per-NIC and primary checks precede deferred cross-VM duplicate checks."""
    from netbox_sync.vm_network_preflight import ManagedMACConflict

    _, target, hosts, records, _ = _managed_setup(fake_netbox, count=2)
    first, second = hosts[0].virtual_machines
    nic = second.interfaces[0]
    nic.mac_address = first.interfaces[0].mac_address
    nic.ip_addresses = list(first.interfaces[0].ip_addresses)
    if earlier in ('duplicate_mac', 'foreign_mac'):
        for identifier in ([801, 802] if earlier == 'duplicate_mac' else [801]):
            fake_netbox.dcim.mac_addresses.add(FakeRecord(
                id=identifier, mac_address=nic.mac_address,
                assigned_object_type='virtualization.vminterface', assigned_object_id=999))
        # Competing IP conflict must not replace the structured MAC error.
        fake_netbox.ipam.ip_addresses.add(FakeRecord(
            id=803, address=nic.ip_addresses[0],
            assigned_object_type='virtualization.vminterface', assigned_object_id=999))
        message = ('Duplicate NetBox MAC ' + nic.mac_address.upper()
                   if earlier == 'duplicate_mac'
                   else 'MAC ' + nic.mac_address.upper() + ' already assigned to another interface')
    elif earlier in ('duplicate_ip', 'foreign_ip'):
        for identifier in ([803, 804] if earlier == 'duplicate_ip' else [803]):
            fake_netbox.ipam.ip_addresses.add(FakeRecord(
                id=identifier, address=nic.ip_addresses[0],
                assigned_object_type='virtualization.vminterface', assigned_object_id=999))
        records[0].primary_ip4 = 999
        message = (f'Duplicate NetBox IP {nic.ip_addresses[0]}' if earlier == 'duplicate_ip'
                   else f'IP {nic.ip_addresses[0]} already assigned to virtualization.vminterface:999')
    else:
        records[0].primary_ip4 = 999
        message = None
    capsys.readouterr()
    with pytest.raises(VMNetworkApplyError) as caught:
        apply_vm_networks(fake_netbox, hosts, target, confirmed=confirmed)
    if message is not None:
        assert str(caught.value) == message
    else:
        assert str(caught.value).startswith("Existing primary IPv4 conflicts on APP-1: current=None")
    if earlier in ('duplicate_mac', 'foreign_mac'):
        assert type(caught.value) is ManagedMACConflict
        assert (caught.value.vm_name, caught.value.nic_name, caught.value.mac, caught.value.duplicate) == (
            first.original_name, first.interfaces[0].name, nic.mac_address.upper(), earlier == 'duplicate_mac')
    assert fake_netbox.mutations == []
    assert capsys.readouterr().out == ''


def test_vm_batch_duplicate_mac_precedes_duplicate_ip(fake_netbox, capsys):
    _, target, hosts, _, _ = _managed_setup(fake_netbox, count=2)
    first, second = hosts[0].virtual_machines
    second.interfaces[0].mac_address = first.interfaces[0].mac_address
    second.interfaces[0].ip_addresses = list(first.interfaces[0].ip_addresses)
    capsys.readouterr()
    with pytest.raises(VMNetworkApplyError) as caught:
        apply_vm_networks(fake_netbox, hosts, target, confirmed=True)
    assert str(caught.value) == 'Duplicate discovered MACs: ' + first.interfaces[0].mac_address.upper()
    assert fake_netbox.mutations == []
    assert capsys.readouterr().out == ''
