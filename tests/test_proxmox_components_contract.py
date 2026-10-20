"""Provider-specific network and disk conversion baselines."""
from dataclasses import asdict
import json
from pathlib import Path
import pytest

from netbox_sync.proxmox_discovery import discover_hosts
from tests.fakes import FakeProxmox
from tests.sample_data import proxmox_responses, sample_source_config


def discover_scenario(scenario):
    data = proxmox_responses(agent_available=scenario != 'no-agent')
    qemu = data[('nodes', 'node-a', 'qemu', 100, 'config')]
    lxc = data[('nodes', 'node-a', 'lxc', 100, 'config')]
    if scenario == 'disks':
        qemu.update({'ide2': 'local:iso/installer.iso,media=cdrom', 'sata2': 'none',
                     'scsi1': 'other:disk-1,size=1.5G', 'virtio2': 'unknown,size=bad', 'scsihw': 'virtio-scsi-pci'})
        lxc.update({'mp1': 'other:disk-1,mp=/data,size=1.5G', 'mp2': '/srv/local,mp=/local'})
    elif scenario == 'networks':
        qemu.update({'net1': 'e1000=AA:BB:CC:DD:EE:11,bridge=vmbr1,tag=bad',
                     'net2': '', 'net3': 'bridge=vmbr2', 'netx': 'ignored'})
        lxc.update({'net1': 'name=eth1,ip=dhcp,tag=bad', 'net2': None,
                    'net3': 'ip=manual', 'net4': 'ip=2001:db8::1/64', 'netx': 'ignored'})
    elif scenario == 'agent-addresses':
        data[('nodes', 'node-a', 'qemu', 100, 'agent', 'network-get-interfaces')] = {'result': [
            {'hardware-address': 'AA:BB:CC:DD:EE:01', 'ip-addresses': [
                {'ip-address': '127.0.0.1', 'prefix': 8}, {'ip-address': '2001:db8::1', 'prefix': 64},
                {'ip-address': '192.0.2.1'}, {'ip-address': '192.0.2.2', 'prefix': 24}]},
            {'hardware-address': '', 'ip-addresses': []}]}
    host = discover_hosts(FakeProxmox(data), sample_source_config())[0]
    return {'vms': [asdict(vm) for vm in host.virtual_machines],
            'lxc': [asdict(container) for container in host.containers]}


@pytest.mark.parametrize('scenario', ['normal', 'no-agent', 'disks', 'networks', 'agent-addresses'])
def test_normalized_workloads_match_baseline(scenario):
    actual = discover_scenario(scenario)
    fixture = Path(__file__).parent / 'fixtures' / 'proxmox_components' / (scenario+'.json')
    assert actual == json.loads(fixture.read_text(encoding='utf-8'))
    if scenario == 'disks':
        assert [disk['name'] for disk in actual['vms'][0]['disks']] == ['scsi0', 'scsi1', 'virtio2']
        assert len(actual['lxc'][0]['disks']) == 3
    if scenario == 'agent-addresses':
        assert actual['vms'][0]['interfaces'][0]['ip_addresses'] == ['192.0.2.1', '192.0.2.2/24']


def agent_networks(response):
    data = proxmox_responses()
    config = data[('nodes', 'node-a', 'qemu', 100, 'config')]
    for index in range(3):
        config[f'net{index}'] = f'virtio=AA:BB:CC:DD:EE:0{index + 1}'
    data[('nodes', 'node-a', 'qemu', 100, 'agent', 'network-get-interfaces')] = response
    api = FakeProxmox(data)
    host = discover_hosts(api, sample_source_config())[0]
    return [nic.ip_addresses for nic in host.virtual_machines[0].interfaces], host


@pytest.mark.parametrize('broken', [
    None, [None], [{'ip-address': 7}], [{'ip-address': ['invalid']}],
])
def test_agent_error_retains_completed_interfaces_but_not_partial_addresses(broken):
    addresses, host = agent_networks({'result': [
        {'hardware-address': 'aa:bb:cc:dd:ee:01',
         'ip-addresses': [{'ip-address': '192.0.2.1', 'prefix': 24}]},
        {'hardware-address': 'aa:bb:cc:dd:ee:02',
         'ip-addresses': ([{'ip-address': '192.0.2.2'}] + broken) if isinstance(broken, list) else broken},
        {'hardware-address': 'aa:bb:cc:dd:ee:03',
         'ip-addresses': [{'ip-address': '192.0.2.3'}]},
    ]})
    assert addresses == [['192.0.2.1/24'], [], []]
    assert host.containers[0].interfaces  # Agent failure does not suppress LXC discovery.


@pytest.mark.parametrize('response', [None, [], 'invalid', {'result': None}])
def test_invalid_agent_envelope_still_returns_configured_nics(response):
    addresses, _ = agent_networks(response)
    assert addresses == [[], [], []]


def test_duplicate_agent_mac_last_completed_entry_wins():
    addresses, _ = agent_networks({'result': [
        {'hardware-address': 'AA:BB:CC:DD:EE:01', 'ip-addresses': [{'ip-address': '192.0.2.1'}]},
        {'hardware-address': 'aa:bb:cc:dd:ee:01', 'ip-addresses': [{'ip-address': '192.0.2.2'}]},
    ]})
    assert addresses == [['192.0.2.2'], [], []]


def test_bad_later_duplicate_mac_preserves_previous_completed_entry():
    addresses, _ = agent_networks({'result': [
        {'hardware-address': 'AA:BB:CC:DD:EE:01', 'ip-addresses': [{'ip-address': '192.0.2.1'}]},
        {'hardware-address': 'aa:bb:cc:dd:ee:01', 'ip-addresses': [None]},
    ]})
    assert addresses == [['192.0.2.1'], [], []]


def test_agent_filter_keeps_historical_prefix_and_address_semantics():
    addresses, _ = agent_networks({'result': [
        None, 'ignored',
        {'hardware-address': '', 'ip-addresses': [None]},
        {'hardware-address': 'AA:BB:CC:DD:EE:01', 'ip-addresses': [
            {}, {'ip-address': '127.0.0.1'}, {'ip-address': '2001:db8::1'},
            {'ip-address': '169.254.1.1', 'prefix': 0},
            {'ip-address': 'not-an-ip', 'prefix': 'bad'},
            {'ip-address': '192.0.2.1', 'prefix': None},
        ]},
    ]})
    assert addresses == [['169.254.1.1/0', 'not-an-ip/bad', '192.0.2.1'], [], []]
