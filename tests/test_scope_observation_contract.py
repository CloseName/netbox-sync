"""Read-only scope evidence and VM/LXC conflict annotation contracts."""

from copy import deepcopy
from dataclasses import asdict

import pytest

from netbox_sync.network_scopes import scoped_inventory, NetworkScopeError
from netbox_sync.netbox_vm_interface_metadata import build_nic_custom_fields
from tests.test_network_scopes import fixture


@pytest.mark.parametrize('kind', ['vm', 'lxc'])
@pytest.mark.parametrize('case', ['exact', 'mask', 'foreign', 'old_scope', 'duplicate_mac'])
def test_scope_observations_preserve_records_and_source_inventory(kind, case):
    api, config, hosts = fixture('proxmox')
    guest = (hosts[0].virtual_machines if kind == 'vm' else hosts[0].containers)[0]
    nic = guest.interfaces[0]
    vrf = 10 if kind == 'vm' else 11
    api.virtualization.interfaces.add(
        id=90, name=nic.name, custom_fields=build_nic_custom_fields(guest, nic))
    api.dcim.mac_addresses.add(
        id=100, mac_address=nic.mac_address,
        assigned_object_type='virtualization.vminterface', assigned_object_id=90)
    if case == 'duplicate_mac':
        api.dcim.mac_addresses.add(
            id=101, mac_address=nic.mac_address,
            assigned_object_type='virtualization.vminterface', assigned_object_id=90)
    address = '192.0.2.60/32' if case == 'mask' else '192.0.2.60/24'
    ip = api.ipam.ip_addresses.add(
        id=200, address=address, vrf=999 if case == 'old_scope' else vrf,
        assigned_object_type='virtualization.vminterface',
        assigned_object_id=999 if case == 'foreign' else 90)
    before_hosts = [asdict(host) for host in hosts]
    before_ip = deepcopy(ip.serialize())
    result = scoped_inventory(api, hosts, config)
    observed = (result[0].virtual_machines if kind == 'vm' else result[0].containers)[0].interfaces[0]
    assert observed is not nic and observed.ip_vrf_id == vrf
    assert observed.ip_scope_conflicts == (
        [{'address': address, 'vrf_id': 999 if case == 'old_scope' else vrf, 'netbox_id': 200}]
        if case in ('mask', 'foreign', 'old_scope') else [])
    assert observed.mac_scope_conflicts == (
        [{'netbox_id': 100}, {'netbox_id': 101}] if case == 'duplicate_mac' else [])
    assert [asdict(host) for host in hosts] == before_hosts
    assert ip.serialize() == before_ip and api.mutations == []


@pytest.mark.parametrize('kind', ['vm', 'lxc'])
def test_ambiguous_nic_resets_ip_but_preserves_mac_observations(kind):
    api, config, hosts = fixture('proxmox')
    guest = (hosts[0].virtual_machines if kind == 'vm' else hosts[0].containers)[0]
    nic = guest.interfaces[0]
    nic.ip_scope_conflicts = [{'old': 'ip'}]
    nic.mac_scope_conflicts = [{'old': 'mac'}]
    for identifier in (90, 91):
        api.virtualization.interfaces.add(
            id=identifier, name=nic.name, custom_fields=build_nic_custom_fields(guest, nic))
    result = scoped_inventory(api, hosts, config)
    observed = (result[0].virtual_machines if kind == 'vm' else result[0].containers)[0].interfaces[0]
    assert observed.ip_scope_conflicts == []
    assert observed.mac_scope_conflicts == [{'old': 'mac'}]
    assert nic.ip_scope_conflicts == [{'old': 'ip'}]
    assert api.mutations == []


def test_ip_conflicts_are_deduplicated_and_sorted_by_record_id():
    api, config, hosts = fixture('proxmox')
    for identifier in (300, 100, 200):
        api.ipam.ip_addresses.add(
            id=identifier, address='192.0.2.60/24', vrf=10,
            assigned_object_type=None, assigned_object_id=None)
    result = scoped_inventory(api, hosts, config)
    assert [row['netbox_id'] for row in result[0].virtual_machines[0].interfaces[0].ip_scope_conflicts] == [
        100, 200, 300]
    assert api.mutations == []


@pytest.mark.parametrize('fields', [{}, {'address': 'invalid'}])
def test_invalid_existing_ip_fails_even_with_no_guests(fields):
    api, config, _ = fixture('proxmox')
    api.ipam.ip_addresses.add(id=200, **fields)
    with pytest.raises(NetworkScopeError, match='^Invalid existing IP evidence$'):
        scoped_inventory(api, [], config)
    assert api.mutations == []
