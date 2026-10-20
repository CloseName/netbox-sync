"""Root-owned per-VM keys and bounded, unprivileged pfSense network operations."""

import json
import os
import secrets
import subprocess
import sys
import time
from .bootstrap_state import runtime_netbox
from .local_control import ControlError
from .source_lifecycle import apply_lock
from .discovery_worker import _drop_privileges, _safe_environment
from .child_process import child_process, stop_child

PUBLIC = (
    "status",
    "error",
    "address",
    "port",
    "verify_tls",
    "username",
    "collected_at",
    "ssh_port",
    "sync_enabled",
    "interval_minutes",
    "next_attempt",
)


def public(value):
    """Project public pfSense connection state without private key material."""

    return {k: value[k] for k in PUBLIC if k in value}


def atomic(path, value):
    """Replace private JSON state after syncing the temporary file."""

    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def collection_due(state, now):
    """Require enabled synchronization, prepared SSH credentials and an elapsed due time."""

    return bool(
        state.get("sync_enabled") and state.get("host_key") and state.get("key") and state.get("next_attempt", 0) <= now
    )


def collector_username():
    """Allow only the configured production or test collector account name."""

    value = os.environ.get("NETBOX_SYNC_PFSENSE_USER", "netbox-sync")
    if value not in ("netbox-sync", "netbox-sync-test"):
        raise ControlError("CONTROL_REQUEST_INVALID")
    return value


def state_root(store):
    """Separate test-collector state under the pfSense directory."""

    base = store.root / "pfsense"
    return base if collector_username() == "netbox-sync" else base / "test"


def _state_path(store, vm):
    """Validate private state directories before selecting a VM file."""
    base = store.root / "pfsense"
    base.mkdir(mode=0o700, exist_ok=True)
    if base.is_symlink() or base.stat().st_uid != 0 or base.stat().st_mode & 0o077:
        raise ControlError("CONTROL_DIRECTORY_INVALID")
    root = state_root(store)
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != 0 or root.stat().st_mode & 0o077:
        raise ControlError("CONTROL_DIRECTORY_INVALID")
    return root / (str(vm) + ".json")


def _read_state(path):
    """Read bounded private state or return the disconnected projection."""
    if not path.exists():
        return {"status": "NOT_CONNECTED"}
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 16384:
            raise ControlError("CONTROL_DIRECTORY_INVALID")
        return json.load(stream)


