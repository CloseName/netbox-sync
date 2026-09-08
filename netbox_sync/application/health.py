"""Read-only health policy, independent of HTTP and database implementations."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .observability import ErrorCode


class HealthStatus(str, Enum):
    """Public component states; unknown is not proof of availability."""

    HEALTHY = 'healthy'
    DEGRADED = 'degraded'
    UNAVAILABLE = 'unavailable'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class ComponentHealth:
    """Allowlisted health data, never an exception or internal configuration."""

    status: HealthStatus
    message: str
    error_code: ErrorCode | None = None


@dataclass(frozen=True)
class SystemHealth:
    """Fixed components make accidental serialization of internal objects unnecessary."""

    status: HealthStatus
    api: ComponentHealth
    application: ComponentHealth
    database: ComponentHealth
    registry: ComponentHealth
    netbox: ComponentHealth


class RegistryHealthProbe(Protocol):
    """Read-only database and registry availability check."""

    def check(self) -> tuple[ComponentHealth, ComponentHealth]:
        """Return database and registry states without resolving credentials."""


class SystemHealthService:
    """Compose safe readiness information; never execute sync or discovery."""

    def __init__(self, probe: RegistryHealthProbe, *, netbox_configured: bool):
        self._probe = probe
        self._netbox_configured = netbox_configured

    def check(self) -> SystemHealth:
        """Healthy means API/registry ready, not that external sync targets were tested."""
        database, registry = self._probe.check()
        try:
            configured = self._netbox_configured() if callable(self._netbox_configured) else self._netbox_configured
        except Exception:
            configured = False
        if HealthStatus.UNAVAILABLE in (database.status, registry.status):
            overall = HealthStatus.UNAVAILABLE
        elif (database.status != HealthStatus.HEALTHY
              or registry.status != HealthStatus.HEALTHY or not configured):
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY
        netbox_message = (
            'Configuration present; connectivity and credentials not checked'
            if configured else 'Configuration incomplete; connectivity not checked'
        )
        return SystemHealth(
            overall,
            ComponentHealth(HealthStatus.HEALTHY, 'API is responding'),
            ComponentHealth(HealthStatus.HEALTHY, 'Application health service is responding'),
            database, registry,
            ComponentHealth(HealthStatus.UNKNOWN, netbox_message),
        )
