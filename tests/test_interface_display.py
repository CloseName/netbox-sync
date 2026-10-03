"""Bridge-based display names preserve provider identity and network attachments."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from netbox_sync.interface_display import interface_display_name
from netbox_sync.netbox_vm_interface_metadata import build_nic_custom_fields
from tests.test_vm_name_length import (
    _config, discover_esxi, fake_esxi_service, sample_source_config,
    discover_hosts, FakeProxmox, proxmox_responses, target, netbox_http,
    execute_esxi_runtime, apply_full_sync, build_runtime_plan,
)
from tests.test_esxi_network_bootstrap import (
    _managed_setup, _network_records, apply_vm_networks, VMNetworkApplyError,
)
from tests.fakes import FakeRecord


@pytest.mark.parametrize('provider', ['esxi', 'proxmox'])
def test_rename_keeps_ids_and_attachments_and_replan_is_empty(provider, fake_netbox):
    config = _config() if provider == 'esxi' else sample_source_config()
    hosts = (discover_esxi(fake_esxi_service(), config) if provider == 'esxi'
             else discover_hosts(FakeProxmox(proxmox_responses()), config))
    target(fake_netbox, config)
    guests = [guest for host in hosts for guest in [*host.virtual_machines, *host.containers]]
    expected = {build_nic_custom_fields(g, n)['sync_identities'][0]['external_id']: (g, n)
                for g in guests for n in g.interfaces}
    def execute():
        if provider == 'esxi':
            execute_esxi_runtime(fake_netbox, hosts, config, confirmed=True)
        else:
            apply_full_sync(fake_netbox, hosts, config.target, confirmed=True)
    with netbox_http(fake_netbox) as (api, _, _):
        fake_netbox = api
        execute()
        interfaces = list(api.virtualization.interfaces.all())
        snapshot = {}
        for row in interfaces:
            g, n = expected[row.custom_fields['sync_identities'][0]['external_id']]
            assert row.name == n.bridge
            snapshot[row.id] = deepcopy(row.custom_fields)
            # Simulate persisted names from the preceding release.
            row.update({'name': n.name})
        macs = [r.serialize() for r in api.dcim.mac_addresses.all()]
        ips = [r.serialize() for r in api.ipam.ip_addresses.all()]
        plan = build_runtime_plan(api, hosts, config)
        changes = [r for r in plan.items if r.action.value in ('CREATE', 'UPDATE')]
        assert changes and all(r.action.value == 'UPDATE' for r in changes)
        execute()
        assert {r.id for r in api.virtualization.interfaces.all()} == set(snapshot)
        for row in api.virtualization.interfaces.all():
            assert row.custom_fields == snapshot[row.id]
        assert [r.serialize() for r in api.dcim.mac_addresses.all()] == macs
        assert [r.serialize() for r in api.ipam.ip_addresses.all()] == ips
        assert not [r for r in build_runtime_plan(api, hosts, config).items
                    if r.action.value in ('CREATE', 'UPDATE')]
        for guest in guests:
            for nic in guest.interfaces:
                nic.bridge = 'DMZ'
        execute()
        assert {r.id for r in api.virtualization.interfaces.all()} == set(snapshot)
        assert all(r.name == 'DMZ' for r in api.virtualization.interfaces.all())
        assert not [r for r in build_runtime_plan(api, hosts, config).items
                    if r.action.value in ('CREATE', 'UPDATE')]


def test_two_cards_same_bridge_remain_distinct_and_order_independent(fake_netbox):
    _, legacy, hosts, records, _ = _managed_setup(fake_netbox)
    vm = hosts[0].virtual_machines[0]
    first = vm.interfaces[0]
    second = deepcopy(first)
    second.external_id = '4001'
    second.name = 'Network adapter 2'
    second.mac_address = '00:50:56:AA:BB:CE'
    second.ip_addresses = ['192.0.2.53/24']
    vm.interfaces.append(second)
    apply_vm_networks(fake_netbox, hosts, legacy, confirmed=True)
    rows = fake_netbox.virtualization.interfaces.all()
    assert len(rows) == 2 and len({r.name for r in rows}) == 2
    assert all(r.name.startswith('VM Network / ') for r in rows)
    ids = {r.id for r in rows}
    vm.interfaces.reverse()
    fake_netbox.clear_mutations()
    apply_vm_networks(fake_netbox, hosts, legacy, confirmed=True)
    assert fake_netbox.mutations == []
    assert {r.id for r in fake_netbox.virtualization.interfaces.all()} == ids


@pytest.mark.parametrize('managed', [False, True])
def test_occupied_bridge_name_blocks_before_network_writes(fake_netbox, managed):
    _, legacy, hosts, records, _ = _managed_setup(fake_netbox)
    vm = hosts[0].virtual_machines[0]
    if managed:
        _network_records(fake_netbox, records[0], vm)
    fake_netbox.virtualization.interfaces.add(FakeRecord(
        id=987, name=vm.interfaces[0].bridge, virtual_machine=records[0], custom_fields={},
    ))
    fake_netbox.clear_mutations()
    with pytest.raises(VMNetworkApplyError):
        apply_vm_networks(fake_netbox, hosts, legacy, confirmed=True)
    assert fake_netbox.mutations == []


def test_missing_bridge_and_long_names():
    nic = SimpleNamespace(name='eth0', bridge=None, external_id='net0')
    guest = SimpleNamespace(interfaces=[nic])
    assert interface_display_name(guest, nic) == 'eth0'
    nic.bridge = 'Ж' * 100
    assert len(interface_display_name(guest, nic)) == 64
    assert nic.bridge == 'Ж' * 100


def test_original_unmanaged_name_is_still_an_adoption_blocker(fake_netbox):
    _, legacy, hosts, records, _ = _managed_setup(fake_netbox)
    vm = hosts[0].virtual_machines[0]
    fake_netbox.virtualization.interfaces.add(FakeRecord(
        id=987, name=vm.interfaces[0].name, virtual_machine=records[0], custom_fields={},
    ))
    fake_netbox.clear_mutations()
    with pytest.raises(VMNetworkApplyError):
        apply_vm_networks(fake_netbox, hosts, legacy, confirmed=True)
    assert fake_netbox.mutations == []


def test_rename_swap_blocks_before_network_writes(fake_netbox):
    _, legacy, hosts, records, _ = _managed_setup(fake_netbox)
    vm = hosts[0].virtual_machines[0]
    first = vm.interfaces[0]
    first.bridge = 'LAN'
    second = deepcopy(first)
    second.external_id = '4001'
    second.name = 'Network adapter 2'
    second.bridge = 'DMZ'
    second.mac_address = '00:50:56:AA:BB:CE'
    second.ip_addresses = []
    vm.interfaces.append(second)
    apply_vm_networks(fake_netbox, hosts, legacy, confirmed=True)
    first.bridge, second.bridge = second.bridge, first.bridge
    fake_netbox.clear_mutations()
    with pytest.raises(VMNetworkApplyError):
        apply_vm_networks(fake_netbox, hosts, legacy, confirmed=True)
    assert fake_netbox.mutations == []