def _prepare_connection(state, data):
    """Validate a connection and reuse its durable key unless the endpoint changes."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    from .api.pfsense import Connect

    original = data
    data = Connect(**data).model_dump()
    data["password"] = original["password"]
    endpoint = {k: data[k] for k in ("address", "port", "verify_tls")}
    if "key" in state and any(state.get(k) != endpoint[k] for k in ("address", "port")):
        return data, {"error": "ENDPOINT_CHANGED", "status": state["status"]}
    if "key" not in state:
        key = Ed25519PrivateKey.generate()
        state.update(
            key=key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()
            ).decode(),
            public_key=key.public_key()
            .public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
            .decode(),
            owner=secrets.token_hex(16),
            username=collector_username(),
            **endpoint,
        )
    state.update(endpoint)
    return data, None


def _run_collector(value):
    """Run the bounded child and map uncertain failures to the existing safe code."""
    try:
        with child_process(
            subprocess.Popen,
            [sys.executable, "-B", "-m", "netbox_sync.pfsense_connect"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_safe_environment(),
            preexec_fn=_drop_privileges(10001, 10001),
        ) as process:
            try:
                output, _ = process.communicate(json.dumps(value).encode(), timeout=115)
            except subprocess.TimeoutExpired:
                stop_child(process)
                raise ValueError()
        if process.returncode or len(output) > 8192:
            raise ValueError()
        result = json.loads(output)
    except Exception:
        result = {"error": "OUTCOME_UNKNOWN"}
    return result


def _collect(store, path, state, command, policy):
    """Persist reservation before remote work and retain successful SSH preparation."""
    vm, operation, data = command
    state["next_attempt"] = time.time() + state.get("interval_minutes", 60) * 60
    state.update(status="RUNNING", error=None, started_at=time.time())
    atomic(path, state)  # Persist key before any remote mutation; retries reuse it.
    url, read_token = runtime_netbox(store.path, "read")
    _, apply_token = runtime_netbox(store.path, "apply")
    value = {
        "vm_id": vm,
        "operation": operation,
        "state": state,
        "data": data,
        "policy": policy,
        "url": url,
        "read_token": read_token,
        "apply_token": apply_token,
        "guard_instance": os.environ.get("NETBOX_SYNC_GUARD_INSTANCE", ""),
    }
    result = _run_collector(value)
    # Retain successful SSH preparation even if collection/import fails.
    if (
        type(result.get("ssh_port")) is int
        and 1 <= result["ssh_port"] <= 65535
        and isinstance(result.get("host_key"), str)
        and result["host_key"].startswith("ssh-ed25519 ")
    ):
        state.update(ssh_port=result["ssh_port"], host_key=result["host_key"])
    if result.get("error"):
        state.update(status="ATTENTION", error=result["error"])
    else:
        if operation == "connect":
            state.update(sync_enabled=data["sync_enabled"], interval_minutes=data["interval_minutes"])
        state["next_attempt"] = time.time() + state.get("interval_minutes", 60) * 60
        state.update(status="CONNECTED", error=None, **{k: result[k] for k in ("collected_at", "ssh_port", "host_key")})
    atomic(path, state)
    return public(state)


def _set_schedule(path, state, data):
    """Persist scheduling only after SSH preparation has completed."""
    from .api.pfsense import Schedule

    settings = Schedule(**data)
    if not state.get("host_key"):
        return {"error": "CONNECT_REQUIRED"}
    state.update(
        sync_enabled=settings.sync_enabled,
        interval_minutes=settings.interval_minutes,
        next_attempt=time.time() + settings.interval_minutes * 60,
    )
    atomic(path, state)
    return public(state)


def handle(store, lock_path, payload, *, scheduled_policy=None):
    """Authorize and serialize per-VM setup, scheduling and bounded collection operations."""

    from .api.auth import AuthClient

    if (
        set(payload) != {"action", "operation", "vm_id", "session", "data"}
        or type(payload["vm_id"]) is not int
        or not 0 < payload["vm_id"] <= 2147483647
    ):
        raise ControlError("CONTROL_REQUEST_INVALID")
    operation = payload["operation"]
    vm = payload["vm_id"]
    data = payload["data"]
    if operation not in ("status", "connect", "collect", "schedule"):
        raise ControlError("CONTROL_REQUEST_INVALID")
    auth = AuthClient("/run/netbox-sync-auth/worker.sock")
    if scheduled_policy is None:
        auth.call(
            "authorize",
            session=payload["session"],
            permission={
                "status": "source.read",
                "connect": "source.register",
                "collect": "source.apply",
                "schedule": "source.apply",
            }[operation],
            audit=operation != "status",
        )
    path = _state_path(store, vm)

    if operation == "status":
        current = _read_state(path)
        if current.get("status") == "RUNNING" and time.time() - current.get("started_at", 0) > 130:
            current.update(status="ATTENTION", error="OUTCOME_UNKNOWN")
        return public(current)
    policy = (
        scheduled_policy
        if scheduled_policy is not None
        else auth.call("probe.authorize", session=payload["session"], revision=data.get("policy_revision"))["effective"]
    )
    with apply_lock(lock_path):
        state = _read_state(path)
        if scheduled_policy is not None and not collection_due(state, time.time()):
            return public(state)
        if operation == "connect":
            data, error = _prepare_connection(state, data)
            if error is not None:
                return error
        elif "key" not in state:
            return {"error": "NOT_CONNECTED"}
        if operation == "schedule":
            return _set_schedule(path, state, data)
        return _collect(store, path, state, (vm, operation, data), policy)
