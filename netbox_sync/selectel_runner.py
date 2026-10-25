"""Durable bounded account job. Provider reads run without root privileges."""

import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import NamedTuple
from .bootstrap_state import BootstrapStore, runtime_netbox
from .local_control import ControlError
from .selectel_control import read, write, root
from .source_lifecycle import apply_lock
from .discovery_worker import _drop_privileges, _safe_environment
from .child_process import child_process, stop_child
from .selectel_payload import MAX_BYTES
from .selectel_result import confirmed_import


def child_result(output, returncode, operation):
    # Once import started, an abnormal response cannot prove that no writes ran.
    """Validate bounded child output while preserving uncertainty for possible write operations."""

    def failure(code):
        return {"error": "IMPORT_UNCONFIRMED" if operation in ("import", "lifecycle-execute") else code}

    if os.fstat(output.fileno()).st_size > MAX_BYTES:
        return failure("SELECTEL_RESULT_TOO_LARGE")
    if returncode:
        return failure("SELECTEL_COLLECTOR_EXITED")
    output.seek(0)
    try:
        result = json.load(output)
    except (ValueError, UnicodeError):
        return failure("SELECTEL_RESULT_INVALID")
    if not isinstance(result, dict):
        return failure("SELECTEL_RESULT_INVALID")
    if (
        operation == "collect"
        and "error" not in result
        and not all(isinstance(result.get(k), dict) for k in ("document", "registry", "summary"))
    ):
        return failure("SELECTEL_RESULT_INVALID")
    return result


@contextmanager
def locked_store(store):
    # The launcher still holds this lock briefly after starting our process.
    """Retry the launcher-held bootstrap lock briefly before entering account state work."""

    with ExitStack() as stack:
        for attempt in range(101):
            try:
                stack.enter_context(store.locked())
                break
            except ControlError as exc:
                if exc.code != "BOOTSTRAP_BUSY" or attempt == 100:
                    raise
                time.sleep(0.05)
        yield


def child(value, timeout):
    """Run a resource-limited collector and preserve uncertain outcomes on write timeouts."""

    def sandbox():
        import resource

        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES + 4096, MAX_BYTES + 4096))
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
        _drop_privileges(10001, 10001)()

    with tempfile.TemporaryFile() as output:
        with child_process(
            subprocess.Popen,
            [sys.executable, "-B", "-m", "netbox_sync.selectel_collect"],
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.DEVNULL,
            env=_safe_environment(),
            preexec_fn=sandbox,
        ) as process:
            try:
                process.communicate(json.dumps(value).encode(), timeout=timeout)
            except subprocess.TimeoutExpired:
                stop_child(process)
                return {
                    "error": (
                        "IMPORT_UNCONFIRMED" if value["operation"] in ("import", "lifecycle-execute") else "RUN_TIMEOUT"
                    )
                }
        return child_result(output, process.returncode, value["operation"])


class _AccountRun(NamedTuple):
    """Fixed account-run identity and paths used across collection stages."""

    store: object
    account: str
    run_id: str
    lock: str
    base: object
    path: object


@dataclass
class _RunProgress:
    """Track the exact point after which a failure may conceal committed writes."""

    import_started: bool = False


def _execute_run(run, progress):
    """Collect and import under caller-held locks with a second activation check."""
    with locked_store(run.store):
        state = read(run.path)
        if state["run_id"] != run.run_id:
            return None
    url, _ = runtime_netbox(run.store.path, "read")
    token = read(run.base / "netbox-token.json")["token"]
    access = {"url": url, "token": token, "guard_instance": os.environ.get("NETBOX_SYNC_GUARD_INSTANCE", "")}
    result = child(dict(operation="preflight", **access), 90)
    if result.get("ready") is True:
        result = child(
            {
                "operation": "collect",
                "account": run.account,
                "username": state["username"],
                "password": state["password"],
            },
            2800,
        )
    elif "error" not in result:
        result = {"error": "SETUP_REQUIRED"}
    if "error" not in result:
        with apply_lock(run.lock):
            # Disabling an account during collection also prevents its import.
            with locked_store(run.store):
                current = read(run.path)
                if current.get("run_id") != run.run_id:
                    return None
                if not current.get("enabled", True):
                    current.update(status="attention", error="ACCOUNT_DISABLED", finished_at=time.time())
                    write(run.path, current)
                    return None
            url, _ = runtime_netbox(run.store.path, "read")
            token = read(run.base / "netbox-token.json")["token"]
            progress.import_started = True
            imported = child(
                {
                    "operation": "import",
                    "url": url,
                    "token": token,
                    "guard_instance": os.environ.get("NETBOX_SYNC_GUARD_INSTANCE", ""),
                    "payload": {
                        "account": run.account,
                        "nonce": run.run_id,
                        "document": result["document"],
                        "registry": result["registry"],
                    },
                },
                90,
            )
        if imported.get("error") in ("IMPORT_UNCONFIRMED", "NETBOX_IMPORT_REFUSED", "SELECTEL_RESULT_TOO_LARGE"):
            result = {"error": imported["error"]}
        elif not confirmed_import(imported, run.account):
            result = {"error": "IMPORT_UNCONFIRMED"}
        else:
            result = {"summary": {**result["summary"], **imported}}
    return result


def _finish_run(run, result):
    """Persist only the current run outcome, preserving uncertain-import scheduling."""
    # Do not expose exception bodies, provider payloads, or passwords.
    with locked_store(run.store):
        state = read(run.path)
        if state.get("run_id") != run.run_id:
            return
        if "error" in result:
            state.update(status="attention", error=result["error"])
            if result["error"] == "IMPORT_UNCONFIRMED":
                state["next_run"] = None
        else:
            state.update(status="completed", error=None, summary=result["summary"])
        state["finished_at"] = time.time()
        write(run.path, state)


def main():
    """Serialize collection and import, recheck account activation and persist the run outcome."""

    store = BootstrapStore(sys.argv[1])
    account, run_id, lock = sys.argv[2:]
    base = root(store)
    path = base / (account + ".json")
    run = _AccountRun(store, account, run_id, lock, base, path)
    progress = _RunProgress()
    try:
        # Per-account lock survives API timeout and prevents overlap after interrupted runs.
        with apply_lock(str(base / "collection.lock")), apply_lock(str(base / (account + ".lock"))):
            result = _execute_run(run, progress)
            if result is None:
                return
    except Exception:
        result = {"error": "IMPORT_UNCONFIRMED" if progress.import_started else "RUN_INTERRUPTED_OR_BUSY"}
    _finish_run(run, result)


if __name__ == "__main__":
    main()
