"""Experimental account dispatch preserves lock, uncertainty and scheduling rules."""

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace as NS
import pytest
from netbox_sync import selectel_control as module
from netbox_sync.api.auth import AuthClient


@pytest.fixture
def account(tmp_path, monkeypatch):
    path = tmp_path / "29916.json"
    path.touch()
    (tmp_path / "netbox-token.json").touch()
    state = {
        "account": "29916",
        "name": "fixture",
        "username": "reader",
        "password": "private",
        "status": "configured",
        "enabled": True,
        "schedule": {"kind": "off"},
    }
    events = []

    @contextmanager
    def locked():
        events.append("lock")
        try:
            yield
        finally:
            events.append("unlock")

    def write(target, value):
        events.append("write")
        state.clear()
        state.update(deepcopy(value))

    monkeypatch.setattr(AuthClient, "call", lambda *args, **kwargs: events.append(("authorize", kwargs["audit"])))
    monkeypatch.setattr(module, "root", lambda store: tmp_path)
    monkeypatch.setattr(module, "runtime_netbox", lambda *args: ("https://netbox.test/", "private-token"))
    monkeypatch.setattr(module, "read", lambda target: deepcopy(state))
    monkeypatch.setattr(module, "write", write)
    monkeypatch.setattr(module, "running", lambda current: current.get("live", False))
    monkeypatch.setattr(module, "launch", lambda *args: events.append("launch") or {"launched": True})
    store = NS(locked=locked, path=tmp_path / "state", root=tmp_path)

    def call(operation, data=None):
        return module.handle(
            store,
            "lock",
            {
                "action": "selectel",
                "operation": operation,
                "session": "fixture",
                "data": {"account": "29916", **(data or {})},
            },
        )

    return call, state, events


def test_listing_interrupted_run_projects_attention_without_persisting(account):
    call, state, events = account
    state.update(status="running", run_id="old", next_run=123)
    before = deepcopy(state)
    result = call("list")
    assert result["items"][0]["error"] == "RUN_INTERRUPTED"
    assert result["items"][0]["next_run"] is None
    assert result["items"][0]["url"] == "https://netbox.test/plugins/netbox-sync-guard/providers/29916/"
    assert result["import_ready"] is True
    assert state == before
    assert events == [("authorize", False), "lock", "unlock"]


@pytest.mark.parametrize("error", ["IMPORT_UNCONFIRMED", "RUN_INTERRUPTED"])
def test_saving_credentials_never_resolves_uncertain_import(account, error):
    call, state, events = account
    state.update(status="attention", error=error)
    result = call("save", {"name": " new ", "username": " reader ", "password": "new-private"})
    assert result["status"] == "attention" and result["error"] == error
    assert result["name"] == "new" and result["username"] == "reader"
    assert "password" not in result
    assert state["password"] == "new-private"
    assert events == [("authorize", True), "lock", "write", "unlock"]


@pytest.mark.parametrize(
    "operation,data", [("enabled", {"enabled": False}), ("schedule", {"schedule": {"kind": "off"}})]
)
def test_schedule_and_disable_remain_available_during_running_job(account, operation, data):
    call, state, events = account
    state.update(status="running", live=True, run_id="original")
    result = call(operation, data)
    assert result["status"] == "running" and result["run_id"] == "original"
    assert events == [("authorize", True), "lock", "write", "unlock"]


@pytest.mark.parametrize(
    "change,code",
    [
        ({"lifecycle_pending": {"nonce": "old"}}, "LIFECYCLE_UNCONFIRMED"),
        ({"deleted": True}, "ACCOUNT_DELETED"),
        ({"enabled": False}, "ACCOUNT_DISABLED"),
        ({"error": "IMPORT_UNCONFIRMED"}, "IMPORT_UNCONFIRMED"),
    ],
)
def test_collect_refusals_do_not_launch_or_write(account, change, code):
    call, state, events = account
    state.update(change)
    assert call("collect") == {"error": code}
    assert events == [("authorize", True), "lock", "unlock"]


def test_lifecycle_delegation_is_authorized_before_separate_locking(account, monkeypatch):
    from netbox_sync import selectel_lifecycle_control

    call, state, events = account
    monkeypatch.setattr(
        selectel_lifecycle_control, "handle", lambda *args: events.append("lifecycle") or {"review": True}
    )
    assert call("lifecycle-review") == {"review": True}
    assert events == [("authorize", True), "lifecycle"]
