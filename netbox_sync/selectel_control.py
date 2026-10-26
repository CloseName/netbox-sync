"""Admin-only account control, durable root-owned secrets and asynchronous runs."""

import json
import os
import re
import stat
import subprocess
import sys
import time
from uuid import uuid4
from .local_control import ControlError
from .bootstrap_state import runtime_netbox

PUBLIC = (
    "account",
    "name",
    "username",
    "status",
    "started_at",
    "finished_at",
    "error",
    "summary",
    "run_id",
    "enabled",
    "schedule",
    "next_run",
    "trigger",
    "lifecycle_pending",
    "deleted",
    "reconciliation",
    "baseline_history",
)


def public(state):
    """Project the explicit public account fields while omitting stored credentials."""

    from .selectel_diagnostic import diagnostic

    value = {k: state[k] for k in PUBLIC if k in state}
    if diagnostic(state.get("import_diagnostic")):
        value["import_diagnostic"] = diagnostic(state["import_diagnostic"])
    return value


def running(state):
    """Recognize a recent launch reservation or matching Linux process command line."""

    if state.get("status") != "running":
        return False
    if time.time() - state.get("started_at", 0) > 3600:
        return False
    if time.time() - state.get("started_at", 0) < 5:
        return True
    try:
        from pathlib import Path

        return state["run_id"].encode() in Path("/proc", str(int(state["pid"])), "cmdline").read_bytes().split(b"\0")
    except (OSError, KeyError, ValueError, TypeError):
        return False


def read(path):
    """Read bounded private root-owned state without following a final symlink."""

    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if (
            info.st_uid
            or stat.S_IMODE(info.st_mode) != 0o600
            or not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_size > 131072
        ):
            raise ControlError("BOOTSTRAP_INVALID")
        return json.load(stream)


def write(path, value):
    """Atomically replace private account state and sync the file and containing directory."""

    tmp = path.parent / (uuid4().hex + ".tmp")
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if tmp.exists():
            tmp.unlink()


def root(store):
    """Create or validate the private root-owned Selectel state directory."""

    path = store.root / "selectel"
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid or stat.S_IMODE(info.st_mode) != 0o700:
        raise ControlError("BOOTSTRAP_INVALID")
    return path


