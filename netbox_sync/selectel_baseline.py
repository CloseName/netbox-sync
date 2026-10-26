"""Accept explicit historical baseline receipts without inventing import success."""

from copy import deepcopy
import time


def finish(path, state, payload, result):
    """Keep the pending gate unless Guard acknowledges this exact reviewed run."""
    from .selectel_control import write

    required = ("account", "operation", "key", "fingerprint")
    if (
        result.get("baseline_accepted") is not True
        or result.get("historical_outcome") != "unknown"
        or any(result.get(key) != payload.get(key) for key in required)
    ):
        return {"error": "LIFECYCLE_UNCONFIRMED", "pending": payload}
    history = list(state.get("baseline_history", []))
    history.append(
        {
            key: deepcopy(state.get(key))
            for key in ("run_id", "status", "error", "started_at", "finished_at", "reconciliation")
        }
    )
    history[-1].update(accepted_at=time.time(), historical_outcome="unknown", fingerprint=payload["fingerprint"])
    state.update(
        baseline_history=history,
        status="baseline_accepted",
        error=None,
        enabled=False,
        schedule={"kind": "off"},
        next_run=None,
    )
    state.pop("lifecycle_pending", None)
    # Older successful summaries cannot certify the newly accepted baseline.
    state.pop("summary", None)
    write(path, state)
    return result
