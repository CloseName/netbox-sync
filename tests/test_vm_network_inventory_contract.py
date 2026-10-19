"""Behavioral contracts for VM network inventory preparation before extraction."""
import pytest
from tests.fakes import FakeRecord
from tests.test_esxi_network_bootstrap import _managed_setup
from netbox_sync.netbox_vm_network_apply import apply_vm_networks, VMNetworkApplyError


@pytest.mark.parametrize('failure_at', [None, 'vms', 'interfaces', 'macs', 'ips'])
def test_inventory_read_order_and_fail_closed(fake_netbox, monkeypatch, failure_at):
    _, target, hosts, _, _ = _managed_setup(fake_netbox)
    calls = []
    failure = RuntimeError('fixture inventory unavailable')
    endpoints = [('vms', fake_netbox.virtualization.virtual_machines, 'filter'),
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
            apply_vm_networks(fake_netbox, hosts, target, confirmed=True)
        assert caught.value is failure
        assert calls == [name for name, _, _ in endpoints][:calls.index(failure_at) + 1]
    else:
        apply_vm_networks(fake_netbox, hosts, target, confirmed=False)
        assert calls == ['vms', 'interfaces', 'macs', 'ips']
    assert fake_netbox.mutations == []


@pytest.mark.parametrize('kind', ['mac', 'ip'])
def test_duplicate_inventory_is_not_collapsed(fake_netbox, kind):
    _, target, hosts, _, _ = _managed_setup(fake_netbox)
    nic = hosts[0].virtual_machines[0].interfaces[0]
    for identity in (801, 802):
        if kind == 'mac':
            fake_netbox.dcim.mac_addresses.add(FakeRecord(id=identity, mac_address=nic.mac_address,
                assigned_object_type=None, assigned_object_id=None))
        else:
            fake_netbox.ipam.ip_addresses.add(FakeRecord(id=identity, address=nic.ip_addresses[0],
                assigned_object_type=None, assigned_object_id=None))
    with pytest.raises(VMNetworkApplyError, match='Duplicate NetBox'):
        apply_vm_networks(fake_netbox, hosts, target, confirmed=True)
    assert fake_netbox.mutations == []


def test_malformed_unrelated_ip_is_ignored(fake_netbox):
    _, target, hosts, _, _ = _managed_setup(fake_netbox)
    for identity, address in [(801, None), (802, 'not-an-address')]:
        fake_netbox.ipam.ip_addresses.add(FakeRecord(id=identity, address=address))
    apply_vm_networks(fake_netbox, hosts, target, confirmed=False)
    assert fake_netbox.mutations == []


def test_prepared_indexes_preserve_records_duplicates_and_vrf_scopes(fake_netbox):
    from netbox_sync.vm_network_inventory import prepare_vm_network_inventory
    from netbox_sync.netbox_vm_network_apply import _canonical_mac
    from netbox_sync.network_scopes import scope_key
    cluster, _, _, records, _ = _managed_setup(fake_netbox)
    vm = records[0]
    orphan = fake_netbox.virtualization.interfaces.add(FakeRecord(id=901, virtual_machine=None))
    interface = fake_netbox.virtualization.interfaces.add(FakeRecord(id=902, virtual_machine=vm))
    macs = [fake_netbox.dcim.mac_addresses.add(FakeRecord(id=i, mac_address=value))
            for i, value in [(903, 'AA:BB:CC:DD:EE:FF'), (904, 'aa:bb:cc:dd:ee:ff')]]
    ips = [fake_netbox.ipam.ip_addresses.add(FakeRecord(id=i, address='192.0.2.1/24', vrf=vrf))
           for i, vrf in [(905, None), (906, None), (907, {'id': 42})]]
    invalid = fake_netbox.ipam.ip_addresses.add(FakeRecord(id=908, address='invalid'))
    result = prepare_vm_network_inventory(fake_netbox, cluster, _canonical_mac=_canonical_mac)
    assert result.target_vms[0] is vm
    assert result.interfaces_by_id[orphan.id] is orphan
    assert result.interfaces_by_vm[vm.id] == [interface]
    assert None not in result.interfaces_by_vm
    assert result.macs_by_address[_canonical_mac('AA:BB:CC:DD:EE:FF')] == macs
    assert result.ips_by_address[scope_key('192.0.2.1/24', None)] == ips[:2]
    assert result.ips_by_address[scope_key('192.0.2.1/24', 42)] == ips[2:]
    assert result.ips_by_id[invalid.id] is invalid
    assert len(result.ips_by_address) == 2
    assert fake_netbox.mutations == []
