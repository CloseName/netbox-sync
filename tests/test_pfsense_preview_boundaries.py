"""Detailed parsing and matching boundaries before pfSense preview extraction."""

import pytest
from netbox_sync.pfsense_preview import runtime_interfaces, build_preview, SnapshotError
from tests.test_pfsense_preview import sample

HEADER = "vtnet0: flags=1<UP> metric 0 mtu 1500\n"


@pytest.mark.parametrize(
    "line",
    [
        "\tinet 192.0.2.2 wrong 255.255.255.0",
        "\tinet6 fe80::1 wrong 64",
        "\tether aa:bb",
        "\tinet 192.0.2.2",
        "\tinet6 fe80::1%other prefixlen 64",
    ],
)
def test_bad_address_detail_is_closed(line):
    with pytest.raises(SnapshotError, match="Invalid or incomplete network snapshot"):
        runtime_interfaces(HEADER + line + "\n")


def test_duplicate_address_ignored_unknown_detail_and_latest_status_retained():
    raw = (
        HEADER
        + "\tinet 192.0.2.2 netmask 255.255.255.0\n" * 2
        + "\tunknown ignored\n\tstatus: first\n\tstatus: second\n"
    )
    row = runtime_interfaces(raw)["vtnet0"]
    assert row["status"] == "second"
    assert row["addresses"] == [{"address": "192.0.2.2/24", "scope": None, "link_local": False, "ipam_candidate": True}]


@pytest.mark.parametrize("count,valid", [(512, True), (513, False)])
def test_runtime_address_limit(count, valid):
    raw = HEADER + "".join(f"\tinet6 2001:db8::{i:x} prefixlen 64\n" for i in range(1, count + 1))
    if valid:
        assert len(runtime_interfaces(raw)["vtnet0"]["addresses"]) == 512
    else:
        with pytest.raises(SnapshotError):
            runtime_interfaces(raw)


def test_missing_runtime_mac_precedes_absent_target():
    snapshot, inventory = sample()
    snapshot["runtime"]["ifconfig"] = snapshot["runtime"]["ifconfig"].replace("\tether bc:24:11:90:8c:32\n", "")
    result = build_preview(snapshot, [], 2609)
    assert result["issues"] == [{"device": "vtnet0", "code": "MAC_MISSING"}]
    assert result["interfaces"][0]["match"] is None


def test_vlan_projection_preserves_order_and_omits_extra_fields():
    snapshot, inventory = sample()
    snapshot["configuration"]["vlans"] = [
        {"parent": "vtnet0", "tag": str(i), "device": f"vlan{i}", "description": "review", "extra": "secret"}
        for i in (20, 10)
    ]
    result = build_preview(snapshot, inventory, 2609)
    assert [row["tag"] for row in result["vlans"]] == ["20", "10"]
    assert all(set(row) == {"parent", "tag", "device", "description"} for row in result["vlans"])
