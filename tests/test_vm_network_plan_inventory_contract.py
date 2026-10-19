"""Read order and output contracts for the legacy VM network planner."""
from pathlib import Path
import pytest
from tests.fakes import FakeRecord
from tests.test_esxi_network_bootstrap import _managed_setup
from netbox_sync.netbox_vm_network_planner import plan_vm_networks


@pytest.mark.parametrize('failure_at', [None, 'vms', 'interfaces', 'macs', 'ips', 'vlans', 'prefixes'])
def test_read_order_and_failure_output(fake_netbox, monkeypatch, capsys, failure_at):
    cluster, target, hosts, _, _ = _managed_setup(fake_netbox)
    calls = []
    failure = RuntimeError('inventory unavailable')
    endpoints = [('vms', fake_netbox.virtualization.virtual_machines, 'filter'),
                 ('interfaces', fake_netbox.virtualization.interfaces, 'all'),
                 ('macs', fake_netbox.dcim.mac_addresses, 'all'),
                 ('ips', fake_netbox.ipam.ip_addresses, 'all'),
                 ('vlans', fake_netbox.ipam.vlans, 'all'),
                 ('prefixes', fake_netbox.ipam.prefixes, 'all')]
    for name, endpoint, method in endpoints:
        original = getattr(endpoint, method)
        def read(*args, _name=name, _original=original, **kwargs):
            calls.append((_name, kwargs))
            if _name == failure_at:
                raise failure
            return _original(*args, **kwargs)
        monkeypatch.setattr(endpoint, method, read)
    site = fake_netbox.dcim.sites.get(slug=target.site_slug)
    capsys.readouterr()
    if failure_at:
        with pytest.raises(RuntimeError) as caught:
            plan_vm_networks(fake_netbox, hosts[0], cluster, site)
        assert caught.value is failure
        assert capsys.readouterr().out == '\n  QEMU VM NETWORK\n'
    else:
        plan_vm_networks(fake_netbox, hosts[0], cluster, site)
    names = [name for name, _, _ in endpoints]
    expected = names[:names.index(failure_at) + 1] if failure_at else names
    assert [name for name, _ in calls] == expected
    assert calls[0][1] == {'cluster_id': cluster.id}
    assert all(not kwargs for _, kwargs in calls[1:])
    assert fake_netbox.mutations == []


@pytest.mark.parametrize('scenario', ['empty_inventory', 'duplicates', 'invalid_addresses', 'invalid_vlan'])
def test_planner_inventory_output(fake_netbox, capsys, scenario):
    cluster, target, hosts, _, _ = _managed_setup(fake_netbox)
    nic = hosts[0].virtual_machines[0].interfaces[0]
    if scenario == 'duplicates':
        for i, vrf in [(801, None), (802, 42)]:
            fake_netbox.ipam.ip_addresses.add(FakeRecord(id=i, address=nic.ip_addresses[0], vrf=vrf,
                assigned_object_type=None, assigned_object_id=None))
            fake_netbox.dcim.mac_addresses.add(FakeRecord(id=i, mac_address=nic.mac_address,
                assigned_object_type=None, assigned_object_id=None))
            fake_netbox.ipam.vlans.add(FakeRecord(id=i, vid=120, name='duplicate'))
            fake_netbox.ipam.prefixes.add(FakeRecord(id=i, prefix='192.0.2.0/24'))
    elif scenario == 'invalid_addresses':
        for i, address in [(801, None), (802, 'invalid')]:
            fake_netbox.ipam.ip_addresses.add(FakeRecord(id=i, address=address))
    elif scenario == 'invalid_vlan':
        fake_netbox.ipam.vlans.add(FakeRecord(id=801, vid='invalid'))
    capsys.readouterr()
    site = fake_netbox.dcim.sites.get(slug=target.site_slug)
    if scenario == 'invalid_vlan':
        with pytest.raises(ValueError):
            plan_vm_networks(fake_netbox, hosts[0], cluster, site)
    else:
        plan_vm_networks(fake_netbox, hosts[0], cluster, site)
    output = capsys.readouterr().out
    snapshot = Path(__file__).parent / 'fixtures' / 'vm_network_plan_inventory' / (scenario + '.txt')
    assert output == snapshot.read_text(encoding='utf-8')
    assert fake_netbox.mutations == []


def test_indexes_preserve_records_duplicates_and_address_only_policy(fake_netbox):
    from netbox_sync.vm_network_plan_inventory import prepare_vm_network_plan_inventory
    from netbox_sync.netbox_vm_network_planner import _canonical_mac, _canonical_address
    cluster, _, _, records, _ = _managed_setup(fake_netbox)
    interface = fake_netbox.virtualization.interfaces.add(FakeRecord(id=801, virtual_machine=records[0]))
    fake_netbox.virtualization.interfaces.add(FakeRecord(id=802, virtual_machine=None))
    ips = [fake_netbox.ipam.ip_addresses.add(FakeRecord(id=i, address='192.0.2.1/24', vrf=vrf))
           for i, vrf in [(803, None), (804, 42)]]
    invalid = fake_netbox.ipam.ip_addresses.add(FakeRecord(id=805, address='invalid'))
    vlans = [fake_netbox.ipam.vlans.add(FakeRecord(id=i, vid=vid)) for i, vid in [(806, '120'), (807, 120)]]
    prefixes = [fake_netbox.ipam.prefixes.add(FakeRecord(id=i, prefix='192.0.2.0/24')) for i in (808, 809)]
    result = prepare_vm_network_plan_inventory(fake_netbox, cluster,
        _canonical_mac=_canonical_mac, _canonical_address=_canonical_address)
    assert result.target_vms[0] is records[0]
    assert result.interfaces_by_vm == {records[0].id: [interface]}
    assert result.ips_by_address == {'192.0.2.1/24': ips}
    assert result.ips_by_id[805] is invalid
    assert result.vlans_by_vid == {120: vlans}
    assert result.prefixes_by_prefix == {'192.0.2.0/24': prefixes}
    assert fake_netbox.mutations == []
