"""Recovery aggregation keeps evidence and validation boundaries stable."""

from copy import deepcopy
import pytest
from netbox_sync.recovery_evidence import assess
from netbox_sync.bootstrap_probe import ProbeError

ANCHOR = "503c5ad7-aaaa-bbbb-cccc-0123456789ab"
CLUSTER = {"id": 3, "scope_type": "dcim.site", "scope_id": 1}


def row(identifier, kind="host", external=ANCHOR):
    return {
        "id": identifier,
        "cluster": 3,
        "custom_fields": {
            "sync_identities": [
                {"schema": "v2", "type": "esxi", "instance": "source-a", "kind": kind, "external_id": external}
            ]
        },
    }


def test_device_and_vm_ids_have_independent_duplicate_namespaces():
    devices = [row(1)]
    machines = [row(1, "vm", "vm-a")]
    before = deepcopy((devices, machines))
    result = assess("source-a", ANCHOR, 1, 3, CLUSTER, devices, machines, require_host=True)
    assert result["blockers"] == []
    assert result["owned"] == [{"kind": "device", "id": 1}, {"kind": "vm", "id": 1}]
    assert (devices, machines) == before
    assert assess("source-a", ANCHOR, 1, 3, CLUSTER, devices, machines, require_host=True) == result


@pytest.mark.parametrize("identifier", [True, 0, -1, "1"])
def test_object_ids_remain_exact_positive_integers(identifier):
    with pytest.raises(ProbeError, match="^RESPONSE_INVALID$"):
        assess("source-a", ANCHOR, 1, 3, CLUSTER, [row(identifier)], [])


@pytest.mark.parametrize("kind", ["device", "vm"])
def test_duplicate_row_is_rejected_before_reading_its_provenance(kind):
    class Unreadable(dict):
        def get(self, key, *args):
            if key != "id":
                raise AssertionError("Duplicate provenance must not be read")
            return super().get(key, *args)

    rows = [row(1), Unreadable(id=1)]
    with pytest.raises(ProbeError, match="^RESPONSE_INVALID$"):
        assess("source-a", ANCHOR, 1, 3, CLUSTER, rows if kind == "device" else [], rows if kind == "vm" else [])


def test_inventory_limit_precedes_any_row_access():
    class Unreadable(dict):
        def get(self, *args):
            raise AssertionError("Oversized inventory must not be inspected")

    with pytest.raises(ProbeError, match="^RESPONSE_INVALID$"):
        assess("source-a", ANCHOR, 1, 3, CLUSTER, [Unreadable()] * 10001, [])
