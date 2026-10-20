"""Reused MAC/IP assignment failures retain provider-specific partial-write order."""

import pytest
from tests.fakes import FakeRecord
from tests.fakes.netbox import FakeEndpoint
from tests.test_esxi_network_bootstrap import _managed_setup
from tests.test_lxc_network_preflight_contract import _two_containers
from netbox_sync.netbox_vm_network_apply import apply_vm_networks
from netbox_sync.netbox_lxc_network_apply import apply_lxc_networks


@pytest.mark.parametrize("kind", ["vm", "lxc"])
@pytest.mark.parametrize("failure_at", range(1, 6))
def test_reused_network_assignment_failure_order(fake_netbox, monkeypatch, capsys, kind, failure_at):
    if kind == "vm":
        _, target, hosts, _, _ = _managed_setup(fake_netbox)
        guest = hosts[0].virtual_machines[0]
        apply = apply_vm_networks
    else:
        target, hosts, _, guest, _ = _two_containers(fake_netbox)
        hosts[0].containers = [guest]
        apply = apply_lxc_networks
    nic = guest.interfaces[0]
    fake_netbox.dcim.mac_addresses.add(
        FakeRecord(id=801, mac_address=nic.mac_address, assigned_object_type=None, assigned_object_id=None)
    )
    fake_netbox.ipam.ip_addresses.add(
        FakeRecord(id=802, address=nic.ip_addresses[0], assigned_object_type=None, assigned_object_id=None)
    )
    attempts = []
    failure = RuntimeError("injected reused assignment failure")

    def guard(original, instance, *args, **kwargs):
        attempts.append(1)
        if len(attempts) == failure_at:
            raise failure
        return original(instance, *args, **kwargs)

    create, update = FakeEndpoint.create, FakeRecord.update
    monkeypatch.setattr(FakeEndpoint, "create", lambda self, **kw: guard(create, self, **kw))
    monkeypatch.setattr(FakeRecord, "update", lambda self, changes: guard(update, self, changes))
    with pytest.raises(RuntimeError) as caught:
        apply(fake_netbox, hosts, target, confirmed=True)
    assert caught.value is failure
    expected = [
        ("create", "virtualization.interfaces"),
        ("update", "dcim.mac_addresses"),
        ("update", "virtualization.interfaces"),
        ("update", "ipam.ip_addresses"),
        ("update", "virtualization.virtual_machines"),
    ]
    assert len(attempts) == failure_at
    assert [(m[0], m[1]) for m in fake_netbox.mutations] == expected[: failure_at - 1]
    assert "NETWORK APPLY SUMMARY" not in capsys.readouterr().out
