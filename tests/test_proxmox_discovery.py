"""Characterize the current normalized Proxmox discovery output."""

from copy import deepcopy

import pytest

from netbox_sync.proxmox_discovery import discover_hosts

from tests.fakes import FakeProxmox
from tests.sample_data import (
    proxmox_responses,
    sample_source_config,
)


def test_discovers_host_qemu_lxc_storage_disks_and_networks():
    hosts = discover_hosts(
        FakeProxmox(proxmox_responses()),
        sample_source_config(),
    )

    assert len(hosts) == 1
    host = hosts[0]

    assert host.source == 'proxmox'
    assert host.source_id == 'node-a'
    assert host.normalized_name == 'NODE-A'
    assert host.management_ip == '10.20.30.10'
    assert host.hypervisor_version == '8.3.2'
    assert host.cpu.cores == 8
    assert host.cpu.logical_cpus == 16
    assert host.memory_bytes == 32 * 1024**3

    assert host.disks == []
    assert len(host.storages) == 1
    assert host.storages[0].name == 'local-lvm'

    assert len(host.interfaces) == 1
    host_nic = host.interfaces[0]
    assert host_nic.name == 'vmbr0'
    assert host_nic.addresses == ['10.20.30.10/24']
    assert host_nic.bridge_ports == ['eno1', 'eno2']
    assert host_nic.vlan_aware is True

    assert len(host.virtual_machines) == 1
    vm = host.virtual_machines[0]
    assert vm.vmid == 100
    assert vm.source_id == 'proxmox:node-a:100'
    assert vm.vcpus == 4
    assert vm.memory_bytes == 4096 * 1024**2
    assert vm.autostart is True
    assert len(vm.disks) == 1
    assert vm.disks[0].name == 'scsi0'
    assert vm.disks[0].storage == 'local-lvm'
    assert vm.disks[0].size_bytes == 32 * 1024**3
    assert len(vm.interfaces) == 1
    assert vm.interfaces[0].mac_address == 'AA:BB:CC:DD:EE:01'
    assert vm.interfaces[0].external_id == 'net0'
    assert vm.interfaces[0].vlan_id == 120
    assert vm.interfaces[0].ip_addresses == ['10.20.30.40/24']

    assert len(host.containers) == 1
    container = host.containers[0]
    assert container.vmid == 100
    assert container.source_id == 'proxmox:node-a:lxc:100'
    assert container.architecture == 'amd64'
    assert container.os_type == 'debian'
    assert container.unprivileged is True
    assert container.disks[0].size_bytes == 8 * 1024**3
    assert container.interfaces[0].name == 'eth0'
    assert container.interfaces[0].external_id == 'net0'
    assert container.interfaces[0].mac_address == 'AA:BB:CC:DD:EE:02'
    assert container.interfaces[0].ip_addresses == ['10.20.30.50/24']


def test_qemu_agent_unavailable_retains_nic_and_omits_ip_addresses():
    hosts = discover_hosts(
        FakeProxmox(
            proxmox_responses(agent_available=False)
        ),
        sample_source_config(),
    )

    vm = hosts[0].virtual_machines[0]

    assert len(vm.interfaces) == 1
    assert vm.interfaces[0].mac_address == 'AA:BB:CC:DD:EE:01'
    assert vm.interfaces[0].ip_addresses == []


def test_malformed_agent_response_is_isolated_from_vm_discovery():
    responses = proxmox_responses()
    responses[('nodes', 'node-a', 'qemu', 100, 'agent',
               'network-get-interfaces')] = {'result': [None, 'bad-entry']}

    vm = discover_hosts(
        FakeProxmox(responses), sample_source_config(),
    )[0].virtual_machines[0]

    assert vm.vmid == 100
    assert vm.interfaces[0].ip_addresses == []


def test_unknown_and_suspended_workload_statuses_are_bounded():
    responses = proxmox_responses()
    responses[('nodes', 'node-a', 'qemu')][0]['status'] = 'future-state'
    responses[('nodes', 'node-a', 'lxc')][0]['status'] = 'suspended'

    host = discover_hosts(FakeProxmox(responses), sample_source_config())[0]

    assert host.virtual_machines[0].status == 'stopped'
    assert host.containers[0].status == 'paused'


@pytest.mark.parametrize('value', (1, '1', True, 'true', 'on'))
def test_onboot_equivalent_true_values_are_normalized(value):
    responses = proxmox_responses()
    responses[('nodes', 'node-a', 'qemu', 100, 'config')]['onboot'] = value
    responses[('nodes', 'node-a', 'lxc', 100, 'config')]['onboot'] = value

    host = discover_hosts(FakeProxmox(responses), sample_source_config())[0]

    assert host.virtual_machines[0].autostart is True
    assert host.containers[0].autostart is True


