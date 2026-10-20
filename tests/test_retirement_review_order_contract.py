"""Retirement review ordering and journal idempotency without Linux filesystem access."""

from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from uuid import UUID
import pytest
from netbox_sync import retirement_review as module
from tests.test_retirement_review import fixture, review, SOURCE


def test_blockers_keep_validation_traversal_and_classification_order():
    registry = [module.RegistryEntry(SOURCE, 5, removed=False, uncertain=True), module.RegistryEntry("other-source", 5)]
    objects = [
        module.ObjectEvidence("cluster", 5, "cluster", (SOURCE,), ("vm:1", "device:99"), creation_proven=True),
        module.ObjectEvidence("vm", 1, "vm", ("other-source",), ("cluster:5",)),
        module.ObjectEvidence("ip", 8, "outside", (SOURCE,), creation_proven=True),
    ]
    value = module.build_review(SOURCE, registry, objects, registry_complete=False, netbox_complete=False)
    assert value["blockers"] == [
        {"code": "ATOMIC_NETBOX_GUARD_UNAVAILABLE", "objects": []},
        {"code": "REGISTRY_SNAPSHOT_INCOMPLETE", "objects": []},
        {"code": "NETBOX_SNAPSHOT_INCOMPLETE", "objects": []},
        {"code": "SOURCE_NOT_REMOVED", "objects": []},
        {"code": "SOURCE_OUTCOME_UNCONFIRMED", "objects": []},
        {"code": "CLUSTER_REUSED_BY_ACTIVE_SOURCE", "objects": ["cluster:5"]},
        {"code": "DEPENDENCY_NOT_PROVEN", "objects": ["device:99"]},
        {"code": "OWNED_OBJECT_OUTSIDE_PLACEMENT", "objects": ["ip:8"]},
        {"code": "UNPROVEN_OR_SHARED_OWNERSHIP", "objects": ["vm:1"]},
        {"code": "RETAINED_CHILD", "objects": ["cluster:5"]},
    ]
    assert value["candidates"] == ["cluster:5"]
    assert value["retained"] == ["vm:1"]


@pytest.fixture
def journal(monkeypatch):
    documents, events = {}, []

    class Store:
        def __init__(self, root):
            self.root, self.path = Path(root), Path(root) / "state.json"

        def locked(self):
            events.append("store-lock")
            return nullcontext()

        def write(self, payload):
            events.append("write")
            documents[self.path] = deepcopy(payload)

    def read(path):
        events.append("read")
        if path not in documents:
            raise FileNotFoundError()
        return deepcopy(documents[path])

    def lock(path):
        events.append("apply-lock")
        return nullcontext()

    monkeypatch.setattr(module, "BootstrapStore", Store)
    monkeypatch.setattr(module, "read_journal", read)
    monkeypatch.setattr(module, "apply_lock", lock)
    return module.RetirementReviewJournal("/fixture", "/fixture/lock"), events


def test_journal_replay_and_conflict_preserve_original_payload(journal):
    store, events = journal
    identifier = str(UUID(int=1))
    value = review()
    saved = store.record(identifier, "operator", value)
    assert saved["review"] == value
    assert saved["digest"] == module.fingerprint(value)
    assert store.record(identifier, "operator", value) == saved
    with pytest.raises(module.RetirementBlocked, match="REVIEW_REQUEST_CONFLICT"):
        store.record(identifier, "another", value)
    assert events == [
        "apply-lock",
        "store-lock",
        "read",
        "write",
        "apply-lock",
        "store-lock",
        "read",
        "apply-lock",
        "store-lock",
        "read",
    ]


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("executable", True, "ATOMIC_NETBOX_GUARD_UNAVAILABLE"),
        ("format", 2, "Invalid review fields"),
        ("registry_fingerprint", "bad", "Invalid review fingerprint"),
        ("source_instance", "!", "Invalid review identity"),
    ],
)
def test_invalid_review_never_acquires_locks(journal, field, value, error):
    store, events = journal
    document = review()
    document[field] = value
    with pytest.raises((ValueError, module.RetirementBlocked), match=error):
        store.record(str(UUID(int=1)), "operator", document)
    assert events == []
