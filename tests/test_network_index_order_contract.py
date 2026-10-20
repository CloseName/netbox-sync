"""Network indexing keeps read/serialization order and planner/write differences."""

from types import SimpleNamespace as Row
import pytest
from netbox_sync.vm_network_inventory import prepare_vm_network_inventory
from netbox_sync.vm_network_plan_inventory import prepare_vm_network_plan_inventory


@pytest.mark.parametrize("planning", [False, True])
def test_all_inventory_reads_precede_indexing_and_ip_serialization_count_is_preserved(planning):
    events = []

    def record(label, **data):
        def serialize():
            events.append("serialize-" + label)
            return dict(data)

        return Row(id=1, serialize=serialize)

    interface = record("nic", virtual_machine=10)
    mac = record("mac", mac_address="aa")
    ip = record("ip", address="192.0.2.5/24", vrf=None)
    vlan = record("vlan", vid=12)
    prefix = record("prefix", prefix="192.0.2.0/24")

    def endpoint(label, rows):
        def all_rows():
            events.append("read-" + label)
            return rows

        return Row(all=all_rows)

    def vms(**filters):
        assert filters == {"cluster_id": 7}
        events.append("read-vms")
        return []

    api = Row(
        virtualization=Row(virtual_machines=Row(filter=vms), interfaces=endpoint("nic", [interface])),
        dcim=Row(mac_addresses=endpoint("mac", [mac])),
        ipam=Row(
            ip_addresses=endpoint("ip", [ip]), vlans=endpoint("vlan", [vlan]), prefixes=endpoint("prefix", [prefix])
        ),
    )
    canonical = lambda value: value.upper()
    if planning:
        result = prepare_vm_network_plan_inventory(
            api, Row(id=7), _canonical_mac=canonical, _canonical_address=lambda value: value
        )
        expected = [
            "read-vms",
            "read-nic",
            "read-mac",
            "read-ip",
            "read-vlan",
            "read-prefix",
            "serialize-nic",
            "serialize-mac",
            "serialize-ip",
            "serialize-vlan",
            "serialize-prefix",
        ]
    else:
        result = prepare_vm_network_inventory(api, Row(id=7), _canonical_mac=canonical)
        expected = [
            "read-vms",
            "read-nic",
            "read-mac",
            "read-ip",
            "serialize-nic",
            "serialize-mac",
            "serialize-ip",
            "serialize-ip",
        ]
    assert events == expected
    assert result.interfaces_by_vm == {10: [interface]}
    assert result.macs_by_address == {"AA": [mac]}
    assert result.ips_by_id[1] is ip


@pytest.mark.parametrize("kind", ["vm", "lxc"])
def test_observe_projection_retains_invalid_addresses_and_scope_evidence(kind):
    from copy import deepcopy
    from tests.test_network_scopes import fixture
    from netbox_sync.application.ip_observations import assignment_inventory

    _, _, hosts = fixture("proxmox")
    host = hosts[0]
    guest = (host.virtual_machines if kind == "vm" else host.containers)[0]
    host.virtual_machines = [guest] if kind == "vm" else []
    host.containers = [guest] if kind == "lxc" else []
    nic = guest.interfaces[0]
    guest.interfaces = [nic]
    nic.ip_addresses = ["bad", "192.0.2.60/32", "192.0.2.61/24", "192.0.2.60/24"]
    nic.ip_vrf_id = 12
    nic.mac_scope_conflicts = [{"netbox_id": 77}]
    nic.ip_scope_conflicts = [{"address": "192.0.2.60/24", "vrf_id": 11, "netbox_id": 88}]
    before = deepcopy(hosts)
    projected, blockers, observations = assignment_inventory(hosts, "observe")
    got = (projected[0].virtual_machines if kind == "vm" else projected[0].containers)[0].interfaces[0]
    assert not blockers
    assert {c.kind for c in observations} == {"IP_ASSIGNMENT", "MAC_ASSIGNMENT"}
    assert got.ip_addresses == ["192.0.2.61/24", "bad"]
    assert got.mac_address is None
    assert got.network_observations == {
        "version": 1,
        "status": "REVIEW_REQUIRED",
        "addresses": ["192.0.2.60/24", "192.0.2.60/32"],
        "bridge": nic.bridge,
        "vlan_id": nic.vlan_id,
        "ipam_complete": False,
        "mac_addresses": [nic.mac_address.strip().upper()],
        "mac_assignment_complete": False,
        "mac_conflicts": [{"netbox_id": 77}],
        "vrf_id": 12,
        "scope_conflicts": [{"address": "192.0.2.60/24", "vrf_id": 11, "netbox_id": 88}],
    }
    assert hosts == before
