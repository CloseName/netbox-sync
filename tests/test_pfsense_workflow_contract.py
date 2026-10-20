"""pfSense sessions close before appliance work and progress survives failed collection."""

from contextlib import contextmanager, nullcontext
from types import SimpleNamespace as NS
import pytest
from netbox_sync import pfsense_connect as module


@pytest.fixture
def workflow(monkeypatch):
    events, posts = [], []
    state = NS(fail_collect=False, matched=True)

    def post(url, **kwargs):
        operation = "preflight" if "preflight" in url else "import"
        events.append(operation)
        posts.append(kwargs)
        return NS(status_code=200, json=lambda: {"status": "READY" if operation == "preflight" else "SAVED"})

    @contextmanager
    def session():
        events.append("session-enter")
        try:
            yield NS(post=post)
        finally:
            events.append("session-exit")

    monkeypatch.setattr(module.requests, "Session", session)
    monkeypatch.setattr(module, "configure_session", lambda *args: events.append("configure"))
    monkeypatch.setattr(module, "pinned_dns", lambda *args: nullcontext())
    monkeypatch.setattr(module, "EgressPolicy", lambda **kwargs: NS(resolve=lambda *args: ("nb.test", "192.0.2.1")))

    def fetch(session, url, token):
        events.append("vm" if "virtual-machines/" in url else "interfaces")
        return {"name": "pfSense"} if "virtual-machines/" in url else {"count": 0, "results": []}

    monkeypatch.setattr(module, "fetch", fetch)

    def setup(value, interfaces):
        events.append("setup")
        return {"ssh_port": 2222, "host_key": "pinned", "ignored": "private"}

    monkeypatch.setattr(module, "setup", setup)

    def collect(value, policy):
        events.append("collect")
        if state.fail_collect:
            raise module.SetupError("COLLECT_FAILED")
        return {"network": {}, "collected_at": "fixture"}

    monkeypatch.setattr(module, "collect", collect)
    monkeypatch.setattr(
        module, "build_preview", lambda *args: {"all_interfaces_matched": state.matched, "unmatched_vm_interfaces": []}
    )
    value = dict(
        url="https://nb.test",
        vm_id=1,
        read_token="read",
        apply_token="apply",
        guard_instance="guard",
        operation="connect",
        state={"ssh_port": 22, "host_key": "old", "interval_minutes": 30},
        data={"interval_minutes": 10},
        policy={},
    )
    return value, state, events, posts


@pytest.mark.parametrize("operation,port,interval", [("connect", 2222, 600), ("collect", 22, 1800)])
def test_sessions_and_interval_follow_operation_contract(workflow, operation, port, interval):
    value, state, events, posts = workflow
    value["operation"] = operation
    progress = {}
    result = module.run(value, progress)
    assert result["ssh_port"] == progress["ssh_port"] == port
    assert posts[-1]["json"]["snapshot"]["collection_interval_seconds"] == interval
    assert events == ["session-enter", "configure", "vm", "interfaces", "preflight", "session-exit"] + (
        ["setup"] if operation == "connect" else []
    ) + ["collect", "session-enter", "configure", "import", "session-exit"]
    assert "ignored" not in progress
    assert value["state"]["ssh_port"] == 22


@pytest.mark.parametrize("failure,error", [("collect", "COLLECT_FAILED"), ("match", "VM_IDENTITY_MISMATCH")])
def test_collection_or_matching_failure_keeps_progress_without_import(workflow, failure, error):
    value, state, events, posts = workflow
    state.fail_collect, state.matched = failure == "collect", failure != "match"
    progress = {}
    with pytest.raises(module.SetupError, match=error):
        module.run(value, progress)
    assert progress == {"ssh_port": 2222, "host_key": "pinned"}
    assert len(posts) == 1
    assert events[-1] == "collect"
