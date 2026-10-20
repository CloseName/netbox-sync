"""Legacy read-only planning retains status and numeric conversion quirks."""

from types import SimpleNamespace as Row
import pytest
import netbox_sync as runtime
from tests.fakes import FakeProxmox


@pytest.mark.parametrize("status,expected", [("running", "active"), ("stopped", "offline")])
def test_legacy_plan_summary_resets_and_decimal_vcpus_keep_truncation(capsys, status, expected):
    device = Row(id=10)
    responses = {
        ("nodes",): [{"node": "Node"}],
        ("nodes", "Node", "qemu"): [{"vmid": 4, "name": "vm4", "status": status}],
        ("nodes", "Node", "qemu", 4, "config"): {"vcpus": 2, "memory": "1024"},
    }
    objects = {
        "devices": {"node": device},
        "virtual_machines": {
            "4": Row(name="vm4", vcpus="2.9", memory="1024", status=Row(value=expected), device=device)
        },
    }
    for _ in range(2):
        runtime._run_plan(FakeProxmox(responses), objects)
        assert capsys.readouterr().out == (
            "=== SAFE PLAN MODE ===\nNo changes will be written to NetBox.\n\nNODE node=Node netbox_device_id=10\n  SKIP vmid=4 name=vm4 reason=no-change\n\nPlan summary:\n  CREATE:  0\n  UPDATE:  0\n  SKIP:    1\n  BLOCKED: 0\n"
        )