def test_bad_qemu_vmid_is_isolated_while_lxc_remains(monkeypatch):
    responses = proxmox_responses()
    responses[('nodes', 'node-a', 'qemu')][0]['vmid'] = '../../100'
    warnings = []
    monkeypatch.setattr(
        'netbox_sync.proxmox_discovery.LOGGER.warning',
        lambda message, kind, **_kwargs: warnings.append(message % kind),
    )

    host = discover_hosts(FakeProxmox(responses), sample_source_config())[0]

    assert host.virtual_machines == []
    assert [item.vmid for item in host.containers] == [100]
    assert warnings == ['Ignoring malformed Proxmox QEMU VM during discovery']


def test_bad_lxc_resources_are_isolated_while_qemu_remains(monkeypatch):
    responses = deepcopy(proxmox_responses())
    responses[('nodes', 'node-a', 'lxc', 100, 'config')]['memory'] = 'invalid'
    warnings = []
    monkeypatch.setattr(
        'netbox_sync.proxmox_discovery.LOGGER.warning',
        lambda message, kind, **_kwargs: warnings.append(message % kind),
    )

    host = discover_hosts(FakeProxmox(responses), sample_source_config())[0]

    assert [item.vmid for item in host.virtual_machines] == [100]
    assert host.containers == []
    assert warnings == [
        'Ignoring malformed Proxmox LXC container during discovery',
    ]


@pytest.mark.parametrize('value', (None, '', '0', 0, -1, '-1', '1.0', True))
@pytest.mark.parametrize('kind', ('qemu', 'lxc'))
def test_invalid_vmid_is_rejected_without_ambiguous_coercion(value, kind):
    responses = proxmox_responses()
    responses[('nodes', 'node-a', kind)][0]['vmid'] = value

    host = discover_hosts(FakeProxmox(responses), sample_source_config())[0]

    discovered = host.virtual_machines if kind == 'qemu' else host.containers
    assert discovered == []


def test_malformed_guest_ip_is_ignored_without_losing_vm():
    responses = proxmox_responses()
    responses[('nodes', 'node-a', 'qemu', 100, 'agent',
               'network-get-interfaces')]['result'][0]['ip-addresses'] = [None]

    vm = discover_hosts(
        FakeProxmox(responses), sample_source_config(),
    )[0].virtual_machines[0]

    assert vm.vmid == 100
    assert vm.interfaces[0].ip_addresses == []


def test_malformed_nics_are_skipped_while_valid_sibling_nics_remain():
    responses = proxmox_responses()
    qemu_config = responses[('nodes', 'node-a', 'qemu', 100, 'config')]
    lxc_config = responses[('nodes', 'node-a', 'lxc', 100, 'config')]
    qemu_config['net0'] = None
    qemu_config['net1'] = 'virtio=AA:BB:CC:DD:EE:11,bridge=vmbr1,tag=121'
    lxc_config['net0'] = {'unexpected': 'object'}
    lxc_config['net1'] = (
        'name=eth1,bridge=vmbr1,hwaddr=AA:BB:CC:DD:EE:12,tag=121'
    )

    host = discover_hosts(FakeProxmox(responses), sample_source_config())[0]

    assert [nic.external_id for nic in host.virtual_machines[0].interfaces] == [
        'net1',
    ]
    assert [nic.external_id for nic in host.containers[0].interfaces] == [
        'net1',
    ]


def test_v1_identity_changes_after_live_migration_current_bug():
    before = discover_hosts(
        FakeProxmox(proxmox_responses('node-a')),
        sample_source_config(),
    )[0].virtual_machines[0]
    after = discover_hosts(
        FakeProxmox(proxmox_responses('node-b')),
        sample_source_config(),
    )[0].virtual_machines[0]

    # Characterization only: PHASE 2 must reverse this expectation.
    assert before.vmid == after.vmid == 100
    assert before.source_id == 'proxmox:node-a:100'
    assert after.source_id == 'proxmox:node-b:100'
    assert before.source_id != after.source_id


def test_physical_disks_are_never_requested_but_vm_disks_remain():
    responses = {k:v for k,v in proxmox_responses().items() if 'disks' not in k}
    api = FakeProxmox(responses)
    host = discover_hosts(api, sample_source_config())[0]
    assert host.disks == []
    assert host.virtual_machines[0].disks
    assert not any('disks' in path for path, _ in api.calls)
