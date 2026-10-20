"""pfSense control keeps durable reservations and partial SSH preparation."""

from contextlib import contextmanager
from copy import deepcopy
from io import StringIO
import json
from types import SimpleNamespace as NS
import pytest
from netbox_sync import pfsense_control as module
from netbox_sync.api.auth import AuthClient


@pytest.fixture
def control(monkeypatch):
    state = dict(
        status="CONNECTED",
        key="private",
        host_key="ssh-ed25519 old",
        address="10.0.0.1",
        port=443,
        verify_tls=True,
        interval_minutes=10,
    )
    result = dict(collected_at=100, ssh_port=22, host_key="ssh-ed25519 new")
    events = []

    class Path:
        def __truediv__(self, name):
            return self

        def mkdir(self, **kwargs):
            pass

        def is_symlink(self):
            return False

        def exists(self):
            return True

        def stat(self):
            return NS(st_uid=0, st_mode=0o700)

    class Stream(StringIO):
        def fileno(self):
            return 7

    fakeos = NS(
        O_RDONLY=0,
        O_NOFOLLOW=0,
        environ={},
        open=lambda *args: 7,
        fdopen=lambda fd: Stream(json.dumps(state)),
        fstat=lambda fd: NS(st_uid=0, st_mode=0o600, st_size=100),
    )
    monkeypatch.setattr(module, "os", fakeos)
    monkeypatch.setattr(module, "collector_username", lambda: "netbox-sync")
    monkeypatch.setattr(module.time, "time", lambda: 1000)

    def write(path, value):
        events.append(("write", deepcopy(value)))
        state.clear()
        state.update(deepcopy(value))

    monkeypatch.setattr(module, "atomic", write)
    monkeypatch.setattr(
        AuthClient, "call", lambda self, op, **kw: events.append(op) or {"effective": {"allowed": True}}
    )

    @contextmanager
    def lock(path):
        events.append("lock")
        try:
            yield
        finally:
            events.append("unlock")

    monkeypatch.setattr(module, "apply_lock", lock)
    monkeypatch.setattr(
        module, "runtime_netbox", lambda path, mode: events.append(mode) or ("https://netbox.test", mode)
    )
    monkeypatch.setattr(module, "_safe_environment", lambda: {})
    monkeypatch.setattr(module, "_drop_privileges", lambda *args: None)

    @contextmanager
    def child(*args, **kwargs):
        def communicate(raw, timeout):
            events.append(("child", json.loads(raw), timeout))
            return json.dumps(result).encode(), b""

        yield NS(communicate=communicate, returncode=0)

    monkeypatch.setattr(module, "child_process", child)
    store = NS(root=Path(), path="fixture")

    def call(operation="collect", data=None, scheduled_policy=None):
        return module.handle(
            store,
            "lock",
            dict(action="pfsense", operation=operation, vm_id=7, session="fixture", data=data or {}),
            scheduled_policy=scheduled_policy,
        )

    return call, state, result, events


def test_collection_reservation_precedes_tokens_and_child(control):
    call, state, result, events = control
    value = call()
    assert [e[0] if isinstance(e, tuple) else e for e in events] == [
        "authorize",
        "probe.authorize",
        "lock",
        "write",
        "read",
        "apply",
        "child",
        "write",
        "unlock",
    ]
    assert events[3][1]["status"] == "RUNNING"
    assert events[3][1]["next_attempt"] == 1600
    assert value["status"] == "CONNECTED" and value["ssh_port"] == 22
    assert "key" not in value


def test_failed_import_retains_successful_ssh_preparation(control):
    call, state, result, events = control
    result["error"] = "IMPORT_UNCONFIRMED"
    value = call()
    assert value["status"] == "ATTENTION" and value["error"] == "IMPORT_UNCONFIRMED"
    assert state["host_key"] == "ssh-ed25519 new" and state["ssh_port"] == 22


def test_status_projects_stale_run_without_write_or_policy_probe(control):
    call, state, result, events = control
    state.update(status="RUNNING", started_at=0)
    assert call("status")["error"] == "OUTCOME_UNKNOWN"
    assert state["status"] == "RUNNING"
    assert events == ["authorize"]


def test_scheduled_not_due_skips_auth_and_child(control):
    call, state, result, events = control
    state.update(sync_enabled=True, next_attempt=2000)
    assert call(scheduled_policy={})["status"] == "CONNECTED"
    assert events == ["lock", "unlock"]


@pytest.mark.parametrize("prepared", [False, True])
def test_schedule_requires_prepared_ssh_and_never_collects(control, prepared):
    call, state, result, events = control
    if not prepared:
        state.pop("host_key")
    value = call("schedule", dict(policy_revision=1, sync_enabled=False, interval_minutes=20))
    if prepared:
        assert value["sync_enabled"] is False and value["next_attempt"] == 2200
        assert any(isinstance(e, tuple) and e[0] == "write" for e in events)
    else:
        assert value == {"error": "CONNECT_REQUIRED"}
        assert not any(isinstance(e, tuple) for e in events)
    assert not any(isinstance(e, tuple) and e[0] == "child" for e in events)


@pytest.mark.parametrize("changed", [False, True])
def test_connect_reuses_key_and_rejects_changed_endpoint(control, changed):
    call, state, result, events = control
    data = dict(
        address="10.0.0.2" if changed else "10.0.0.1",
        port=443,
        verify_tls=True,
        username="reader",
        password="fixture-secret",
        policy_revision=1,
        sync_enabled=False,
        interval_minutes=20,
    )
    value = call("connect", data)
    assert state["key"] == "private"
    if changed:
        assert value == {"error": "ENDPOINT_CHANGED", "status": "CONNECTED"}
        assert not any(isinstance(e, tuple) for e in events)
    else:
        child = next(e for e in events if isinstance(e, tuple) and e[0] == "child")
        assert child[1]["data"]["password"] == "fixture-secret"
        assert value["sync_enabled"] is False and value["interval_minutes"] == 20
