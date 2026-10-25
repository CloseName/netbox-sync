"""Receipt reconciliation never converts missing evidence into permission to retry."""
from copy import deepcopy
import pytest

from netbox_sync import selectel_recovery as recovery

RUN = "f5f3efcc-436a-4caf-8d21-d5492ba94f4c"
INSTANCE = "85c0013b-6464-4d8a-aa66-2604623ffbcf"


def state():
    return dict(account="29916", run_id=RUN, status="attention", error="IMPORT_UNCONFIRMED",
                import_digest="a" * 64, import_instance=INSTANCE, password="PRIVATE",
                schedule={"kind": "off"}, next_run=None)


def receipt():
    return dict(protocol=1, account="29916", run_id=RUN, outcome="committed", digest="a" * 64,
                result=dict(account="29916", servers=1, matched=1, unmatched=0, registry_resources=1,
                            retained=0, native_mode="registry_only", placement_pending=[],
                            replayed=False, writes_performed=True))


@pytest.mark.parametrize("outcome", ["not_found", "partial_evidence", "conflict", "busy", "unknown"])
def test_unresolved_never_clears_error_or_retries(outcome):
    original = state()
    result = recovery.reconciled_state(original, {**receipt(), "outcome": outcome}, INSTANCE, now=123)
    assert result["error"] == "IMPORT_UNCONFIRMED"
    assert result["status"] == "attention"
    assert result["run_id"] == RUN
    assert result["next_run"] is None
    assert original == state()


@pytest.mark.parametrize("patch", [{"account": "435835"}, {"run_id": INSTANCE}, {"digest": "b" * 64},
                                   {"result": {}}, {"protocol": True}])
def test_wrong_or_malformed_receipt_remains_uncertain(patch):
    result = recovery.reconciled_state(state(), {**receipt(), **patch}, INSTANCE, now=123)
    assert result["error"] == "IMPORT_UNCONFIRMED"


def test_old_runs_without_persisted_intent_remain_blocked():
    old = state()
    del old["import_digest"]
    result = recovery.reconciled_state(old, receipt(), INSTANCE, now=123)
    assert result["error"] == "IMPORT_UNCONFIRMED"
    assert result["reconciliation"]["outcome"] == "intent_unavailable"


def test_namespace_change_never_confirms():
    result = recovery.reconciled_state(state(), receipt(), RUN, now=123)
    assert result["error"] == "IMPORT_UNCONFIRMED"


def test_exact_receipt_confirms_without_changing_schedule_or_finished_at():
    original = state()
    original["finished_at"] = 100
    result = recovery.reconciled_state(original, receipt(), INSTANCE, now=123)
    assert result["status"] == "completed" and result["error"] is None
    assert result["finished_at"] == 100
    assert result["next_run"] is None and result["schedule"] == {"kind": "off"}
    assert result["reconciliation"] == {"outcome": "committed", "checked_at": 123, "run_id": RUN}
    assert "PRIVATE" not in str(result["reconciliation"])


@pytest.mark.parametrize("value", [{"ready": True}, {}, {"ready": True, "selectel_protocol": True},
                                   {"ready": True, "selectel_protocol": 2}])
def test_legacy_or_unknown_guard_contract_is_not_compatible(value):
    assert not recovery.compatible(value)


def test_supported_guard_contract():
    assert recovery.compatible({"ready": True, "selectel_protocol": 1, "receipt_lookup": True})


def test_reconcile_reads_receipt_without_collection_or_import(monkeypatch, tmp_path):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from netbox_sync import selectel_control, selectel_runner, bootstrap_state, source_lifecycle
    current = state()
    operations = []
    monkeypatch.setattr(selectel_control, "root", lambda store: tmp_path)
    monkeypatch.setattr(selectel_control, "read", lambda path: {"token": "PRIVATE"} if path.name == "netbox-token.json" else deepcopy(current))
    monkeypatch.setattr(selectel_control, "write", lambda path, value: current.update(value))
    monkeypatch.setattr(bootstrap_state, "runtime_netbox", lambda *args: ("https://netbox.test", "unused"))
    monkeypatch.setattr(source_lifecycle, "apply_lock", lambda path: nullcontext())
    monkeypatch.setenv("NETBOX_SYNC_GUARD_INSTANCE", INSTANCE)
    def child(value, timeout):
        operations.append(value["operation"])
        return {"ready": True, "selectel_protocol": 1, "receipt_lookup": True} if value["operation"] == "preflight" else receipt()
    monkeypatch.setattr(selectel_runner, "child", child)
    result = recovery.reconcile(SimpleNamespace(path=tmp_path, locked=nullcontext), "lock", "29916")
    assert operations == ["preflight", "receipt"]
    assert result["status"] == "completed"
    assert "PRIVATE" not in str(result) and "import_digest" not in result


def test_receipt_api_preserves_uncertainty_as_successful_lookup():
    from types import SimpleNamespace
    from unittest.mock import patch
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from netbox_sync.api.selectel import routes
    app = FastAPI()
    app.include_router(routes(SimpleNamespace(bootstrap_socket="unused")))
    with patch("netbox_sync.api.selectel.control", return_value={"result": {
        "error": "IMPORT_UNCONFIRMED", "reconciliation": {"outcome": "not_found"}
    }}):
        result = TestClient(app).post("/api/v1/selectel/29916/reconcile")
    assert result.status_code == 200
    assert result.json()["error"] == "IMPORT_UNCONFIRMED"


def test_receipt_transport_is_get_only_and_unknown_operation_cannot_import(monkeypatch):
    from types import SimpleNamespace
    from netbox_sync import retirement_transport, selectel_collect
    calls = []
    client = SimpleNamespace(_request=lambda *args: calls.append(args) or receipt())
    monkeypatch.setattr(retirement_transport, "GuardClient", lambda *args: client)
    value = dict(operation="receipt", account="29916", run_id=RUN,
                 url="https://netbox.test", token="fixture", guard_instance=INSTANCE)
    selectel_collect.run(value)
    assert calls == [("GET", f"providers/accounts/29916/runs/{RUN}/")]
    with pytest.raises(ValueError):
        selectel_collect.run({**value, "operation": "unknown", "payload": {}})
    assert len(calls) == 1
