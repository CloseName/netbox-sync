"""Fixed-tick registry scheduler using persisted scheduled history."""

from dataclasses import dataclass
from datetime import datetime, timezone

from .application.scheduling import ScheduleDecision, ScheduleEvaluationStatus, SchedulerSourceInput, evaluate_schedule
from .orchestrator import MultiSourceRunResult, run_sources


@dataclass(frozen=True)
class SchedulerTickResult:
    """Bounded decisions and existing execution outcomes for one tick."""

    decisions: tuple
    execution: MultiSourceRunResult

    @property
    def counts(self):
        result = {name: 0 for name in ("disabled", "waiting", "due", "running", "delayed")}
        for decision in self.decisions:
            if decision.evaluation_status is ScheduleEvaluationStatus.OK:
                result[decision.state.value.lower()] += 1
        return result

    @property
    def evaluation_failed(self):
        """Return isolated conversion/evaluation failure count."""
        return sum(decision.evaluation_status is ScheduleEvaluationStatus.FAILED for decision in self.decisions)

    @property
    def failed(self):
        """Return whether this tick requires a nonzero process exit."""
        return bool(self.evaluation_failed or self.execution.failed or self.execution.history_failures)


def scheduler_summary_lines(tick):
    """Return a bounded summary containing no source data or exception details."""
    counts = tick.counts
    return (
        "SCHEDULER SUMMARY",
        f"sources={len(tick.decisions)}",
        *(f"{name}={counts[name]}" for name in ("due", "delayed", "waiting", "running", "disabled")),
        f"evaluation_failed={tick.evaluation_failed}",
        f"executed={tick.execution.total}",
        f"failed={tick.execution.failed}",
        f"history_failures={tick.execution.history_failures}",
    )


def run_scheduler_tick(sources, execute_source, run_repository, stale_seconds=7200, clock=None, execute_due=True):
    """Evaluate every source once and execute eligible sources sequentially once."""
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    entries = tuple(sources)
    configs = tuple(
        sorted(
            (
                entry.config if isinstance(entry, SchedulerSourceInput) else entry
                for entry in entries
                if not isinstance(entry, SchedulerSourceInput) or entry.config is not None
            ),
            key=lambda item: item.id,
        )
    )
    latest = {run.source_instance: run for run in run_repository.latest_by_source(trigger="scheduled")}
    running = {
        run.source_instance: run for run in run_repository.latest_by_source(trigger="scheduled", status="RUNNING")
    }
    decisions = [
        ScheduleDecision.failed()
        for entry in entries
        if isinstance(entry, SchedulerSourceInput) and entry.config is None
    ]
    eligible = []
    for source in configs:
        try:
            decision = evaluate_schedule(
                source,
                latest.get(source.source_instance),
                running.get(source.source_instance),
                now,
                stale_seconds,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            decision = ScheduleDecision.failed(source.source_instance)
        decisions.append(decision)
        if decision.eligible:
            eligible.append(source)
    execution = run_sources(
        eligible if execute_due else (),
        execute_source,
        clock=clock,
        run_repository=run_repository if execute_due else None,
    )
    return SchedulerTickResult(tuple(decisions), execution)
