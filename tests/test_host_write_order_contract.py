"""Host writes retain completed earlier-host mutations when a later address conflicts."""

import pytest
from tests.test_host_apply_preflight_contract import prepared
from netbox_sync.netbox_apply import apply_hosts, HostApplyError


def test_later_host_address_conflict_keeps_prior_write_order(fake_netbox, capsys):
    config, hosts = prepared(fake_netbox)
    with pytest.raises(HostApplyError, match="IP assignment changed after preflight"):
        apply_hosts(fake_netbox, hosts, config, confirmed=True)
    expected = [
        ("create", "dcim.devices"),
        ("create", "dcim.interfaces"),
        ("create", "ipam.ip_addresses"),
        ("update", "dcim.devices"),
        ("create", "dcim.devices"),
        ("create", "dcim.interfaces"),
    ]
    assert [(m[0], m[1]) for m in fake_netbox.mutations] == expected
    assert "APPLY SUMMARY" not in capsys.readouterr().out


def test_network_disabled_multi_host_writes_only_devices(fake_netbox, capsys):
    config, hosts = prepared(fake_netbox)
    apply_hosts(fake_netbox, hosts, config, confirmed=True, host_networking=False)
    assert [(m[0], m[1]) for m in fake_netbox.mutations] == [("create", "dcim.devices")] * 2
    output = capsys.readouterr().out
    assert "APPLY SUMMARY created=2 updated=0 skipped=0" in output
