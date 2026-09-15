"""Source-agnostic, sequential multi-source orchestration."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from .source_config import SourceConfig
from . import scheduled_failure
from .run_history import (ActionCounts, RunStatus, RunTrigger, safe_error_code,
                          safe_error_message, terminal_status)


class HistoryStatus(str, Enum):
    """Bounded persistence outcome independent of source execution."""

    NOT_REQUESTED = 'NOT_REQUESTED'
    RECORDED = 'RECORDED'
    START_FAILED = 'START_FAILED'
    FINALIZE_FAILED = 'FINALIZE_FAILED'


HISTORY_UNAVAILABLE = 'RUN_HISTORY_UNAVAILABLE'


@dataclass(frozen=True)
class SourceRunResult:
    """Secret-safe outcome for one attempted source."""

    source_id: str
    source_instance: str
    source_type: str
    success: bool
    started_at: datetime
    finished_at: datetime
    error_type: Optional[str] = None
    error_summary: Optional[str] = None
    history_status: HistoryStatus = HistoryStatus.NOT_REQUESTED
    history_error_code: Optional[str] = None


@dataclass(frozen=True)
class MultiSourceRunResult:
    """Aggregate result for a deterministic multi-source execution."""

    results: tuple[SourceRunResult, ...]

    @property
    def total(self):
        """Return attempted source count."""

        return len(self.results)

    @property
    def succeeded(self):
        """Return successful source count."""

        return sum(result.success for result in self.results)

    @property
    def failed(self):
        """Return failed source count."""

        return self.total - self.succeeded

    @property
    def skipped(self):
        """No selected source is skipped by this phase's orchestrator."""

        return 0

    @property
    def history_failures(self):
        """Return sources whose audit persistence did not complete."""

        return sum(result.history_error_code is not None for result in self.results)


def _utc_now():
    return datetime.now(timezone.utc)


def run_sources(sources, execute_source, clock=None, run_repository=None):
    """Execute immutable configs sequentially and isolate per-source failures."""

    now = clock or _utc_now
    configs = tuple(sources)
    for config in configs:
        if not isinstance(config, SourceConfig):
            raise TypeError('sources must contain only SourceConfig objects')

    results = []
    for source in sorted(configs, key=lambda config: config.id):
        started_at = now()
        run = None
        history_status = HistoryStatus.NOT_REQUESTED
        if run_repository:
            try:
                run = run_repository.start_run(
                    source.source_instance, source.source_type, RunTrigger.SCHEDULED,
                    'system/scheduler',
                )
                history_status = HistoryStatus.RECORDED
            except Exception:  # pylint: disable=broad-exception-caught
                results.append(SourceRunResult(
                    source_id=source.id, source_instance=source.source_instance,
                    source_type=source.source_type, success=False, started_at=started_at,
                    finished_at=now(), error_type='HistoryPersistenceError',
                    error_summary='source execution skipped because run history is unavailable',
                    history_status=HistoryStatus.START_FAILED,
                    history_error_code=HISTORY_UNAVAILABLE,
                ))
                continue
        evidence, diagnostic_token = scheduled_failure.begin()
        try:
            execution = execute_source(source)
        except (Exception, SystemExit) as exc:  # pylint: disable=broad-exception-caught
            scheduled_failure.emit(exc, evidence, run.run_id if run else None)
            code = safe_error_code(getattr(exc, 'code', None))
            if run:
                try:
                    run_repository.finish_run(
                        run.run_id, terminal_status(code), error_code=code,
                        error_message_safe=safe_error_message(code),
                        plan_digest=getattr(evidence.plan, 'digest', None),
                        planner_version=getattr(evidence.plan, 'planner_version', None),
                    )
                except Exception:  # pylint: disable=broad-exception-caught
                    history_status = HistoryStatus.FINALIZE_FAILED
            results.append(
                SourceRunResult(
                    source_id=source.id,
                    source_instance=source.source_instance,
                    source_type=source.source_type,
                    success=False,
                    started_at=started_at,
                    finished_at=now(),
                    error_type=type(exc).__name__,
                    error_summary='source execution failed',
                    history_status=history_status,
                    history_error_code=(HISTORY_UNAVAILABLE
                                        if history_status is HistoryStatus.FINALIZE_FAILED else None),
                )
            )
            continue
        finally:
            scheduled_failure.end(diagnostic_token)
        if run:
            try:
                run_repository.finish_run(
                    run.run_id, RunStatus.SUCCEEDED,
                    counts=ActionCounts.from_items(getattr(execution, 'items', ())),
                    plan_digest=getattr(execution, 'digest', None),
                    planner_version=getattr(execution, 'planner_version', None),
                )
            except Exception:  # pylint: disable=broad-exception-caught
                history_status = HistoryStatus.FINALIZE_FAILED
        results.append(
            SourceRunResult(
                source_id=source.id,
                source_instance=source.source_instance,
                source_type=source.source_type,
                success=True,
                started_at=started_at,
                finished_at=now(),
                history_status=history_status,
                history_error_code=(HISTORY_UNAVAILABLE
                                    if history_status is HistoryStatus.FINALIZE_FAILED else None),
            )
        )
    return MultiSourceRunResult(results=tuple(results))
