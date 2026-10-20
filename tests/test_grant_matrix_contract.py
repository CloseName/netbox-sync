"""Grant SQL remains ordered and confined to one owner transaction."""

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import pytest
from netbox_sync import deployment


def capture(monkeypatch, fail_at=None):
    statements, events = [], []

    class Cursor:
        def execute(self, statement):
            statements.append(statement.as_string())
            if len(statements) == fail_at:
                raise RuntimeError("fixture failure")

    @contextmanager
    def cursor():
        events.append("cursor-enter")
        try:
            yield Cursor()
        finally:
            events.append("cursor-exit")

    @contextmanager
    def connect(info):
        assert info == "fixture-owner"
        events.append("transaction-enter")
        try:
            yield SimpleNamespace(cursor=cursor)
        except Exception:
            events.append("rollback")
            raise
        else:
            events.append("commit")

    monkeypatch.setattr(deployment, "connection_info", lambda role, env: "fixture-owner" if role == "owner" else None)
    monkeypatch.setattr(deployment.psycopg, "connect", connect)
    return statements, events


def expected():
    return json.loads((Path(__file__).parent / "fixtures" / "grant-statements.json").read_text(encoding="utf8"))


def test_complete_grant_matrix_and_transaction_order(monkeypatch):
    statements, events = capture(monkeypatch)
    deployment.apply_grants({"NETBOX_SYNC_REGISTRY_SCHEMA": "fixture_schema"})
    assert statements == expected()
    assert events == ["transaction-enter", "cursor-enter", "cursor-exit", "commit"]


@pytest.mark.parametrize("fail_at", [1, 27, 60, 90])
def test_grant_failure_stops_and_rolls_back_original_transaction(monkeypatch, fail_at):
    statements, events = capture(monkeypatch, fail_at)
    with pytest.raises(RuntimeError, match="fixture failure"):
        deployment.apply_grants({"NETBOX_SYNC_REGISTRY_SCHEMA": "fixture_schema"})
    assert statements == expected()[:fail_at]
    assert events == ["transaction-enter", "cursor-enter", "cursor-exit", "rollback"]


def test_invalid_schema_is_rejected_before_connecting(monkeypatch):
    statements, events = capture(monkeypatch)
    with pytest.raises(deployment.DeploymentError, match="REGISTRY_SCHEMA is invalid"):
        deployment.apply_grants({"NETBOX_SYNC_REGISTRY_SCHEMA": "invalid;schema"})
    assert statements == events == []
