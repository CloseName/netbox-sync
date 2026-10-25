"""Read-only Guard reconciliation; no collection, import replay or inferred success."""

import os
import re
import time
from uuid import UUID
from .selectel_result import confirmed_import


def compatible(value):
    """Require the explicit versioned Selectel protocol before any provider reads."""
    return (
        isinstance(value, dict)
        and value.get("ready") is True
        and type(value.get("selectel_protocol")) is int
        and value["selectel_protocol"] == 1
        and value.get("receipt_lookup") is True
    )


def reconciled_state(state, evidence, instance, *, now):
    """Only an exact intent/namespace-bound receipt resolves the uncertain state."""
    updated = dict(state)
    outcome = "unavailable"
    if (
        isinstance(evidence, dict)
        and type(evidence.get("protocol")) is int
        and evidence["protocol"] == 1
        and evidence.get("account") == state["account"]
        and evidence.get("run_id") == state.get("run_id")
    ):
        outcome = evidence.get("outcome")
        if outcome not in ("committed", "not_found", "partial_evidence", "conflict", "busy"):
            outcome = "unavailable"
        if outcome == "committed":
            if not state.get("import_digest") or not state.get("import_instance"):
                outcome = "intent_unavailable"
            elif (
                state["import_instance"] != instance
                or evidence.get("digest") != state["import_digest"]
                or not confirmed_import(evidence.get("result"), state["account"])
            ):
                outcome = "conflict"
            else:
                # A retained summary can belong to an older run; do not attach its coverage.
                updated.update(
                    status="completed", error=None, next_run=None, summary={**evidence["result"], "products": []}
                )
    updated["reconciliation"] = {"outcome": outcome, "checked_at": now, "run_id": state.get("run_id")}
    return updated


def reconcile(store, lock_path, account):
    """Serialize with imports/lifecycle; read the existing receipt, never POST to Guard."""
    from .bootstrap_state import runtime_netbox
    from .selectel_control import read, write, root, public, running
    from .selectel_runner import child
    from .source_lifecycle import apply_lock, LifecycleError

    if not isinstance(account, str) or not re.fullmatch(r"[0-9]{1,20}", account):
        return {"error": "CONTROL_REQUEST_INVALID"}
    base = root(store)
    try:
        with (
            apply_lock(str(base / "collection.lock")),
            apply_lock(str(base / (account + ".lock"))),
            apply_lock(lock_path),
        ):
            with store.locked():
                path = base / (account + ".json")
                state = read(path)
                if running(state) or state.get("lifecycle_pending") or state.get("deleted"):
                    return {"error": "RUN_ACTIVE"}
                if (
                    state.get("error") not in ("IMPORT_UNCONFIRMED", "RUN_INTERRUPTED")
                    and state.get("status") != "running"
                ):
                    return public(state)
                # An interrupted process is not evidence that no writes committed.
                if state.get("status") == "running":
                    state.update(status="attention", error="RUN_INTERRUPTED", next_run=None)
                nonce = str(UUID(state["run_id"]))
                url, _ = runtime_netbox(store.path, "read")
                instance = os.environ.get("NETBOX_SYNC_GUARD_INSTANCE", "")
                access = dict(url=url, token=read(base / "netbox-token.json")["token"], guard_instance=instance)
                if compatible(child(dict(operation="preflight", **access), 90)):
                    evidence = child(dict(operation="receipt", account=account, run_id=nonce, **access), 90)
                else:
                    evidence = {}
                updated = reconciled_state(state, evidence, instance, now=time.time())
                write(path, updated)
                return public(updated)
    except LifecycleError:
        return {"error": "LIFECYCLE_BUSY"}


def main():
    """Updater entrypoint inside the bootstrap container; output contains only evidence codes."""
    import json
    from .bootstrap_state import BootstrapStore, runtime_netbox
    from .selectel_control import read, root
    from .selectel_runner import child

    store = BootstrapStore(os.environ.get("NETBOX_SYNC_NETBOX_STATE_DIR", "/var/lib/netbox-sync/netbox"))
    lock = os.environ.get("NETBOX_SYNC_APPLY_LOCK_PATH", "/run/netbox-sync-lock/apply.lock")
    base = root(store)
    accounts = sorted(p.stem for p in base.glob("*.json") if re.fullmatch(r"[0-9]{1,20}", p.stem))
    if not accounts:
        print(json.dumps({"compatible": True, "accounts": []}))
        return
    url, _ = runtime_netbox(store.path, "read")
    ready = child(
        dict(
            operation="preflight",
            url=url,
            token=read(base / "netbox-token.json")["token"],
            guard_instance=os.environ.get("NETBOX_SYNC_GUARD_INSTANCE", ""),
        ),
        90,
    )
    if not compatible(ready):
        raise SystemExit("SELECTEL_GUARD_INCOMPATIBLE")
    results = []
    for account in accounts:
        result = reconcile(store, lock, account)
        results.append(
            {"account": account, "error": result.get("error"), "reconciliation": result.get("reconciliation")}
        )
    print(json.dumps({"compatible": True, "accounts": results}))


if __name__ == "__main__":
    main()
