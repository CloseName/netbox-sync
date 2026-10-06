"""Schedule read/update application boundary."""

from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime, timezone

from .scheduling import evaluate_schedule


@dataclass(frozen=True)
class ScheduleView:
    """Allowlisted derived schedule projection."""

    source_instance: str
    sync_enabled: bool
    sync_interval_seconds: int
    scheduler_state: str
    last_scheduled_run_at: object | None
    next_expected_at: object | None
    sync_calendar: dict | None = None


class ScheduleReadError(RuntimeError):
    """Safe schedule projection failure."""

    def __init__(self, code='SCHEDULE_UNAVAILABLE'):
        self.code = code
        super().__init__(code)


class ScheduleService:
    """Combine read-only source/history state with isolated control updates."""

    def __init__(self, sources, history, control, stale_seconds=7200, clock=None):
        self._sources, self._history, self._control = sources, history, control
        self._stale_seconds = stale_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _context(self, instance):
        source = self._sources.get_source(instance)
        try:
            runs = self._history.scheduled_for_source(instance)
        except Exception:  # pylint: disable=broad-exception-caught
            raise ScheduleReadError() from None
        latest = runs[0] if runs else None
        running = next((run for run in runs if run.status.value == 'RUNNING'), None)
        return source, latest, running

    def get(self, instance):
        source, latest, running = self._context(instance)
        decision = evaluate_schedule(source, latest, running, self._clock(), self._stale_seconds)
        return ScheduleView(instance, source.sync_enabled, source.sync_interval_seconds,
                            decision.state.value, decision.last_scheduled_run_at,
                            decision.next_expected_at, source.sync_calendar)

    def update(self, instance, values):
        source, latest, running = self._context(instance)
        committed = self._control.update(instance, values)
        updated = replace(source, sync_enabled=committed['sync_enabled'],
                          sync_interval_seconds=committed['sync_interval_seconds'],
                          sync_calendar=committed.get('sync_calendar'),
                          schedule_changed_at=(datetime.fromisoformat(committed['schedule_changed_at'])
                              if isinstance(committed.get('schedule_changed_at'), str) else committed.get('schedule_changed_at')))
        decision = evaluate_schedule(updated, latest, running, self._clock(), self._stale_seconds)
        return ScheduleView(instance, updated.sync_enabled, updated.sync_interval_seconds,
                            decision.state.value, decision.last_scheduled_run_at,
                            decision.next_expected_at, updated.sync_calendar)
