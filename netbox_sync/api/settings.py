"""Snapshot API configuration once at bootstrap, not inside domain services."""

import os
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from .egress import EgressPolicy
from ..application.scheduling import stale_threshold


@dataclass(frozen=True)
class ApiSettings:
    """Reuse registry conventions; no source or NetBox credential resolution."""

    public_url: str = ''
    registry_dsn: str = field(default='', repr=False)
    registry_schema: str = ''
    netbox_configured: bool = False
    web_dist: str = field(default='', repr=False)
    registration_dsn: str = field(default='', repr=False)
    broker_socket: str = field(default='', repr=False)
    lifecycle_socket: str = field(default='', repr=False)
    bootstrap_socket: str = field(default='', repr=False)
    discovery_socket: str = field(default='', repr=False)
    apply_socket: str = field(default='', repr=False)
    schedule_socket: str = field(default='', repr=False)
    diagnostics_stale_seconds: int = 7200
    allowed_write_hosts: tuple[str, ...] = ('127.0.0.1:8000', 'localhost:8000')
    egress_policy: EgressPolicy = field(default_factory=EgressPolicy)

    @classmethod
    def from_environment(cls, environ=None):
        """Read only required configuration; never log or serialize the environment."""
        env = os.environ if environ is None else environ
        stale_seconds = stale_threshold(env.get('NETBOX_SYNC_DIAGNOSTICS_STALE_SECONDS', '7200'))
        public_url=env.get('NETBOX_SYNC_PUBLIC_URL','')
        if public_url:
            from ..tls_config import public_authority
            public_authority(public_url)
        return cls(
            public_url=public_url,
            registry_dsn=env.get('NETBOX_SYNC_REGISTRY_DSN', '').strip(),
            registry_schema=env.get('NETBOX_SYNC_REGISTRY_SCHEMA', '').strip(),
            netbox_configured=bool(
                env.get('NB_API_URL', '').strip()
                and (env.get('NB_API_TOKEN', '').strip() or env.get('NB_API_TOKEN_FILE', '').strip())
            ),
            web_dist=env.get('NETBOX_SYNC_WEB_DIST', '').strip(),
            registration_dsn=env.get('NETBOX_SYNC_REGISTRATION_DSN', '').strip(),
            broker_socket=env.get('NETBOX_SYNC_BROKER_SOCKET', '').strip(),
            bootstrap_socket=env.get('NETBOX_SYNC_BOOTSTRAP_SOCKET', '/run/netbox-sync-bootstrap/worker.sock').strip(),
            lifecycle_socket=env.get('NETBOX_SYNC_LIFECYCLE_SOCKET', '/run/netbox-sync-lifecycle/worker.sock').strip(),
            discovery_socket=env.get('NETBOX_SYNC_DISCOVERY_SOCKET', '').strip(),
            apply_socket=env.get('NETBOX_SYNC_APPLY_SOCKET', '').strip(),
            schedule_socket=env.get('NETBOX_SYNC_SCHEDULE_SOCKET', '').strip(),
            diagnostics_stale_seconds=stale_seconds,
            allowed_write_hosts=tuple(value.strip() for value in env.get(
                'NETBOX_SYNC_WRITE_HOSTS', '127.0.0.1:8000,localhost:8000',
            ).split(',') if value.strip()),
            egress_policy=EgressPolicy(**{
                field_name: tuple(item.strip() for item in env.get(variable, '').split(',') if item.strip())
                for field_name, variable in (
                    ('allowed_cidrs', 'NETBOX_SYNC_ONBOARDING_ALLOWED_CIDRS'),
                    ('denied_cidrs', 'NETBOX_SYNC_ONBOARDING_DENIED_CIDRS'),
                    ('allowed_hosts', 'NETBOX_SYNC_ONBOARDING_ALLOWED_HOSTS'),
                    ('allowed_suffixes', 'NETBOX_SYNC_ONBOARDING_ALLOWED_SUFFIXES'),
                )
            }),
        )


def application_version():
    """Distribution version, with a deterministic fallback for uninstalled checkouts."""
    try:
        return version('netbox-sync')
    except PackageNotFoundError:
        return 'development'
