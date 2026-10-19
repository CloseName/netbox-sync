"""Behavioral contracts for LXC network inventory preparation before extraction."""
import pytest
from tests.fakes import FakeRecord
from tests.fakes import FakeProxmox
from tests.netbox_scenarios import add_target
from tests.sample_data import sample_source_config, proxmox_responses
from netbox_sync.proxmox_discovery import discover_hosts
from netbox_sync.netbox_lxc_metadata import build_lxc_custom_fields


def _managed_setup(api):
    _, _, cluster, target = add_target(api)
    hosts = discover_hosts(FakeProxmox(proxmox_responses()), sample_source_config())
    container = hosts[0].containers[0]
    record = api.virtualization.virtual_machines.add(FakeRecord(
        id=80, name=container.original_name, cluster=cluster,
        custom_fields=build_lxc_custom_fields(container)))
    return cluster, target, hosts, [record], None

from netbox_sync.netbox_lxc_network_apply import apply_lxc_networks, LXCNetworkApplyError


@pytest.mark.parametrize('failure_at', [None, 'vms', 'interfaces', 'macs', 'ips'])
def test_inventory_read_order_and_fail_closed(fake_netbox, monkeypatch, failure_at):
    _, target, hosts, _, _ = _managed_setup(fake_netbox)
    calls = []
    failure = RuntimeError('fixture inventory unavailable')
    endpoints = [('vms', fake_netbox.virtualization.virtual_machines, 'all'),
                 ('interfaces', fake_netbox.virtualization.interfaces, 'all'),
                 ('macs', fake_netbox.dcim.mac_addresses, 'all'),
                 ('ips', fake_netbox.ipam.ip_addresses, 'all')]
    for name, endpoint, method in endpoints:
        original = getattr(endpoint, method)
        def read(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            if _name == failure_at:
                raise failure
            return _original(*args, **kwargs)
        monkeypatch.setattr(endpoint, method, read)
    if failure_at:
        with pytest.raises(RuntimeError) as caught:
            apply_lxc_networks(fake_netbox, hosts, target, confirmed=True)
        assert caught.value is failure
        assert calls == [name for name, _, _ in endpoints][:calls.index(failure_at) + 1]
    else:
        apply_lxc_networks(fake_netbox, hosts, target, confirmed=False)
        assert calls == ['vms', 'interfaces', 'macs', 'ips']
    assert fake_netbox.mutations == []


@pytest.mark.parametrize('kind', ['mac', 'ip'])
def test_duplicate_inventory_is_not_collapsed(fake_netbox, kind):
    _, target, hosts, _, _ = _managed_setup(fake_netbox)
    nic = hosts[0].containers[0].interfaces[0]
    for identity in (801, 802):
        if kind == 'mac':
            fake_netbox.dcim.mac_addresses.add(FakeRecord(id=identity, mac_address=nic.mac_address,
                assigned_object_type=None, assigned_object_id=None))
        else:
            fake_netbox.ipam.ip_addresses.add(FakeRecord(id=identity, address=nic.ip_addresses[0],
                assigned_object_type=None, assigned_object_id=None))
    with pytest.raises(LXCNetworkApplyError, match='Duplicate NetBox'):
        apply_lxc_networks(fake_netbox, hosts, target, confirmed=True)
    assert fake_netbox.mutations == []


def test_malformed_unrelated_ip_is_ignored(fake_netbox):
    _, target, hosts, _, _ = _managed_setup(fake_netbox)
    for identity, address in [(801, None), (802, 'not-an-address')]:
        fake_netbox.ipam.ip_addresses.add(FakeRecord(id=identity, address=address))
    apply_lxc_networks(fake_netbox, hosts, target, confirmed=False)
    assert fake_netbox.mutations == []



def test_identity_outside_target_cluster_is_still_found_and_refused(fake_netbox):
    _, target, hosts, records, _ = _managed_setup(fake_netbox)
    records[0].cluster = FakeRecord(id=999)
    with pytest.raises(LXCNetworkApplyError, match='outside target cluster'):
        apply_lxc_networks(fake_netbox, hosts, target, confirmed=True)
    assert fake_netbox.mutations == []


def test_lxc_indexes_keep_foreign_records_and_scoped_duplicates(fake_netbox):
    from netbox_sync.lxc_network_inventory import prepare_lxc_network_inventory
    from netbox_sync.netbox_lxc_network_apply import _canonical_mac, _canonical_ip
    from netbox_sync.network_scopes import scope_key
    _, _, _, records, _ = _managed_setup(fake_netbox)
    foreign = fake_netbox.virtualization.virtual_machines.add(FakeRecord(id=999, cluster=999))
    interface = fake_netbox.virtualization.interfaces.add(FakeRecord(id=901, virtual_machine=records[0]))
    fake_netbox.virtualization.interfaces.add(FakeRecord(id=902, virtual_machine=None))
    macs = [fake_netbox.dcim.mac_addresses.add(FakeRecord(id=i, mac_address=value))
            for i, value in [(903, 'AA:BB:CC:DD:EE:FF'), (904, 'aa:bb:cc:dd:ee:ff')]]
    ips = [fake_netbox.ipam.ip_addresses.add(FakeRecord(id=i, address='192.0.2.1/24', vrf=vrf))
           for i, vrf in [(905, None), (906, None), (907, {'id': 42})]]
    fake_netbox.ipam.ip_addresses.add(FakeRecord(id=908, address='invalid'))
    result = prepare_lxc_network_inventory(fake_netbox, _canonical_mac=_canonical_mac, _canonical_ip=_canonical_ip)
    assert result.all_vms[-1] is foreign
    assert result.interfaces_by_vm[records[0].id] == [interface]
    assert None not in result.interfaces_by_vm
    assert result.macs_by_address[_canonical_mac('AA:BB:CC:DD:EE:FF')] == macs
    assert result.ips_by_address[scope_key('192.0.2.1/24', None)] == ips[:2]
    assert result.ips_by_address[scope_key('192.0.2.1/24', 42)] == ips[2:]
    assert len(result.ips_by_address) == 2
    assert fake_netbox.mutations == []
