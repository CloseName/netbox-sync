"""Precheck reporters consume contexts once and keep counters local to each call."""

from types import SimpleNamespace
import pytest
from netbox_sync.vm_network_report import print_vm_network_precheck
from netbox_sync.lxc_network_report import print_lxc_network_precheck


@pytest.mark.parametrize("kind,report", [("vm", print_vm_network_precheck), ("lxc", print_lxc_network_precheck)])
def test_generator_contexts_preserve_order_and_reset_counters(capsys, kind, report):
    guest = SimpleNamespace(vmid=20, original_name="fixture", interfaces=[])
    nics = []
    for index in range(3):
        nic = SimpleNamespace(name="net" + str(index), bridge=None, vlan_id=None)
        guest.interfaces.append(nic)
        nics.append(
            {
                "source": nic,
                "existing": None if index == 0 else object(),
                "interface_changes": {"enabled": True} if index == 1 else {},
                "changes": {"enabled": True} if index == 1 else {},
                "mac_value": None,
                "existing_mac": None,
                "ips": [{"existing": None if index == 0 else object(), "address": "192.0.2." + str(index + 1) + "/24"}],
            }
        )
    context = {
        "source_vm": guest,
        "container": guest,
        "netbox_vm": SimpleNamespace(id=10),
        "nics": nics,
        "primary_candidate": None,
    }

    def contexts():
        yield context

    first = None
    for _ in range(2):
        report(contexts(), SimpleNamespace(name="site"), SimpleNamespace(name="cluster"))
        output = capsys.readouterr().out
        if first is None:
            first = output
        else:
            assert output == first
        assert output.index("CREATE INTERFACE") < output.index("UPDATE INTERFACE") < output.index("SKIP INTERFACE")
        for line in (
            "  interface_create=1",
            "  interface_update=1",
            "  interface_skip=1",
            "  ip_create=1",
            "  ip_match=2",
        ):
            assert line + "\n" in output
    assert len(context["nics"]) == 3 and context["primary_candidate"] is None
