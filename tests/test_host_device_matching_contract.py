"""Device ownership takes precedence over adoption conflict evidence."""

from types import SimpleNamespace
import pytest
from netbox_sync import netbox_apply as module
from tests.fakes import FakeRecord


@pytest.mark.parametrize(
    "case,expected",
    [
        ("absent", None),
        ("invalid-ip", None),
        ("one-ip", "Device adoption candidate exists without sync identity: management_ip='192.0.2.10'"),
        ("two-ip", "Management IP conflict: 192.0.2.10 matches=2"),
        ("one-name", "Device adoption candidate exists without sync identity: 'host-a'"),
        ("two-name", "Device name conflict: 'host-a' matches=2"),
        ("ip-before-name", "Device adoption candidate exists without sync identity: management_ip='192.0.2.10'"),
    ],
)
def test_unowned_device_conflict_order(fake_netbox, monkeypatch, case, expected):
    host = SimpleNamespace(source="proxmox", source_id="a", normalized_name="host-a", management_ip="192.0.2.10")
    site = SimpleNamespace(id=1)
    monkeypatch.setattr(module, "find_sync_identity_matches", lambda devices, host: [])
    if case != "absent":
        count = 2 if case.startswith("two-") or case == "ip-before-name" else 1
        for number in range(count):
            name = "HOST-A" if "name" in case else "other"
            ip = "192.0.2.10/24" if "ip" in case and (case != "ip-before-name" or number == 0) else None
            if case == "invalid-ip":
                ip = "invalid"
            fake_netbox.dcim.devices.add(FakeRecord(id=number + 10, name=name, primary_ip4=ip))
    if expected is None:
        assert module._resolve_device(fake_netbox, host, site) == (None, None)
    else:
        with pytest.raises(module.HostApplyError) as caught:
            module._resolve_device(fake_netbox, host, site)
        assert str(caught.value) == expected
    assert fake_netbox.mutations == []


@pytest.mark.parametrize("matches,site_id", [(1, 1), (1, 2), (2, 1)])
def test_identity_precedes_address_and_name_checks(fake_netbox, monkeypatch, matches, site_id):
    host = SimpleNamespace(source="proxmox", source_id="a", normalized_name="host-a", management_ip="192.0.2.10")
    device = FakeRecord(id=10, name="owned", site=SimpleNamespace(id=site_id))
    # Invalid address objects would fail if adoption checks ran for an owned device.
    fake_netbox.dcim.devices.add(FakeRecord(id=11, name=None, primary_ip4=object()))
    monkeypatch.setattr(module, "find_sync_identity_matches", lambda devices, host: [device] * matches)
    if matches == 1 and site_id == 1:
        assert module._resolve_device(fake_netbox, host, SimpleNamespace(id=1)) == (device, "sync_identity")
    else:
        with pytest.raises(module.HostApplyError) as caught:
            module._resolve_device(fake_netbox, host, SimpleNamespace(id=1))
        assert str(caught.value) == (
            "Duplicate sync identity proxmox:a matches=2"
            if matches == 2
            else "Device 'owned' matched by sync_identity but is outside target site: site_id=2"
        )
    assert fake_netbox.mutations == []
