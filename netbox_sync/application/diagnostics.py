"""Read-only, transport-neutral operator diagnostics aggregation."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from .scheduling import evaluate_schedule


class DiagnosticStatus(str, Enum):
    """Closed public diagnostic states."""

    HEALTHY = 'HEALTHY'
    DEGRADED = 'DEGRADED'
    UNHEALTHY = 'UNHEALTHY'
    UNAVAILABLE = 'UNAVAILABLE'
    UNKNOWN = 'UNKNOWN'


@dataclass(frozen=True)
class DiagnosticComponent:
    """Bounded component state without implementation details."""

    status: DiagnosticStatus
    checked_at: datetime
    safe_code: str | None = None
    safe_message: str | None = None
    last_seen_at: datetime | None = None
    last_success_at: datetime | None = None
    next_expected_at: datetime | None = None


@dataclass(frozen=True)
class RunSummary:
    """Small public-safe run projection."""

    run_id: object
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class DiagnosticWarning:
    """Closed warning suitable for API and UI rendering."""

    warning_code: str
    safe_message: str
    source_instance: str | None = None
    source_type: str | None = None
    trigger: str | None = None
    run_id: object | None = None
    started_at: datetime | None = None
    age_seconds: int | None = None


@dataclass(frozen=True)
class SourceDiagnostic:
    """Per-source state inferred only from configuration and persisted history."""

    source_instance: str
    source_type: str
    enabled: bool
    sync_enabled: bool
    sync_interval_seconds: int
    status: DiagnosticStatus
    latest_run: RunSummary | None
    latest_success_at: datetime | None
    latest_scheduled_run: RunSummary | None
    latest_manual_run: RunSummary | None
    scheduler_state: str
    last_scheduled_run_at: datetime | None
    next_expected_at: datetime | None
    warnings: tuple[str, ...]

    plan_blocked: bool = False
    plan_checked_at: datetime | None = None
    outcome_unconfirmed: bool = False
    operation_evidence_available: bool = False

    @property
    def warning_count(self):
        return len(self.warnings)


@dataclass(frozen=True)
class HistorySnapshot:
    """Fixed-query history snapshot produced by a read adapter."""

    latest: tuple
    successes: tuple
    scheduled: tuple
    manual: tuple
    stale: tuple
    scheduled_successes: tuple = ()
    scheduled_running: tuple = ()


@dataclass(frozen=True)
class Diagnostics:
    """Complete safe operator snapshot."""

    overall_status: DiagnosticStatus
    generated_at: datetime
    components: dict[str, DiagnosticComponent]
    sources: tuple[SourceDiagnostic, ...]
    stale_runs: tuple[DiagnosticWarning, ...]
    warnings: tuple[DiagnosticWarning, ...]


def _summary(run):
    if run is None:
        return None
    return RunSummary(run.run_id, run.trigger.value, run.status.value,
                      run.started_at, run.finished_at)


def _indexed(values):
    return {value.source_instance: value for value in values}


class DiagnosticsService:
    """Aggregate failure-isolated checks without discovery, apply, or writes."""

    def __init__(self, source_service, history_reader, discovery_health, apply_health,
                 stale_seconds=7200, clock=None, evidence_reader=None):
        if not isinstance(stale_seconds, int) or not 300 <= stale_seconds <= 604800:
            raise ValueError('diagnostics stale threshold must be between 300 and 604800 seconds')
        self._evidence = evidence_reader or history_reader
        self._sources = source_service
        self._history = history_reader
        self._discovery = discovery_health
        self._apply = apply_health
        self._stale_seconds = stale_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _worker(client, checked_at, code, message):
        try:
            healthy = client.health()
        except Exception:  # pylint: disable=broad-exception-caught
            healthy = False
        return DiagnosticComponent(
            DiagnosticStatus.HEALTHY if healthy else DiagnosticStatus.UNAVAILABLE,
            checked_at,
            None if healthy else code,
            None if healthy else message,
            last_seen_at=checked_at if healthy else None,
        )

    def check(self):
        """Return partial diagnostics even when individual dependencies fail."""
        now = self._clock()
        components = {
            'api': DiagnosticComponent(DiagnosticStatus.HEALTHY, now, last_seen_at=now),
        }
        try:
            source_views = tuple(self._sources.list_sources())
            components['registry'] = DiagnosticComponent(
                DiagnosticStatus.HEALTHY, now, last_seen_at=now)
        except Exception:  # pylint: disable=broad-exception-caught
            source_views = ()
            components['registry'] = DiagnosticComponent(
                DiagnosticStatus.UNAVAILABLE, now, 'REGISTRY_UNAVAILABLE',
                'Source registry is unavailable.')
        try:
            snapshot = self._history.diagnostics_snapshot(
                now - timedelta(seconds=self._stale_seconds), 100)
            components['run_history'] = DiagnosticComponent(
                DiagnosticStatus.HEALTHY, now, last_seen_at=now)
        except Exception:  # pylint: disable=broad-exception-caught
            snapshot = HistorySnapshot((), (), (), (), ())
            components['run_history'] = DiagnosticComponent(
                DiagnosticStatus.UNAVAILABLE, now, 'RUN_HISTORY_UNAVAILABLE',
                'Synchronization history is unavailable.')
        components['discovery_worker'] = self._worker(
            self._discovery, now, 'DISCOVERY_WORKER_UNAVAILABLE',
            'Discovery worker is unavailable.')
        components['apply_worker'] = self._worker(
            self._apply, now, 'APPLY_WORKER_UNAVAILABLE',
            'Apply worker is unavailable.')

        plans, uncertain, operation_evidence_available = {}, set(), False
        try:
            plans, uncertain = self._evidence.operation_evidence()
            operation_evidence_available = True
        except Exception:
            # History remains useful, but lack of plan evidence is never "no problems".
            pass
        latest, successes = _indexed(snapshot.latest), _indexed(snapshot.successes)
        scheduled, manual = _indexed(snapshot.scheduled), _indexed(snapshot.manual)
        scheduled_running = _indexed(snapshot.scheduled_running)
        stale_by_source = {run.source_instance for run in snapshot.stale}
        source_results, warnings = [], []
        for source in sorted(source_views, key=lambda value: value.source_instance):
            current = latest.get(source.source_instance)
            source_warnings = []
            if source.source_instance in stale_by_source:
                source_warnings.append('STALE_RUNNING')
            scheduled_run = scheduled.get(source.source_instance)
            decision = evaluate_schedule(
                source, scheduled_run, scheduled_running.get(source.source_instance),
                now, self._stale_seconds)
            delayed = decision.state.value == 'DELAYED'
            if delayed:
                source_warnings.append('SCHEDULED_ACTIVITY_DELAYED')
            if not source.enabled or current is None:
                status = DiagnosticStatus.UNKNOWN
            elif current.status.value == 'SUCCEEDED':
                status = (DiagnosticStatus.DEGRADED if source_warnings
                          else DiagnosticStatus.HEALTHY)
            elif current.status.value == 'RUNNING':
                status = (DiagnosticStatus.DEGRADED if source_warnings
                          else DiagnosticStatus.UNKNOWN)
            elif source.source_instance in successes:
                status = DiagnosticStatus.DEGRADED
            else:
                status = DiagnosticStatus.UNHEALTHY
            plan = plans.get(source.source_instance, {})
            plan_blocked = plan.get('apply_allowed') is False and plan.get('status') == 'READY'
            outcome_unconfirmed = source.source_instance in uncertain
            if plan_blocked or outcome_unconfirmed:
                status = DiagnosticStatus.DEGRADED
            source_results.append(SourceDiagnostic(
                source.source_instance, source.type, source.enabled, source.sync_enabled,
                source.sync_interval_seconds, status, _summary(current),
                (successes.get(source.source_instance).finished_at
                 or successes.get(source.source_instance).started_at)
                if source.source_instance in successes else None,
                _summary(scheduled_run), _summary(manual.get(source.source_instance)),
                decision.state.value, decision.last_scheduled_run_at,
                decision.next_expected_at,
                tuple(source_warnings), plan_blocked, plan.get("finished_at"), outcome_unconfirmed, operation_evidence_available,
            ))
            if delayed:
                warnings.append(DiagnosticWarning(
                    'SCHEDULED_ACTIVITY_DELAYED',
                    'Scheduled synchronization activity is later than expected.',
                    source.source_instance))

        stale_warnings = tuple(DiagnosticWarning(
            warning_code='STALE_RUNNING',
            safe_message=(
                'Synchronization run has remained RUNNING longer than expected. '
                'Automatic retry was not performed.'
            ),
            source_instance=run.source_instance,
            source_type=run.source_type,
            trigger=run.trigger.value,
            run_id=run.run_id,
            started_at=run.started_at,
            age_seconds=max(0, int((now - run.started_at).total_seconds())),
        ) for run in snapshot.stale)
        warnings = stale_warnings + tuple(warnings)
        scheduled_runs = tuple(snapshot.scheduled)
        scheduled_successes = tuple(snapshot.scheduled_successes)
        if components['run_history'].status is DiagnosticStatus.UNAVAILABLE:
            scheduler = DiagnosticComponent(DiagnosticStatus.UNKNOWN, now,
                                            'RUN_HISTORY_UNAVAILABLE',
                                            'Scheduled activity cannot be evaluated.')
        elif any('SCHEDULED_ACTIVITY_DELAYED' in source.warnings for source in source_results):
            scheduler = DiagnosticComponent(
                DiagnosticStatus.DEGRADED, now, 'SCHEDULED_ACTIVITY_DELAYED',
                'Scheduled synchronization activity is later than expected.',
                max((run.started_at for run in scheduled_runs), default=None),
                max(((run.finished_at or run.started_at) for run in scheduled_successes), default=None))
        elif scheduled_runs:
            scheduler = DiagnosticComponent(
                DiagnosticStatus.HEALTHY, now, last_seen_at=max(run.started_at for run in scheduled_runs),
                last_success_at=max(((run.finished_at or run.started_at)
                                     for run in scheduled_successes), default=None))
        else:
            scheduler = DiagnosticComponent(
                DiagnosticStatus.UNKNOWN, now, safe_message='No scheduled runs have been recorded.')
        components['scheduler'] = scheduler

        source_statuses = {source.status for source in source_results}
        if (components['registry'].status is DiagnosticStatus.UNAVAILABLE
                or DiagnosticStatus.UNHEALTHY in source_statuses):
            overall = DiagnosticStatus.UNHEALTHY
        elif (DiagnosticStatus.DEGRADED in source_statuses or warnings
              or any(component.status in (
                DiagnosticStatus.DEGRADED, DiagnosticStatus.UNAVAILABLE)
                for component in components.values())):
            overall = DiagnosticStatus.DEGRADED
        else:
            overall = DiagnosticStatus.HEALTHY
        return Diagnostics(overall, now, components, tuple(source_results),
                           stale_warnings, warnings)
