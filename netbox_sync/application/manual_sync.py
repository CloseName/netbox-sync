"""Manual sync orchestration independent of HTTP and credential mechanics."""

# pylint: disable=too-many-boolean-expressions

from dataclasses import dataclass
from enum import Enum

from .confirmation import ConfirmationClaims, ConfirmationError, ConfirmationStore


class ApplyOutcome(str, Enum):
    """Explicit outcomes without pretending multi-request writes are transactional."""

    SUCCEEDED = "SUCCEEDED"
    FAILED_BEFORE_WRITE = "FAILED_BEFORE_WRITE"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    OUTCOME_UNCERTAIN = "OUTCOME_UNCERTAIN"


class ManualSyncError(RuntimeError):
    """Stable fail-closed orchestration failure."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ApplyResult:
    """Secret-free result returned after consuming a capability."""

    status: ApplyOutcome
    plan_digest: str


class ManualSyncService:
    """Bind an exact read-only plan to one guarded executor invocation."""

    def __init__(self, source_loader, plan_builder, executor, confirmations=None):
        self._source_loader = source_loader
        self._plan_builder = plan_builder
        self._executor = executor
        self._confirmations = confirmations or ConfirmationStore()

    def _enabled_source(self, source_instance):
        source = self._source_loader(source_instance)
        if source is None:
            raise ManualSyncError("SOURCE_NOT_FOUND")
        if not source.enabled:
            raise ManualSyncError("SOURCE_DISABLED")
        # sync_enabled deliberately does not govern explicitly confirmed manual runs.
        return source

    def prepare(self, source_instance, expected_digest):
        """Recompute before issuing a short-lived capability."""
        source = self._enabled_source(source_instance)
        plan = self._plan_builder(source)
        if not plan.apply_allowed:
            raise ManualSyncError("PLAN_BLOCKED")
        if plan.digest != expected_digest:
            raise ManualSyncError("PLAN_STALE")
        claims = ConfirmationClaims(
            source_instance=source.source_instance,
            source_id=source.id,
            plan_digest=plan.digest,
            planner_version=plan.planner_version,
            source_fingerprint=plan.source_fingerprint,
            target_fingerprint=plan.target_fingerprint,
        )
        return self._confirmations.issue(claims)

    def apply(self, source_instance, token):
        """Consume once, re-plan, then cross the existing guarded write boundary."""
        try:
            claims = self._confirmations.consume(token, source_instance)
        except ConfirmationError as exc:
            raise ManualSyncError(exc.code) from exc
        source = self._enabled_source(source_instance)
        plan = self._plan_builder(source)
        if (
            not plan.apply_allowed
            or source.id != claims.source_id
            or plan.digest != claims.plan_digest
            or plan.planner_version != claims.planner_version
            or plan.source_fingerprint != claims.source_fingerprint
            or plan.target_fingerprint != claims.target_fingerprint
        ):
            raise ManualSyncError("PLAN_STALE")
        try:
            self._executor(source, plan)
        except ManualSyncError:
            raise
        except Exception as exc:
            # Once delegated, existing multi-request executors cannot prove whether a write landed.
            raise ManualSyncError("OUTCOME_UNCERTAIN") from exc
        return ApplyResult(ApplyOutcome.SUCCEEDED, plan.digest)
