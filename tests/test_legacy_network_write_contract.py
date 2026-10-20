"""Legacy address selection intentionally differs from modern network writes."""

import pytest
from netbox_sync import legacy_netbox_writes as writes
from tests.fakes import FakeNetBox


def setup():
    api = FakeNetBox()
    vm = api.virtualization.virtual_machines.add(id=4, name="vm")
    objects = {key: {} for key in ("virtual_machines_interfaces", "mac_addresses", "prefixes", "ip_addresses", "vlans")}
    return api, vm, objects


@pytest.mark.parametrize(
    "addresses,expected",
    [
        (
            {
                "ens19": [{"ip-address": "10.0.2.5", "prefix": 20}],
                "ens18": [{"ip-address": "10.0.1.5", "prefix": 20}],
                "eth0": [{"ip-address": "10.0.0.5", "prefix": 20}],
            },
            "10.0.0.5/20",
        ),
        (
            {"ens19": [{"ip-address": "10.0.2.5", "prefix": 20}], "ens18": [{"ip-address": "10.0.1.5", "prefix": 20}]},
            "10.0.1.5/20",
        ),
        ({"ens19": [{"ip-address": "10.0.2.5", "prefix": 20}]}, "10.0.2.5/20"),
    ],
)
def test_legacy_uses_first_known_name_and_last_octet_prefix(addresses, expected):
    api, vm, objects = setup()
    writes._process_pve_virtual_machine_network_interface(
        api, objects, vm, "net9", "AA:BB:CC:DD:EE:FF", None, addresses
    )
    assert api.ipam.ip_addresses.all()[0].address == expected
    assert api.ipam.prefixes.all()[0].prefix == expected.rsplit(".", 1)[0] + ".0/20"
    assert vm.primary_ip4 == api.ipam.ip_addresses.all()[0].id


def test_legacy_empty_preferred_address_list_fails_after_mac():
    api, vm, objects = setup()
    with pytest.raises(IndexError):
        writes._process_pve_virtual_machine_network_interface(
            api,
            objects,
            vm,
            "net0",
            "AA:BB:CC:DD:EE:FF",
            12,
            {"eth0": [], "ens18": [{"ip-address": "10.0.0.5", "prefix": 24}]},
        )
    assert [m[1] for m in api.mutations] == [
        "virtualization.interfaces",
        "dcim.mac_addresses",
        "virtualization.interfaces",
    ]
    assert not api.ipam.vlans.all()


def test_legacy_missing_known_address_does_not_write_vlan():
    api, vm, objects = setup()
    writes._process_pve_virtual_machine_network_interface(
        api, objects, vm, "net0", "AA:BB:CC:DD:EE:FF", 12, {"other": [{"ip-address": "10.0.0.5", "prefix": 24}]}
    )
    assert not api.ipam.vlans.all()
    assert not api.ipam.ip_addresses.all()
    assert not hasattr(vm, "primary_ip4")
