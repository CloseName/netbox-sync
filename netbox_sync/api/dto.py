"""Explicit public DTOs; no ORM/configuration objects are exposed."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..application.health import HealthStatus
from ..application.diagnostics import DiagnosticStatus
from ..application.observability import ErrorCode


class PublicModel(BaseModel):
    """Disallow accidental extra response fields."""

    model_config = ConfigDict(extra='forbid', frozen=True)


class ComponentHealthDTO(PublicModel):
    """Safe component status."""

    status: HealthStatus
    message: str
    error_code: ErrorCode | None = None


class ComponentsDTO(PublicModel):
    """Explicitly enumerated system components."""

    api: ComponentHealthDTO
    application: ComponentHealthDTO
    database: ComponentHealthDTO
    registry: ComponentHealthDTO
    netbox: ComponentHealthDTO


class SystemHealthDTO(PublicModel):
    """Read-only snapshot, not a synchronization outcome."""

    status: HealthStatus
    components: ComponentsDTO

    @classmethod
    def from_result(cls, result):
        """Map only allowlisted domain fields."""
        components = {}
        for name in ('api', 'application', 'database', 'registry', 'netbox'):
            component = getattr(result, name)
            components[name] = ComponentHealthDTO(
                status=component.status, message=component.message, error_code=component.error_code,
            )
        return cls(status=result.status, components=ComponentsDTO(**components))


class LivenessDTO(PublicModel):
    """Cheap process liveness; no database access."""

    status: HealthStatus = HealthStatus.HEALTHY


class DiagnosticComponentDTO(PublicModel):
    """Bounded diagnostic component projection."""

    status: Literal['HEALTHY', 'DEGRADED', 'UNAVAILABLE', 'UNKNOWN']
    checked_at: datetime
    safe_code: Literal['REGISTRY_UNAVAILABLE', 'RUN_HISTORY_UNAVAILABLE',
                       'DISCOVERY_WORKER_UNAVAILABLE', 'APPLY_WORKER_UNAVAILABLE',
                       'SCHEDULED_ACTIVITY_DELAYED'] | None = None
    safe_message: str | None = None
    last_seen_at: datetime | None = None
    last_success_at: datetime | None = None
    next_expected_at: datetime | None = None


class DiagnosticComponentsDTO(PublicModel):
    """Explicitly enumerate every operator-visible component."""

    api: DiagnosticComponentDTO
    registry: DiagnosticComponentDTO
    run_history: DiagnosticComponentDTO
    discovery_worker: DiagnosticComponentDTO
    apply_worker: DiagnosticComponentDTO
    scheduler: DiagnosticComponentDTO


class DiagnosticRunDTO(PublicModel):
    """Small run reference used by source diagnostics."""

    run_id: UUID
    trigger: Literal['manual', 'scheduled']
    status: Literal['RUNNING', 'SUCCEEDED', 'FAILED_BEFORE_WRITE', 'PARTIALLY_APPLIED',
                    'OUTCOME_UNCERTAIN', 'BLOCKED', 'LOCKED', 'FAILED']
    started_at: datetime
    finished_at: datetime | None


class DiagnosticWarningDTO(PublicModel):
    """Closed warning without raw implementation detail."""

    warning_code: Literal['STALE_RUNNING', 'SCHEDULED_ACTIVITY_DELAYED']
    safe_message: str = Field(max_length=256)
    source_instance: str | None = None
    source_type: Literal['proxmox', 'esxi'] | None = None
    trigger: Literal['manual', 'scheduled'] | None = None
    run_id: UUID | None = None
    started_at: datetime | None = None
    age_seconds: int | None = Field(default=None, ge=0)


class SourceDiagnosticDTO(PublicModel):
    """Allowlisted per-source diagnostic state."""

    source_instance: str
    source_type: Literal['proxmox', 'esxi']
    enabled: bool
    sync_enabled: bool
    sync_interval_seconds: int = Field(gt=0)
    status: DiagnosticStatus
    latest_run: DiagnosticRunDTO | None
    latest_success_at: datetime | None
    latest_scheduled_run: DiagnosticRunDTO | None
    latest_manual_run: DiagnosticRunDTO | None
    scheduler_state: Literal['DISABLED', 'WAITING', 'DUE', 'RUNNING', 'DELAYED']
    last_scheduled_run_at: datetime | None
    next_expected_at: datetime | None
    warning_count: int = Field(ge=0)
    warnings: list[Literal['STALE_RUNNING', 'SCHEDULED_ACTIVITY_DELAYED']]


class DiagnosticsDTO(PublicModel):
    """Safe aggregate diagnostics response."""

    overall_status: Literal['HEALTHY', 'DEGRADED', 'UNHEALTHY']
    generated_at: datetime
    components: DiagnosticComponentsDTO
    sources: list[SourceDiagnosticDTO]
    stale_runs: list[DiagnosticWarningDTO]
    warnings: list[DiagnosticWarningDTO]

    @classmethod
    def from_result(cls, result):
        """Copy only explicitly public diagnostic fields."""
        component_names = ('api', 'registry', 'run_history', 'discovery_worker',
                           'apply_worker', 'scheduler')
        components = DiagnosticComponentsDTO(**{
            name: DiagnosticComponentDTO(**vars(result.components[name]))
            for name in component_names
        })
        sources = [SourceDiagnosticDTO(
            source_instance=value.source_instance, source_type=value.source_type,
            enabled=value.enabled, sync_enabled=value.sync_enabled,
            sync_interval_seconds=value.sync_interval_seconds, status=value.status,
            latest_run=DiagnosticRunDTO(**vars(value.latest_run)) if value.latest_run else None,
            latest_success_at=value.latest_success_at,
            latest_scheduled_run=(DiagnosticRunDTO(**vars(value.latest_scheduled_run))
                                  if value.latest_scheduled_run else None),
            latest_manual_run=(DiagnosticRunDTO(**vars(value.latest_manual_run))
                               if value.latest_manual_run else None),
            scheduler_state=value.scheduler_state,
            last_scheduled_run_at=value.last_scheduled_run_at,
            next_expected_at=value.next_expected_at,
            warning_count=value.warning_count, warnings=list(value.warnings),
        ) for value in result.sources]
        warning = lambda value: DiagnosticWarningDTO(**vars(value))
        return cls(overall_status=result.overall_status.value,
                   generated_at=result.generated_at, components=components,
                   sources=sources, stale_runs=[warning(value) for value in result.stale_runs],
                   warnings=[warning(value) for value in result.warnings])


class VersionDTO(PublicModel):
    """Package metadata, independent of Git."""

    name: str = 'NetBox Sync'
    version: str


class ErrorDetailDTO(PublicModel):
    """Stable error envelope with server-generated correlation."""

    code: str
    message: str
    request_id: str


class ErrorDTO(PublicModel):
    """Never includes exception details, request input or internal configuration."""

    error: ErrorDetailDTO


class SourceDTO(PublicModel):
    """Explicit source projection; list and detail share the same safe fields."""

    source_instance: str
    type: Literal['proxmox', 'esxi']
    name: str
    address: str
    enabled: bool
    sync_enabled: bool
    verify_ssl: bool
    sync_interval_seconds: int
    site_slug: str
    cluster_name: str
    platform_slug: str
    device_role_slug: str
    device_type_slug: str
    cluster_type_slug: str
    legacy_identity_owner: bool
    status: Literal['enabled', 'disabled', 'sync_disabled']

    @classmethod
    def from_view(cls, view):
        """Copy only named DTO fields, never serialize arbitrary internal state."""
        return cls(
            source_instance=view.source_instance, type=view.type, name=view.name, address=view.address,
            enabled=view.enabled, sync_enabled=view.sync_enabled, verify_ssl=view.verify_ssl,
            sync_interval_seconds=view.sync_interval_seconds, site_slug=view.site_slug,
            cluster_name=view.cluster_name, platform_slug=view.platform_slug,
            device_role_slug=view.device_role_slug, device_type_slug=view.device_type_slug,
            cluster_type_slug=view.cluster_type_slug, legacy_identity_owner=view.legacy_identity_owner,
            status=view.status,
        )


class SourceListDTO(PublicModel):
    """Stable list envelope including an empty registry."""

    sources: list[SourceDTO]


class ScheduleUpdateDTO(PublicModel):
    """Optimistic update of only automatic synchronization fields."""

    sync_enabled: bool
    sync_interval_seconds: int = Field(strict=True, ge=60, le=86400)
    expected_sync_enabled: bool
    expected_sync_interval_seconds: int = Field(strict=True, gt=0, le=2147483647)


class ScheduleDTO(PublicModel):
    """Public derived schedule state."""

    source_instance: str
    sync_enabled: bool
    sync_interval_seconds: int
    scheduler_state: Literal['DISABLED', 'WAITING', 'DUE', 'RUNNING', 'DELAYED']
    last_scheduled_run_at: datetime | None
    next_expected_at: datetime | None

    @classmethod
    def from_view(cls, view):
        """Copy the exact schedule application projection."""
        return cls(**vars(view))


class DiscoveryItemDTO(PublicModel):
    object_kind: Literal['host', 'qemu', 'lxc', 'vm']
    name: str
    external_id: str
    classification: Literal['MANAGED', 'REVIEW_REQUIRED', 'WOULD_CREATE', 'IGNORED',
                            'UNSUPPORTED', 'CONFLICT', 'NO_CHANGE']
    reason_code: str
    reason: str
    future_action: Literal['none', 'create', 'update', 'review', 'ignored', 'unsupported']
    matched_object_id: int | str | None = None
    matched_object_name: str | None = None


class DiscoveryResultDTO(PublicModel):
    source_instance: str
    source_type: Literal['proxmox', 'esxi']
    site_slug: str
    cluster_name: str
    items: list[DiscoveryItemDTO]

    @classmethod
    def from_worker(cls, value):
        """Validate every allowlisted worker field before public serialization."""
        return cls.model_validate(value)


class SyncPlanItemDTO(PublicModel):
    """Exact allowlisted action in a canonical sync plan."""

    object_kind: str
    external_id: str
    name: str
    action: Literal['CREATE', 'UPDATE', 'NO_CHANGE', 'REVIEW_REQUIRED', 'BLOCKED',
                    'IGNORED', 'UNSUPPORTED', 'RETAIN_ONLY']
    reason_code: str
    reason: str
    matched_object_id: int | str | None = None
    before: list[list[object]]
    after: list[list[object]]


class SyncPlanDTO(PublicModel):
    """Secret-free plan returned by the read-only worker."""

    source_instance: str
    source_type: Literal['proxmox', 'esxi']
    source_fingerprint: str
    target_fingerprint: str
    provider_fingerprint: str
    netbox_fingerprint: str
    schema_version: int
    planner_version: str
    items: list[SyncPlanItemDTO]
    apply_allowed: bool
    digest: str = Field(pattern=r'^[a-f0-9]{64}$')

    @classmethod
    def from_worker(cls, value):
        """Exclude the internal registry ID while retaining its binding inside the digest."""
        if not isinstance(value, dict):
            return cls.model_validate(value)
        return cls.model_validate({key: item for key, item in value.items() if key != 'source_id'})


class SyncPlanRequestDTO(PublicModel):
    """An intentionally empty request: the browser cannot select scope or operations."""


class ConfirmationRequestDTO(PublicModel):
    """The browser may identify an exact plan but cannot submit operations."""

    plan_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    operation_id: UUID | None = None
    confirmed: Literal[True]


class ConfirmationDTO(PublicModel):
    """Short-lived opaque capability; its value is never logged."""

    confirmation_token: str = Field(pattern=r'^[a-f0-9]{64}$')
    expires_in_seconds: int = 300


class ApplyRequestDTO(PublicModel):
    """Only a worker-issued capability crosses the API boundary."""

    confirmation_token: str = Field(pattern=r'^[a-f0-9]{64}$')
    operation_id: UUID | None = None


class ApplyResultDTO(PublicModel):
    """Explicit non-transactional synchronization result."""

    status: Literal['SUCCEEDED', 'FAILED_BEFORE_WRITE', 'PARTIALLY_APPLIED', 'OUTCOME_UNCERTAIN']
    plan_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    run_id: UUID | None = None


class RunActionSummaryDTO(PublicModel):
    """Canonical plan action totals."""

    create: int = Field(ge=0)
    update: int = Field(ge=0)
    no_change: int = Field(ge=0)
    review_required: int = Field(ge=0)
    blocked: int = Field(ge=0)
    ignored: int = Field(ge=0)
    unsupported: int = Field(ge=0)
    retain_only: int = Field(ge=0)


class SyncRunDTO(PublicModel):
    """Explicit safe synchronization history projection."""

    run_id: UUID
    source_instance: str = Field(pattern=r'^[a-z0-9][a-z0-9._-]{1,62}$')
    source_type: Literal['proxmox', 'esxi']
    trigger: Literal['manual', 'scheduled']
    status: Literal['RUNNING', 'SUCCEEDED', 'FAILED_BEFORE_WRITE', 'PARTIALLY_APPLIED',
                    'OUTCOME_UNCERTAIN', 'BLOCKED', 'LOCKED', 'FAILED']
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None = Field(default=None, ge=0)
    plan_digest: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    planner_version: str | None = Field(default=None, max_length=128)
    actions: RunActionSummaryDTO
    error_code: Literal['APPLY_LOCKED', 'PLAN_BLOCKED', 'PLAN_STALE',
                        'CONFIRMATION_EXPIRED', 'CONFIRMATION_INVALID',
                        'CONFIRMATION_SOURCE_MISMATCH', 'FAILED_BEFORE_WRITE',
                        'PARTIALLY_APPLIED', 'OUTCOME_UNCERTAIN', 'APPLY_FAILED'] | None
    error_message_safe: str | None = Field(default=None, max_length=256)
    created_by: str = Field(min_length=1, max_length=128)

    @classmethod
    def from_record(cls, record):
        """Allowlist persisted fields and exclude every internal value."""
        return cls(
            run_id=str(record.run_id), source_instance=record.source_instance,
            source_type=record.source_type, trigger=record.trigger.value,
            status=record.status.value, started_at=record.started_at,
            finished_at=record.finished_at, duration_ms=record.duration_ms,
            plan_digest=record.plan_digest, planner_version=record.planner_version,
            actions=RunActionSummaryDTO(**record.counts.__dict__),
            error_code=record.error_code, error_message_safe=record.error_message_safe,
            created_by=record.created_by,
        )


class SyncRunListDTO(PublicModel):
    """Compact bounded history page."""

    runs: list[SyncRunDTO]
    next_cursor: str | None = None
