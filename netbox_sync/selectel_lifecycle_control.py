"""Durable, idempotent account lifecycle coordinator; no credential response."""

import os
import re
from uuid import UUID, uuid4
from .bootstrap_state import runtime_netbox
from .source_lifecycle import apply_lock, LifecycleError


def _request_error(operation, data):
    """Validate lifecycle confirmation before acquiring any account lock."""
    account = data.get("account") if isinstance(data, dict) else None
    if not isinstance(account, str) or not re.fullmatch(r"[0-9]{1,20}", account):
        return {"error": "CONTROL_REQUEST_INVALID"}
    allowed = {"account", "operation", "key"}
    if operation == "lifecycle-execute":
        allowed |= {"fingerprint", "confirmed"}
    if set(data) - allowed or data.get("operation") not in ("delete", "detach", "activate", "baseline"):
        return {"error": "CONTROL_REQUEST_INVALID"}
    if operation == "lifecycle-execute" and data.get("confirmed") is not True:
        return {"error": "LIFECYCLE_CONFIRMATION_REQUIRED"}
    return None


def _account_error(base, state):
    """Require a stopped, disabled account and an existing integration token."""
    from .selectel_control import running

    if running(state):
        return {"error": "RUN_ACTIVE"}
    if state.get("status") == "running":
        return {"error": "RUN_INTERRUPTED"}
    if state.get("enabled", True):
        return {"error": "DISABLE_ACCOUNT_FIRST"}
    if not (base / "netbox-token.json").is_file():
        return {"error": "SETUP_REQUIRED"}
    return None


def _finish_lifecycle(path, state, data, payload, result):
    """Clear the durable nonce only after a literal confirmed receipt."""
    from .selectel_control import write

    if result.get("rolled_back") is True and result.get("writes_performed") is False:
        state.pop("lifecycle_pending", None)
        write(path, state)
        return result
    if result.get("writes_performed") is not True:
        # Even a timeout may follow a committed transaction. Keep the nonce.
        return {"error": "LIFECYCLE_UNCONFIRMED", "pending": payload}
    if data["operation"] == "baseline":
        from .selectel_baseline import finish

        return finish(path, state, payload, result)
    state.pop("lifecycle_pending", None)
    if data["operation"] == "delete":
        state = {
            "account": data["account"],
            "name": state.get("name", data["account"]),
            "deleted": True,
            "enabled": False,
            "status": "deleted",
            "next_run": None,
        }
    elif data["operation"] == "activate":
        state.update(deleted=False, status="configured", error=None, connection_generation=payload["nonce"])
    write(path, state)
    return result


def _review_lifecycle(operation, payload, pending, access):
    """Review only when no earlier lifecycle outcome remains unresolved."""
    from .selectel_runner import child

    if pending:
        return {"error": "LIFECYCLE_UNCONFIRMED", "pending": pending}
    return child(dict(operation=operation, payload=payload, **access), 90)


def _execute_lifecycle(path, state, operation, data, access):
    """Persist or replay the confirmed payload before invoking the child."""
    from .selectel_control import write
    from .selectel_runner import child

    payload = {"account": data["account"], "operation": data["operation"], "key": data.get("key")}
    pending = state.get("lifecycle_pending")
    if operation == "lifecycle-review":
        return _review_lifecycle(operation, payload, pending, access)
    fingerprint = data.get("fingerprint")
    if not isinstance(fingerprint, str) or not re.fullmatch("[a-f0-9]{64}", fingerprint):
        return {"error": "CONTROL_REQUEST_INVALID"}
    payload["fingerprint"] = fingerprint
    if pending:
        if any(pending.get(k) != v for k, v in payload.items()):
            return {"error": "LIFECYCLE_UNCONFIRMED", "pending": pending}
        payload = pending
    else:
        payload["nonce"] = str(uuid4())
        state.update(lifecycle_pending=payload, enabled=False, next_run=None)
        write(path, state)
    result = child(dict(operation=operation, payload=payload, **access), 90)
    return _finish_lifecycle(path, state, data, payload, result)


def _handle_account(store, base, operation, data):
    """Run one lifecycle action under the caller-held collection and store locks."""
    from .selectel_control import read

    account = data["account"]
    path = base / (account + ".json")
    if not path.exists():
        return {"error": "SETUP_REQUIRED"}
    state = read(path)
    if data.get("operation") == "activate" and not state.get("deleted"):
        return {"error": "ACCOUNT_NOT_DELETED"}
    if data.get("operation") != "baseline" and state.get("error") in ("IMPORT_UNCONFIRMED", "RUN_INTERRUPTED"):
        return {"error": "IMPORT_UNCONFIRMED"}
    if data.get("operation") == "baseline":
        if state.get("error") not in ("IMPORT_UNCONFIRMED", "RUN_INTERRUPTED") or data.get("key") != state.get(
            "run_id"
        ):
            return {"error": "BASELINE_RUN_MISMATCH"}
        try:
            UUID(str(data["key"]))
        except (ValueError, TypeError):
            return {"error": "CONTROL_REQUEST_INVALID"}
    error = _account_error(base, state)
    if error is not None:
        return error
    url, _ = runtime_netbox(store.path, "read")
    access = {
        "url": url,
        "token": read(base / "netbox-token.json")["token"],
        "guard_instance": os.environ.get("NETBOX_SYNC_GUARD_INSTANCE", ""),
    }
    return _execute_lifecycle(path, state, operation, data, access)


def handle(store, lock_path, operation, data):
    """Persist confirmed account lifecycle intent and retain its nonce until the outcome is proved."""
    from .selectel_control import root

    error = _request_error(operation, data)
    if error is not None:
        return error
    base = root(store)
    try:
        with apply_lock(str(base / "collection.lock")), apply_lock(lock_path), store.locked():
            return _handle_account(store, base, operation, data)
    except LifecycleError:
        return {"error": "LIFECYCLE_BUSY"}
