"""Conflict collection preserves per-NIC deduplication and scope evidence."""

from types import SimpleNamespace
from netbox_sync.application.inventory_conflicts import inventory_conflicts
from netbox_sync.network_scopes import scope_key


def inventory(addresses=(), mac=None, vrf=None, previous_ips=(), previous_macs=()):
    nic = SimpleNamespace(
        name="eth0",
        external_id="nic-a",
        mac_address=mac,
        mac_scope_conflicts=previous_macs,
        ip_addresses=addresses,
        ip_vrf_id=vrf,
        ip_scope_conflicts=previous_ips,
    )
    guest = SimpleNamespace(
        external_id="guest-a", vmid=7, original_name="guest", provider_object_id="provider-a", interfaces=[nic]
    )
    host = SimpleNamespace(source_id="host-a", virtual_machines=[guest], containers=[])
    return host, guest, nic


def test_same_nic_deduplicates_exact_address_but_preserves_distinct_prefixes():
    host, _, _ = inventory(["192.0.2.1/24", "192.0.2.1/24", "192.0.2.1/25"])
    (conflict,) = inventory_conflicts([host])
    assert conflict.kind == "IP_ASSIGNMENT" and conflict.value == scope_key("192.0.2.1", None)
    assert [p.address for p in conflict.participants] == ["192.0.2.1/24", "192.0.2.1/25"]


def test_retained_ip_scope_evidence_uses_current_key_and_original_participant_vrf():
    host, _, _ = inventory(
        ["192.0.2.1/24"], vrf=7, previous_ips=[{"address": "192.0.2.1/25", "vrf_id": 9, "netbox_id": 31}]
    )
    (conflict,) = inventory_conflicts([host])
    assert conflict.value == scope_key("192.0.2.1", 7)
    assert [(p.vrf_id, p.netbox_id) for p in conflict.participants] == [(7, None), (9, 31)]


def test_mac_scope_evidence_keeps_normalization_and_participant_order():
    host, _, _ = inventory(mac=" aa:bb:cc:dd:ee:ff ", previous_macs=[{"netbox_id": 41}, {"netbox_id": 42}])
    (conflict,) = inventory_conflicts([host])
    assert conflict.kind == "MAC_ASSIGNMENT" and conflict.value == "AA:BB:CC:DD:EE:FF"
    assert [p.netbox_id for p in conflict.participants] == [None, 41, 42]
    assert all(p.interface_id == "nic-a" for p in conflict.participants)


def test_vm_and_lxc_identity_namespaces_remain_distinct():
    host, guest, _ = inventory()
    host.containers = [guest]
    assert inventory_conflicts([host]) == ()
    host.virtual_machines.append(guest)
    (conflict,) = inventory_conflicts([host])
    assert conflict.kind == "VM_IDENTITY" and conflict.value == "guest-a"
    assert len(conflict.participants) == 2


def test_invalid_and_special_addresses_do_not_create_conflicts():
    host, guest, _ = inventory(["invalid", "127.0.0.1/8", "169.254.1.1/16", "224.0.0.1/24", "0.0.0.0/32"] * 2)
    assert inventory_conflicts([host]) == ()
