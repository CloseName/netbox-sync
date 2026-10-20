"""Account lifecycle ordering and literal receipt flags are stable."""

from contextlib import contextmanager
from copy import deepcopy
import pytest
from netbox_sync import selectel_lifecycle_control as lifecycle
from netbox_sync import selectel_control as control
from netbox_sync import selectel_runner as runner
from tests.test_selectel_lifecycle_control import env, data


@pytest.mark.parametrize("operation", ["activate", "detach"])
def test_confirmed_receipt_preserves_credentials_and_operation_specific_status(env, operation):
    store, path, saved, calls, answers = env
    saved[path].update(deleted=True, status="attention", error="old")
    request = data()
    request["operation"] = operation
    answers.append({"writes_performed": True})
    result = lifecycle.handle(store, "lock", "lifecycle-execute", request)
    assert result == {"writes_performed": True}
    assert saved[path]["password"] == "secret"
    assert "lifecycle_pending" not in saved[path]
    assert saved[path]["enabled"] is False
    assert saved[path]["next_run"] is None
    if operation == "activate":
        assert (saved[path]["deleted"], saved[path]["status"], saved[path]["error"]) == (False, "configured", None)
    else:
        assert (saved[path]["deleted"], saved[path]["status"], saved[path]["error"]) == (True, "attention", "old")


@pytest.mark.parametrize(
    "receipt",
    [
        {"writes_performed": 1},
        {"rolled_back": 1, "writes_performed": False},
        {"rolled_back": True, "writes_performed": 0},
    ],
)
def test_non_boolean_receipt_flags_never_confirm_write_or_rollback(env, receipt):
    store, path, saved, calls, answers = env
    answers.append(receipt)
    result = lifecycle.handle(store, "lock", "lifecycle-execute", data())
    assert result["error"] == "LIFECYCLE_UNCONFIRMED"
    assert result["pending"] == saved[path]["lifecycle_pending"]
    assert saved[path]["password"] == "secret"


def test_nonce_is_durable_before_child_and_all_locks_survive_receipt_write(env, monkeypatch):
    store, path, saved, calls, answers = env
    events = []

    @contextmanager
    def lock(name):
        events.append(("enter", name))
        try:
            yield
        finally:
            events.append(("exit", name))

    monkeypatch.setattr(lifecycle, "apply_lock", lock)
    store.locked = lambda: lock("store")

    def write(target, value):
        events.append(("write", "lifecycle_pending" in value))
        saved[target] = deepcopy(value)

    monkeypatch.setattr(control, "write", write)

    def child(value, timeout):
        assert saved[path]["lifecycle_pending"] == value["payload"]
        assert timeout == 90
        events.append(("child", value["operation"]))
        return {"writes_performed": True}

    monkeypatch.setattr(runner, "child", child)
    lifecycle.handle(store, "lock", "lifecycle-execute", data())
    collection = str(path.parent / "collection.lock")
    assert events == [
        ("enter", collection),
        ("enter", "lock"),
        ("enter", "store"),
        ("write", True),
        ("child", "lifecycle-execute"),
        ("write", False),
        ("exit", "store"),
        ("exit", "lock"),
        ("exit", collection),
    ]
