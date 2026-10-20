"""Placement mapping retains absent hosts before invalidating ready plans."""

from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace as NS
import pytest
from psycopg import sql
from netbox_sync import placement_control as module
from netbox_sync.source_lifecycle import LifecycleError
from netbox_sync.netbox_catalog import project


@pytest.fixture
def placement(monkeypatch):
    events = []
    current = {
        "settings": {
            "onboarding_mapping": {
                "hosts": [{"id": "old", "name": "Absent"}],
                "host_types": {"old": {"id": 99}},
                "ip_conflict_policy": "observe",
            }
        }
    }
    hosts = [{"id": "new", "name": "Present"}]
    refs = {k: project(k, dict(id=i + 1, name=k, slug=k)) for i, k in enumerate(sorted(module.KINDS))}
    refs["cluster"] = project(
        "cluster",
        dict(
            id=12,
            name="Cluster",
            scope_type="dcim.site",
            scope_id=refs["site"]["id"],
            type={"id": refs["cluster_type"]["id"], "name": "cluster_type"},
        ),
    )
    mapping = dict(
        version=1,
        references=refs,
        host_types={"new": project("device_type", dict(id=13, model="Server", slug="server"))},
        hosts=hosts,
    )

    def execute(query, params):
        events.append((str(query), params))
        return NS(fetchone=lambda: None)

    connection = NS(execute=execute)
    store = NS(
        lock_path="lock",
        schema="fixture",
        lock=lambda *args: nullcontext(),
        connect=lambda: nullcontext(connection),
        revision=lambda row: "revision",
        table=lambda name: sql.Identifier(name),
        read=lambda source: {"source": source},
    )
    monkeypatch.setattr(module, "row", lambda *args: current)
    monkeypatch.setattr(module, "evidence", lambda *args: ("discovery", hosts))
    monkeypatch.setattr(module, "source_gate", lambda *args: nullcontext())
    monkeypatch.setattr(module, "blocking_runs", lambda *args: sql.Identifier("runs"))
    return store, current, mapping, events


def test_mapping_retains_absent_identity_policy_and_update_order(placement):
    store, current, mapping, events = placement
    before = deepcopy(mapping)
    assert module.save(store, "fixture", "revision", "discovery", mapping) == {"source": "fixture"}
    assert mapping == before
    assert len(events) == 4
    retained = events[2][1][-2].obj
    assert retained["hosts"] == [{"id": "old", "name": "Absent"}, {"id": "new", "name": "Present"}]
    assert retained["host_types"]["old"] == {"id": 99}
    assert retained["ip_conflict_policy"] == "observe"
    assert "network_scope_rules" not in retained
    assert "status='STALE'" in events[3][0]


@pytest.mark.parametrize(
    "patch",
    [
        {"version": 2},
        {"hosts": []},
        {"references": {}},
        {"host_types": {}},
        {"ip_conflict_policy": "invalid"},
        {"network_scope_rules": None},
    ],
)
def test_invalid_mapping_never_reaches_update(placement, patch):
    store, current, mapping, events = placement
    mapping.update(patch)
    with pytest.raises(LifecycleError, match="REQUEST_INVALID"):
        module.save(store, "fixture", "revision", "discovery", mapping)
    assert len(events) == 2