def launch(store, lock_path, path, state, trigger="manual"):
    """Caller holds store.locked(). Persist reservation before spawning a child."""
    from .selectel_schedule import next_run

    now = time.time()
    state.update(status="running", started_at=now, error=None, run_id=str(uuid4()), trigger=trigger)
    for key in ("import_digest", "import_instance", "reconciliation", "import_diagnostic"):
        state.pop(key, None)
    state["next_run"] = next_run(state.get("schedule", {"kind": "off"}), now)
    write(path, state)
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-m",
                "netbox_sync.selectel_runner",
                str(store.root),
                state["account"],
                state["run_id"],
                str(lock_path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        state.update(status="attention", error="RUN_START_FAILED")
        write(path, state)
    else:
        # Failure to persist the PID is not proof that the child did not start.
        # Keep the durable running reservation and require reconciliation.
        state["pid"] = process.pid
        write(path, state)
    return public(state)


def _list_accounts(base, url):
    """Project account status without persisting interrupted-run observations."""
    items = []
    for p in sorted(base.glob("*.json")):
        if re.fullmatch(r"[0-9]{1,20}", p.stem):
            state = read(p)
            if state.get("status") == "running" and not running(state):
                state.update(status="attention", error="RUN_INTERRUPTED", next_run=None)
            items.append(
                {
                    **public(state),
                    "url": url.rstrip("/") + "/plugins/netbox-sync-guard/providers/" + p.stem + "/",
                }
            )
    return {"items": items, "import_ready": (base / "netbox-token.json").is_file()}


def _set_enabled(path, state, data):
    """Change activation while retaining any already-running job."""
    if set(data) != {"account", "enabled"} or type(data["enabled"]) is not bool:
        raise ControlError("CONTROL_REQUEST_INVALID")
    if not state:
        return {"error": "SETUP_REQUIRED"}
    if data["enabled"] and not state.get("password"):
        return {"error": "SETUP_REQUIRED"}
    from .selectel_schedule import next_run

    state["enabled"] = data["enabled"]
    state["next_run"] = next_run(state.get("schedule", {"kind": "off"}), time.time()) if data["enabled"] else None
    write(path, state)
    return public(state)


def _set_schedule(path, state, data):
    """Validate scheduling without blocking on an active collection."""
    if set(data) != {"account", "schedule"} or not state:
        raise ControlError("CONTROL_REQUEST_INVALID")
    from .selectel_schedule import validate, next_run

    try:
        schedule = validate(data["schedule"])
        due = next_run(schedule, time.time())
    except (ValueError, OverflowError):
        return {"error": "SCHEDULE_INVALID"}
    state.update(schedule=schedule, next_run=due if state.get("enabled", True) else None)
    write(path, state)
    return public(state)


def _save_account(base, path, state, data):
    """Save validated credentials without clearing uncertain import outcomes."""
    from .api.selectel import Account

    if not state and len(list(base.glob("[0-9]*.json"))) >= 100:
        return {"error": "ACCOUNT_LIMIT"}
    parsed = Account(**data)
    # Pydantic validates this descriptor into the declared field type.
    # pylint: disable-next=no-member
    if not parsed.name.strip() or not parsed.username.strip():
        raise ControlError("CONTROL_REQUEST_INVALID")
    state.update(
        account=parsed.account,
        # Pydantic validates this descriptor into the declared field type.
        # pylint: disable-next=no-member
        name=parsed.name.strip(),
        # Pydantic validates this descriptor into the declared field type.
        # pylint: disable-next=no-member
        username=parsed.username.strip(),
        # Pydantic validates this descriptor into the declared field type.
        # pylint: disable-next=no-member
        password=parsed.password.get_secret_value(),
    )
    # Changing credentials cannot resolve an unconfirmed write.
    if state.get("error") not in ("IMPORT_UNCONFIRMED", "RUN_INTERRUPTED"):
        state.update(status="configured", error=None)
    write(path, state)
    return public(state)


def _collect_account(store, lock_path, base, path, state):
    """Require settled enabled state and no concurrent collection before launch."""
    if not state or not state.get("password") or not (base / "netbox-token.json").is_file():
        return {"error": "SETUP_REQUIRED"}
    if len(list(base.glob("[0-9]*.json"))) > 100:
        return {"error": "ACCOUNT_LIMIT"}
    if not state.get("enabled", True):
        return {"error": "ACCOUNT_DISABLED"}
    if state.get("status") == "running" or state.get("error") in ("IMPORT_UNCONFIRMED", "RUN_INTERRUPTED"):
        return {"error": "IMPORT_UNCONFIRMED"}
    # Serialize accounts too: the runner's collection lock remains the final guard.
    if any(running(read(p)) for p in base.glob("[0-9]*.json")):
        return {"error": "COLLECTION_BUSY"}
    return launch(store, lock_path, path, state)


def _account_error(state):
    """Reject unresolved lifecycle outcomes and permanently deleted accounts first."""
    if state.get("lifecycle_pending"):
        return {"error": "LIFECYCLE_UNCONFIRMED"}
    if state.get("deleted"):
        return {"error": "ACCOUNT_DELETED"}
    return None


def _handle_account(store, lock_path, base, operation, data):
    """Dispatch validated account commands under the existing store lock."""
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("account"), str)
        or not re.fullmatch(r"[0-9]{1,20}", data["account"])
    ):
        raise ControlError("CONTROL_REQUEST_INVALID")
    path = base / (data["account"] + ".json")
    state = read(path) if path.exists() else {}
    error = _account_error(state)
    if error is not None:
        return error
    if operation == "enabled":
        return _set_enabled(path, state, data)
    if operation == "schedule":
        return _set_schedule(path, state, data)
    if running(state):
        return {"error": "RUN_ACTIVE"}
    if state.get("status") == "running":
        state.update(status="attention", error="RUN_INTERRUPTED", next_run=None)
        write(path, state)
    if operation == "save":
        return _save_account(base, path, state, data)
    return _collect_account(store, lock_path, base, path, state)


def handle(store, lock_path, payload):
    """Authorize and serialize experimental account configuration, scheduling and collection."""

    from .api.auth import AuthClient

    if set(payload) != {"action", "operation", "session", "data"} or payload["operation"] not in (
        "list",
        "save",
        "collect",
        "schedule",
        "enabled",
        "lifecycle-review",
        "lifecycle-execute",
        "reconcile",
    ):
        raise ControlError("CONTROL_REQUEST_INVALID")
    AuthClient("/run/netbox-sync-auth/worker.sock").call(
        "authorize", session=payload["session"], permission="bootstrap.manage", audit=payload["operation"] != "list"
    )
    operation, data = payload["operation"], payload["data"]
    if operation == "reconcile":
        from .selectel_recovery import reconcile

        if not isinstance(data, dict) or set(data) != {"account"}:
            raise ControlError("CONTROL_REQUEST_INVALID")
        return reconcile(store, lock_path, data["account"])
    if operation.startswith("lifecycle-"):
        from .selectel_lifecycle_control import handle as lifecycle

        return lifecycle(store, lock_path, operation, data)
    with store.locked():
        base = root(store)
        url, _ = runtime_netbox(store.path, "read")
        if operation == "list":
            return _list_accounts(base, url)
        return _handle_account(store, lock_path, base, operation, data)
