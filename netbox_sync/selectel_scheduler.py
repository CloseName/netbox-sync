"""Account calendar worker. Shares the protected launcher and account state."""

import logging
import re
import time
from .selectel_control import root, read, write, running, launch


def tick(store, lock_path, now=None):
    """Launch the earliest eligible account and pause interrupted or uncertain runs."""

    now = time.time() if now is None else now
    with store.locked():
        base = root(store)
        if not (base / "netbox-token.json").is_file():
            return
        states = [(p, read(p)) for p in sorted(base.glob("*.json")) if re.fullmatch(r"[0-9]{1,20}", p.stem)]
        if any(running(state) for _, state in states):
            return
        for path, state in states:
            if state.get("status") == "running":
                state.update(status="attention", error="RUN_INTERRUPTED", next_run=None)
                write(path, state)
        due = [
            (path, state)
            for path, state in states
            if not state.get("deleted")
            and not state.get("lifecycle_pending")
            and state.get("enabled", True)
            and state.get("schedule", {}).get("kind", "off") != "off"
            and isinstance(state.get("next_run"), (int, float))
            and state["next_run"] <= now
            and state.get("error") not in ("IMPORT_UNCONFIRMED", "RUN_INTERRUPTED")
        ]
        if due:
            path, state = min(due, key=lambda item: (item[1]["next_run"], item[0].name))
            launch(store, lock_path, path, state, trigger="schedule")


def run(store, lock_path, stop):
    """Poll experimental account schedules with closed diagnostic logging until stopped."""

    while not stop.is_set():
        try:
            tick(store, lock_path)
        except Exception:
            # Provider/state values and credentials must never enter logs.
            logging.getLogger(__name__).warning("SELECTEL_SCHEDULE_TICK_FAILED")
        stop.wait(30)
