"""Whole-batch LXC validation and provider-specific refusal contracts."""
from copy import deepcopy
import pytest
from tests.fakes import FakeRecord
from tests.test_lxc_network_inventory_contract import _managed_setup
from netbox_sync.netbox_lxc_metadata import build_lxc_custom_fields
from netbox_sync.netbox_vm_interface_metadata import build_nic_custom_fields
from netbox_sync.netbox_lxc_network_apply import apply_lxc_networks, LXCNetworkApplyError


def _two_containers(api):
    cluster, target, hosts, records, _ = _managed_setup(api)
    first = hosts[0].containers[0]
    second = deepcopy(first)
    second.vmid = 999
    second.source_id = 'lxc:999'
    second.original_name = 'second-container'
    second.interfaces[0].mac_address = '02:00:00:00:00:99'
    second.interfaces[0].ip_addresses = ['192.0.2.99/24']
    hosts[0].containers.append(second)
    records.append(api.virtualization.virtual_machines.add(FakeRecord(
        id=81, name=second.original_name, cluster=cluster,
        custom_fields=build_lxc_custom_fields(second))))
    return target, hosts, records, first, second


@pytest.mark.parametrize('confirmed', [False, True])
@pytest.mark.parametrize('conflict', ['duplicate_mac', 'duplicate_ip', 'foreign_mac', 'foreign_ip', 'primary_mac', 'foreign_cluster', 'missing_identity'])
def test_later_container_conflict_prevents_all_writes(fake_netbox, capsys, confirmed, conflict):
    target, hosts, records, first, second = _two_containers(fake_netbox)
    nic = second.interfaces[0]
    if conflict == 'duplicate_mac':
        nic.mac_address = first.interfaces[0].mac_address
        message = 'Duplicate discovered MACs:'
    elif conflict == 'duplicate_ip':
        nic.ip_addresses = list(first.interfaces[0].ip_addresses)
        message = 'Duplicate discovered IPs:'
    elif conflict == 'foreign_mac':
        fake_netbox.dcim.mac_addresses.add(FakeRecord(id=801, mac_address=nic.mac_address,
            assigned_object_type='virtualization.vminterface', assigned_object_id=999))
        message = 'already assigned to virtualization.vminterface:999'
    elif conflict == 'foreign_ip':
        fake_netbox.ipam.ip_addresses.add(FakeRecord(id=802, address=nic.ip_addresses[0],
            assigned_object_type='virtualization.vminterface', assigned_object_id=999))
        message = 'already assigned to virtualization.vminterface:999'
    elif conflict == 'primary_mac':
        fake_netbox.virtualization.interfaces.add(FakeRecord(id=803, name=nic.name,
            virtual_machine=records[1], primary_mac_address=804, enabled=True,
            custom_fields=build_nic_custom_fields(second, nic)))
        message = 'Primary MAC conflict on second-container:'
    elif conflict == 'foreign_cluster':
        records[1].cluster = FakeRecord(id=999)
        message = 'is outside target cluster'
    else:
        records[1].custom_fields = {}
        message = 'Expected exactly one NetBox LXC object'
    capsys.readouterr()
    with pytest.raises(LXCNetworkApplyError, match=message):
        apply_lxc_networks(fake_netbox, hosts, target, confirmed=confirmed)
    assert fake_netbox.mutations == []
    assert capsys.readouterr().out == ''


def test_existing_primary_ipv4_is_not_a_lxc_preflight_refusal(fake_netbox, capsys):
    target, hosts, records, _, _ = _two_containers(fake_netbox)
    records[1].primary_ip4 = 999
    apply_lxc_networks(fake_netbox, hosts, target, confirmed=False)
    assert 'LXC NETWORK APPLY PRECHECK' in capsys.readouterr().out
    assert records[1].primary_ip4 == 999
    assert fake_netbox.mutations == []
