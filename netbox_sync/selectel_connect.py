"""Explicit first collection, with durable request replay and connection scope."""

from .local_control import ControlError


def connect(store, lock_path, base, path, state, data):
    """Caller holds the store lock; credential editing never enters this path."""
    from .api.selectel import Connection
    from .selectel_control import _save_account, launch, public, read, running, write

    parsed = Connection(**data)
    request_id = str(parsed.request_id)
    generation = str(parsed.connection_generation) if parsed.connection_generation else None
    if generation != state.get("connection_generation"):
        return {"error": "CONNECTION_REVIEW_STALE"}
    if state.get("error") in ("IMPORT_UNCONFIRMED", "RUN_INTERRUPTED"):
        return {"error": "IMPORT_UNCONFIRMED"}
    if state.get("status") == "running" and not running(state):
        return {"error": "RUN_INTERRUPTED"}
    if state.get("connect_request_id") == request_id:
        # A lost HTTP response or delayed double click must never collect twice.
        return public(state)
    if state.get("password"):
        return {"error": "ACCOUNT_ALREADY_CONNECTED"}
    if not (base / "netbox-token.json").is_file():
        return {"error": "SETUP_REQUIRED"}
    if any(running(read(p)) for p in base.glob("[0-9]*.json")):
        return {"error": "COLLECTION_BUSY"}
    credentials = {k: data[k] for k in ("account", "name", "username", "password")}
    result = _save_account(base, path, state, credentials)
    if result.get("error"):
        return result
    if not state.get("password"):
        raise ControlError("CONTROL_REQUEST_INVALID")
    state.update(connect_request_id=request_id, enabled=True, schedule={"kind": "off"}, next_run=None)
    write(path, state)
    # The existing runner performs fresh provider collection and native matching.
    return launch(store, lock_path, path, state)
