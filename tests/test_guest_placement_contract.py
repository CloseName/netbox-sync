"""Placement contracts shared by the batch but distinct for VM/LXC identities."""

import pytest

from netbox_sync.guest_placement import apply_guest_placement
from netbox_sync.netbox_metadata import build_device_custom_fields
from netbox_sync.netbox_vm_metadata import build_vm_custom_fields
from netbox_sync.netbox_lxc_metadata import build_lxc_custom_fields
from netbox_sync.proxmox_discovery import discover_hosts
from tests.fakes import FakeProxmox, FakeRecord
from tests.sample_data import proxmox_responses, sample_source_config


def prepared(api):
    config = sample_source_config()
    hosts = discover_hosts(FakeProxmox(proxmox_responses()), config)
    host = hosts[0]
    host.virtual_machines = [next(vm for item in hosts for vm in item.virtual_machines)]
    host.containers = [next(lxc for item in hosts for lxc in item.containers)]
    device = api.dcim.devices.add(
        id=10, cluster=7, custom_fields=build_device_custom_fields(host))
    vm = api.virtualization.virtual_machines.add(
        id=20, cluster=7, device=None, custom_fields=build_vm_custom_fields(host.virtual_machines[0]))
    lxc = api.virtualization.virtual_machines.add(
        id=21, cluster=7, device=None, custom_fields=build_lxc_custom_fields(host.containers[0]))
    return config, [host], device, [vm, lxc]


def test_preview_confirmed_order_and_replay(fake_netbox):
    config, hosts, device, records = prepared(fake_netbox)
    assert apply_guest_placement(fake_netbox, hosts, config) is None
    assert fake_netbox.mutations == []
    apply_guest_placement(fake_netbox, hosts, config, confirmed=True)
    assert fake_netbox.mutations == [
        ('update', 'virtualization.virtual_machines', record.id, {'device': device.id})
        for record in records
    ]
    fake_netbox.clear_mutations()
    apply_guest_placement(fake_netbox, hosts, config, confirmed=True)
    assert fake_netbox.mutations == []


@pytest.mark.parametrize('confirmed', [False, True])
@pytest.mark.parametrize('problem,message', [
    ('missing', 'Guest placement identity is ambiguous or missing'),
    ('duplicate', 'Guest placement identity is ambiguous or missing'),
    ('owner', 'Guest has an unrelated host assignment'),
    ('cluster', 'Guest and managed host belong to different clusters'),
])
def test_later_lxc_failure_blocks_vm_write(fake_netbox, confirmed, problem, message):
    config, hosts, _, records = prepared(fake_netbox)
    lxc = records[1]
    if problem == 'missing':
        lxc.custom_fields = {}
    elif problem == 'duplicate':
        fake_netbox.virtualization.virtual_machines.add(
            id=22, cluster=7, custom_fields=lxc.custom_fields)
    elif problem == 'owner':
        lxc.device = 999
        lxc.cluster = 999  # Ownership failure must precede cluster failure.
    else:
        lxc.cluster = 999
    with pytest.raises(ValueError) as caught:
        apply_guest_placement(fake_netbox, hosts, config, confirmed=confirmed)
    assert str(caught.value) == message
    assert fake_netbox.mutations == []


@pytest.mark.parametrize('kind', [0, 1], ids=['vm', 'lxc'])
@pytest.mark.parametrize('owned', [False, True])
def test_previous_host_requires_matching_source_instance(fake_netbox, kind, owned):
    config, hosts, device, records = prepared(fake_netbox)
    guest = (hosts[0].virtual_machines + hosts[0].containers)[kind]
    previous = fake_netbox.dcim.devices.add(id=11, custom_fields={
        'sync_identities': [None, 'ignored', {'instance': guest.source_instance if owned else 'other'}]})
    records[kind].device = previous
    if owned:
        apply_guest_placement(fake_netbox, hosts, config, confirmed=True)
        assert all(record.device == device.id for record in records)
    else:
        with pytest.raises(ValueError, match='^Guest has an unrelated host assignment$'):
            apply_guest_placement(fake_netbox, hosts, config, confirmed=True)
        assert fake_netbox.mutations == []


@pytest.mark.parametrize('kind', [0, 1], ids=['vm', 'lxc'])
def test_already_assigned_guest_skips_cluster_check(fake_netbox, kind):
    config, hosts, device, records = prepared(fake_netbox)
    records[kind].device = device.id
    records[kind].cluster = 999
    apply_guest_placement(fake_netbox, hosts, config, confirmed=True)
    assert [mutation[2] for mutation in fake_netbox.mutations] == [records[1 - kind].id]


@pytest.mark.parametrize('duplicate', [False, True])
def test_host_identity_checked_before_guest_identity(fake_netbox, duplicate):
    config, hosts, device, records = prepared(fake_netbox)
    records[0].custom_fields = {}
    if duplicate:
        fake_netbox.dcim.devices.add(id=12, cluster=7, custom_fields=device.custom_fields)
        with pytest.raises(ValueError, match='^Ambiguous managed host identity$'):
            apply_guest_placement(fake_netbox, hosts, config, confirmed=True)
    else:
        device.custom_fields = {}
        apply_guest_placement(fake_netbox, hosts, config, confirmed=True)
    assert fake_netbox.mutations == []


def test_write_failure_preserves_prefix_and_propagates(fake_netbox, monkeypatch):
    config, hosts, _, records = prepared(fake_netbox)
    original = FakeRecord.update
    error = RuntimeError('placement update failed')

    def update(record, changes):
        if record is records[1]:
            raise error
        return original(record, changes)

    monkeypatch.setattr(FakeRecord, 'update', update)
    with pytest.raises(RuntimeError) as caught:
        apply_guest_placement(fake_netbox, hosts, config, confirmed=True)
    assert caught.value is error
    assert [mutation[2] for mutation in fake_netbox.mutations] == [records[0].id]
