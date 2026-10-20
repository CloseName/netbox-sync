"""Host network planning retains reference-only output and lookup order."""

from types import SimpleNamespace
import pytest
from netbox_sync.netbox_planner import _plan_host_network
from tests.fakes import FakeRecord


@pytest.mark.parametrize("scope,count,ip_count", [("site", 1, 1), ("global", 1, 0), ("site", 2, 2), ("none", 0, 0)])
def test_host_network_reference_report(fake_netbox, capsys, scope, count, ip_count):
    site = FakeRecord(id=1, name="site")
    for index in range(count):
        fields = {"scope_type": "dcim.site", "scope_id": 1} if scope == "site" else {}
        fake_netbox.ipam.vlans.add(FakeRecord(id=20 + index, vid=7, name="vlan", **fields))
        fake_netbox.ipam.prefixes.add(FakeRecord(id=30 + index, prefix="192.0.2.0/24", **fields))
    for index in range(ip_count):
        fake_netbox.ipam.ip_addresses.add(
            FakeRecord(
                id=40 + index, address="192.0.2.10/24", assigned_object_type="dcim.interface", assigned_object_id=50
            )
        )
    interface = SimpleNamespace(
        name="bridge0",
        interface_type="bridge",
        active=True,
        autostart=False,
        comments="fixture",
        bridge_ports=["eth0", "eth1"],
        vlan_aware=True,
        vlan_id=7,
        addresses=["192.0.2.10/24"],
    )
    host = SimpleNamespace(management_ip="192.0.2.10", interfaces=[interface])
    _plan_host_network(fake_netbox, host, None, site)
    output = capsys.readouterr().out
    assert "management_interface=bridge0" in output
    assert "CREATE INTERFACE name=bridge0 type=virtual" in output
    assert "description=fixture" in output and "bridge_ports=eth0,eth1" in output and "vlan_aware=True" in output
    if count == 0:
        assert "WARN VLAN vid=7 not-found action=not-created" in output
        assert "WARN PREFIX prefix=192.0.2.0/24 not-found action=not-created" in output
    elif count == 2:
        assert "CONFLICT VLAN vid=7 matches=2" in output
        assert "CONFLICT PREFIX prefix=192.0.2.0/24 matches=2" in output
    else:
        state = "match" if scope == "site" else "match-global"
        assert f"MATCH VLAN id=20 vid=7 name=vlan scope={state}" in output
        assert f"MATCH PREFIX id=30 prefix=192.0.2.0/24 scope={state}" in output
    if ip_count == 0:
        assert "CREATE IP address=192.0.2.10/24" in output
    elif ip_count == 2:
        assert "CONFLICT IP address=192.0.2.10/24 matches=2" in output
    else:
        assert "MATCH IP id=40 address=192.0.2.10/24" in output
        assert "currently_assigned=dcim.interface:50" in output
    assert "SET PRIMARY IPv4 address=192.0.2.10/24" in output
    assert fake_netbox.mutations == []
