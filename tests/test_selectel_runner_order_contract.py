"""Selectel runner retains early-return and uncertain-import boundaries."""

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from netbox_sync import selectel_runner as module


@pytest.fixture
def runner(monkeypatch):
    state = {
        "account": "29916",
        "run_id": "run-fixture",
        "username": "reader",
        "password": "private",
        "enabled": True,
        "next_run": 123,
    }
    control = NS(failure=None, change=None, ready=True, token_reads=0)
    events, writes = [], []
    store = NS(path=Path("/fixture/state"), locked=lambda: nullcontext())
    monkeypatch.setattr(module, "BootstrapStore", lambda path: store)
    monkeypatch.setattr(module, "root", lambda store: Path("/fixture/selectel"))
    monkeypatch.setattr(module.sys, "argv", ["runner", "/fixture", "29916", "run-fixture", "/fixture/apply.lock"])
    monkeypatch.setattr(module, "apply_lock", lambda path: nullcontext())
    monkeypatch.setattr(module, "runtime_netbox", lambda *args: ("https://netbox.test", "unused"))
    monkeypatch.setattr(module.time, "time", lambda: 456)

    def read(path):
        if path.name == "netbox-token.json":
            control.token_reads += 1
            if control.failure == "second-token" and control.token_reads == 2:
                raise RuntimeError("private")
            return {"token": "private-token"}
        return deepcopy(state)

    def write(path, value):
        writes.append(deepcopy(value))
        state.clear()
        state.update(deepcopy(value))

    def child(value, timeout):
        operation = value["operation"]
        events.append((operation, timeout))
        if control.failure == operation:
            raise RuntimeError("private")
        if operation == "preflight":
            return {"ready": control.ready}
        if operation == "collect":
            if control.change == "disabled":
                state["enabled"] = False
            if control.change == "run":
                state["run_id"] = "another-run"
            return {"document": {}, "registry": {}, "summary": {"collected": 1}}
        return dict(account="29916", servers=2, matched=1, unmatched=1,
                    registry_resources=2, retained=0, placement_pending=[],
                    replayed=False, writes_performed=True, native_mode="registry_only")

    monkeypatch.setattr(module, "read", read)
    monkeypatch.setattr(module, "write", write)
    monkeypatch.setattr(module, "child", child)
    return state, control, events, writes


def test_success_combines_summary_after_guarded_import(runner):
    state, control, events, writes = runner
    module.main()
    assert events == [("preflight", 90), ("collect", 2800), ("import", 90)]
    assert state["summary"] == dict(collected=1, account="29916", servers=2, matched=1, unmatched=1,
                                  registry_resources=2, retained=0, placement_pending=[],
                                  replayed=False, writes_performed=True, native_mode="registry_only")
    assert state["status"] == "completed" and state["error"] is None
    assert state["next_run"] == 123 and state["finished_at"] == 456
    assert len(writes) == 1


@pytest.mark.parametrize(
    "failure,error,due",
    [
        ("collect", "RUN_INTERRUPTED_OR_BUSY", 123),
        ("import", "IMPORT_UNCONFIRMED", None),
        ("second-token", "RUN_INTERRUPTED_OR_BUSY", 123),
    ],
)
def test_failure_classification_changes_only_after_import_started(runner, failure, error, due):
    state, control, events, writes = runner
    control.failure = failure
    module.main()
    assert state["error"] == error and state["next_run"] == due
    assert state["status"] == "attention" and state["finished_at"] == 456
    assert len(writes) == 1


def test_unready_preflight_never_collects(runner):
    state, control, events, writes = runner
    control.ready = False
    module.main()
    assert events == [("preflight", 90)]
    assert state["error"] == "SETUP_REQUIRED"


def test_disable_during_collection_blocks_import_and_finishes_once(runner):
    state, control, events, writes = runner
    control.change = "disabled"
    module.main()
    assert events == [("preflight", 90), ("collect", 2800)]
    assert state["error"] == "ACCOUNT_DISABLED" and state["finished_at"] == 456
    assert len(writes) == 1


def test_replaced_run_after_collection_has_no_write_or_import(runner):
    state, control, events, writes = runner
    control.change = "run"
    module.main()
    assert events == [("preflight", 90), ("collect", 2800)]
    assert writes == []


def test_initial_run_mismatch_never_starts_child(runner):
    state, control, events, writes = runner
    state["run_id"] = "another-run"
    module.main()
    assert events == writes == []
