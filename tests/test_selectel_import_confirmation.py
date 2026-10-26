"""An HTTP/child success alone must not confirm an account import."""

from copy import deepcopy
import pytest
from netbox_sync import selectel_runner as module
from tests.test_selectel_runner_order_contract import runner


def receipt():
    return dict(account="29916", servers=2, matched=1, unmatched=1,
                registry_resources=3, retained=0, placement_pending=[],
                replayed=False, writes_performed=True, native_mode="registry_only")


def test_safe_refusal_diagnostic_survives_to_public_account(runner, monkeypatch):
    from netbox_sync.selectel_control import public
    state, _, _, _ = runner
    original = module.child
    response = {'error': 'NETBOX_IMPORT_REFUSED', 'import_diagnostic': {
        'reason': 'OBJECT_VALIDATION', 'http_status': 409, 'password': 'PRIVATE'}}
    monkeypatch.setattr(module, 'child', lambda value, timeout:
                        deepcopy(response) if value['operation'] == 'import' else original(value, timeout))
    module.main()
    assert state['error'] == 'NETBOX_IMPORT_REFUSED'
    assert public(state)['import_diagnostic'] == {'reason': 'OBJECT_VALIDATION', 'http_status': 409}
    assert 'PRIVATE' not in str(public(state))


@pytest.mark.parametrize("response", [{}, {"ready": True}, {"account": "29916"},
    {"error": None}, {"error": ""}, {"error": "unknown"}, {"error": []},
    {**receipt(), "account": "435835"}, {**receipt(), "servers": True},
    {**receipt(), "matched": -1}, {**receipt(), "writes_performed": "yes"},
    {**receipt(), "native_mode": "automatic"}])
def test_invalid_import_response_preserves_uncertainty(runner, monkeypatch, response):
    state, _, events, _ = runner
    original = module.child
    def child(value, timeout):
        if value["operation"] == "import":
            events.append(("import", timeout))
            return deepcopy(response)
        return original(value, timeout)
    monkeypatch.setattr(module, "child", child)
    module.main()
    assert state["status"] == "attention"
    assert state["error"] == "IMPORT_UNCONFIRMED"
    assert state["next_run"] is None
    assert "summary" not in state
    assert [op for op, _ in events].count("import") == 1


@pytest.mark.parametrize("replayed", [False, True])
def test_complete_account_result_confirms_import(runner, monkeypatch, replayed):
    state, _, _, _ = runner
    original = module.child
    result = {**receipt(), "replayed": replayed}
    monkeypatch.setattr(module, "child", lambda value, timeout:
                        deepcopy(result) if value["operation"] == "import" else original(value, timeout))
    module.main()
    assert state["status"] == "completed"
    assert state["summary"]["account"] == "29916"
