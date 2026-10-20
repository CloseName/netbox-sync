"""Durable, idempotent account lifecycle coordinator; no credential response."""

import os
import re
from uuid import uuid4
from .bootstrap_state import runtime_netbox
from .source_lifecycle import apply_lock, LifecycleError


def handle(store, lock_path, operation, data):
    from .selectel_control import root, read, write, running
    from .selectel_runner import child

    account = data.get("account") if isinstance(data, dict) else None
    if not isinstance(account, str) or not re.fullmatch(r"[0-9]{1,20}", account):
        return {"error": "CONTROL_REQUEST_INVALID"}
    allowed = {"account", "operation", "key"}
    if operation == "lifecycle-execute":
        allowed |= {"fingerprint", "confirmed"}
    if set(data) - allowed or data.get("operation") not in ("delete", "detach", "activate"):
        return {"error": "CONTROL_REQUEST_INVALID"}
    if operation == "lifecycle-execute" and data.get("confirmed") is not True:
        return {"error": "LIFECYCLE_CONFIRMATION_REQUIRED"}
    base = root(store)
    try:
        with apply_lock(str(base / "collection.lock")), apply_lock(lock_path), store.locked():
            path = base / (account + ".json")
            if not path.exists():
                return {"error": "SETUP_REQUIRED"}
            state = read(path)
            if running(state):
                return {"error": "RUN_ACTIVE"}
            if state.get("enabled", True):
                return {"error": "DISABLE_ACCOUNT_FIRST"}
            if not (base / "netbox-token.json").is_file():
                return {"error": "SETUP_REQUIRED"}
            url, _ = runtime_netbox(store.path, "read")
            access = {
                "url": url,
                "token": read(base / "netbox-token.json")["token"],
                "guard_instance": os.environ.get("NETBOX_SYNC_GUARD_INSTANCE", ""),
            }
            payload = {"account": account, "operation": data["operation"], "key": data.get("key")}
            pending = state.get("lifecycle_pending")
            if operation == "lifecycle-review":
                if pending:
                    return {"error": "LIFECYCLE_UNCONFIRMED", "pending": pending}
                return child(dict(operation=operation, payload=payload, **access), 90)
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
            if result.get("rolled_back") is True and result.get("writes_performed") is False:
                state.pop("lifecycle_pending", None)
                write(path, state)
                return result
            if result.get("writes_performed") is not True:
                # Even a timeout may follow a committed transaction. Keep the nonce.
                return {"error": "LIFECYCLE_UNCONFIRMED", "pending": payload}
            state.pop("lifecycle_pending", None)
            if data["operation"] == "delete":
                state = {
                    "account": account,
                    "name": state.get("name", account),
                    "deleted": True,
                    "enabled": False,
                    "status": "deleted",
                    "next_run": None,
                }
            elif data["operation"] == "activate":
                state.update(deleted=False, status="configured", error=None)
            write(path, state)
            return result
    except LifecycleError:
        return {"error": "LIFECYCLE_BUSY"}
