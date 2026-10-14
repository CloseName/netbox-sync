import importlib.util
from pathlib import Path
from copy import deepcopy

from netbox_sync.proxmox_host_network import snapshot
from netbox_sync.proxmox_discovery import discover_hosts
from netbox_sync.netbox_metadata import build_device_custom_fields
from tests.fakes import FakeProxmox
from tests.sample_data import proxmox_responses, sample_source_config

spec = importlib.util.spec_from_file_location('host_paths', Path(__file__).resolve().parents[1] / 'deploy/netbox_guard/host_network_paths.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
paths = module.paths


def pve(rows):
    return {'proxmox_host_network': snapshot(rows)}


def test_bridge_bond_vlan_paths_are_configuration_not_cables():
    fields = pve([
        {'iface': 'vmbr0', 'type': 'bridge', 'bridge_ports': 'bond0.1608'},
        {'iface': 'bond0.1608', 'type': 'vlan', 'vlan-raw-device': 'bond0', 'vlan-id': 1608},
        {'iface': 'bond0', 'type': 'bond', 'slaves': 'eno2 eno1', 'bond_mode': 'active-backup'},
        {'iface': 'eno1', 'type': 'eth'}, {'iface': 'eno2', 'type': 'eth'},
    ])
    before = deepcopy(fields)
    result = paths(fields, bridge='vmbr0')
    assert result['status'] == 'configured'
    assert result['paths'] == [['vmbr0', 'bond0.1608', 'bond0', 'eno1'], ['vmbr0', 'bond0.1608', 'bond0', 'eno2']]
    assert result['provider_port_confirmed'] is False
    assert fields == before


def test_pending_and_missing_and_cycle_are_incomplete():
    for rows in (
        [{'iface': 'vmbr0', 'type': 'bridge', 'bridge_ports': 'missing'}],
        [{'iface': 'vmbr0', 'type': 'bridge', 'bridge_ports': 'vmbr0'}],
        [{'iface': 'vmbr0', 'type': 'bridge', 'bridge_ports': 'eth0', 'changes': {'bridge_ports': 'eth1'}}, {'iface': 'eth0', 'type': 'eth'}],
        [{'iface': 'vmbr0', 'type': 'OVSBridge', 'ovs_ports': 'eth0'}],
    ):
        result = paths(pve(rows), bridge='vmbr0')
        assert result['status'] == 'incomplete'
        assert result['paths'] == []


def test_duplicate_interface_names_refused():
    assert paths(pve([{'iface': 'eno1', 'type': 'eth'}] * 2), interface='eno1')['status'] == 'ambiguous_names'


def test_vlan_parent_is_not_guessed_from_name():
    fields = pve([{'iface': 'eno1.123', 'type': 'vlan'}, {'iface': 'eno1', 'type': 'eth'}])
    assert paths(fields, interface='eno1.123')['paths'] == []


def test_esxi_standard_and_guest_paths():
    fields = {'esxi_host_network': {'version': 1, 'available': True,
        'physical_nics': [{'name': 'vmnic0'}],
        'switches': [{'name': 'vSwitch0', 'uplinks': ['vmnic0']}],
        'port_groups': [{'name': 'Management', 'switch': 'vSwitch0', 'vlan_id': 0}],
        'vmkernel': [{'name': 'vmk0', 'port_group': 'Management'}]}}
    assert paths(fields, interface='vmk0')['paths'] == [['kernel:vmk0', 'group:Management', 'switch:vSwitch0', 'nic:vmnic0']]
    assert paths(fields, bridge='Management')['status'] == 'configured'
    fields['esxi_host_network']['vmkernel'][0]['distributed_switch_uuid'] = 'dvs'
    assert paths(fields, interface='vmk0')['status'] == 'incomplete'


def test_no_cross_provider_guess():
    fields = pve([])
    fields['esxi_host_network'] = {'version': 1, 'available': True}
    assert paths(fields, interface='eno1')['status'] == 'snapshot_missing_or_ambiguous'


def test_snapshot_is_allowlisted_and_deterministic():
    rows = [{'iface': 'vmbr0', 'type': 'bridge', 'bridge_ports': 'eno2 eno1', 'post-up': 'SECRET', 'comments': 'SECRET'}, {'iface': 'eno1', 'type': 'eth'}]
    assert snapshot(rows) == snapshot(list(reversed(rows)))
    assert 'SECRET' not in str(snapshot(rows))
    assert snapshot([{'iface': 'vmbr0', 'bridge_ports': 'none'}])['interfaces'][0]['bridge_ports'] == []


def test_collected_snapshot_is_projected_without_replacing_other_fields():
    hosts = discover_hosts(FakeProxmox(proxmox_responses()), sample_source_config())
    host = hosts[0]
    assert host.proxmox_host_network['interfaces'][0]['name'] == 'vmbr0'
    fields = build_device_custom_fields(host, {'selectel_summary': 'retained'})
    assert fields['selectel_summary'] == 'retained'
    assert fields['proxmox_host_network'] == host.proxmox_host_network
    assert fields['proxmox_host_network'] is not host.proxmox_host_network
