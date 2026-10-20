"""Guest disappearance indexing retains callback order and VM/LXC identity distinctions."""

from types import SimpleNamespace as NS
import pytest
from netbox_sync.disappearance_identity import collect_discovered_identities


@pytest.mark.parametrize("legacy", [False, True])
def test_identity_collection_keeps_host_reads_and_distinct_guest_callbacks(legacy):
    calls = []

    def callback(label):
        def invoke(obj, nic=None):
            calls.append(label)
            return label if nic is None else label + ":" + nic.name

        return invoke

    vm = NS(source="proxmox", interfaces=[NS(name="net0")])
    lxc = NS(source="proxmox", interfaces=[NS(name="eth0")])
    host = NS(
        source="proxmox",
        source_instance="source-a",
        legacy_identity_owner=legacy,
        virtual_machines=[vm],
        containers=[lxc],
    )
    value = collect_discovered_identities(
        [host],
        _local_source_id=callback("host"),
        vm_identity_source_id=callback("vm-legacy"),
        virtual_machine_source_identity=callback("vm-v2"),
        nic_identity_source_id=callback("nic-legacy"),
        virtual_machine_nic_source_identity=callback("vm-nic-v2"),
        lxc_identity_source_id=callback("lxc-legacy"),
        lxc_source_identity=callback("lxc-v2"),
        lxc_nic_source_identity=callback("lxc-nic-v2"),
    )
    assert type(value) is tuple
    assert value == (
        {("proxmox", "host:")} if legacy else set(),
        {("proxmox", "source-a")},
        {("proxmox", "vm-legacy"), "vm-v2", ("proxmox", "lxc-legacy"), "lxc-v2"},
        {("proxmox", "nic-legacy:net0"), "vm-nic-v2:net0", ("proxmox", "nic-legacy:eth0"), "lxc-nic-v2:eth0"},
    )
    assert calls == [
        "host",
        "vm-legacy",
        "vm-v2",
        "nic-legacy",
        "vm-nic-v2",
        "lxc-legacy",
        "lxc-v2",
        "nic-legacy",
        "lxc-nic-v2",
    ]


def test_disappearance_report_passes_counts_and_retained_warnings_unchanged(monkeypatch, capsys):
    from netbox_sync import netbox_disappearance as module

    vm, nic = NS(id=7, name="old-vm"), NS(id=8, name="eth0")
    monkeypatch.setattr(module, "resolve_disappearance_target", lambda *args, **kwargs: (None, "cluster"))
    monkeypatch.setattr(
        module, "collect_discovered_identities", lambda *args, **kwargs: (set(), set(), {"current"}, {"nic-a", "nic-b"})
    )
    monkeypatch.setattr(module, "build_managed_identity_resolver", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "load_disappearance_inventory", lambda *args, **kwargs: ([], {}))
    monkeypatch.setattr(
        module,
        "find_missing_objects",
        lambda *args: (2, [(vm, ("proxmox", "old"))], 3, [(vm, nic, ("proxmox", "nic"))]),
    )
    module.report_missing_managed_objects(None, [], None)
    assert capsys.readouterr().out == (
        "=== DISAPPEARANCE REPORT ===\nmanaged_guests=2\ndiscovered_guests=1\nmissing_guests=1\n"
        "managed_interfaces=3\ndiscovered_interfaces=2\nmissing_interfaces=1\n"
        "WARNING MISSING GUEST id=7 name='old-vm' identity=proxmox:old action=retained\n"
        "WARNING MISSING INTERFACE vm_id=7 vm='old-vm' interface_id=8 name='eth0' identity=proxmox:nic action=retained\n"
        "No objects were deleted.\n"
    )
