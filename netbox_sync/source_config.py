"""Immutable configuration models for one infrastructure source."""

import os
import re
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping


SOURCE_INSTANCE_PATTERN = re.compile(
    r'^[a-z0-9][a-z0-9._-]{1,62}$'
)
SOURCE_TYPE_PATTERN = re.compile(
    r'^[a-z][a-z0-9_-]{1,31}$'
)


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f'{field_name} must be a non-empty string'
        )


def _required_environment(environ, variable_name: str) -> str:
    value = environ.get(variable_name, '').strip()

    if not value:
        raise ValueError(
            f'{variable_name} must be configured'
        )

    return value


def _environment_flag(environ, variable_name: str, default: str) -> bool:
    return (
        environ.get(variable_name, default)
        .strip()
        .lower()
        == 'true'
    )


def _legacy_secret_reference(environ, variable_name: str):
    file_variable = f'{variable_name}_FILE'
    file_path = environ.get(file_variable, '').strip()

    if file_path:
        return SecretReference(
            provider='file',
            key=file_path,
        )

    if environ.get(variable_name, '').strip():
        return SecretReference(
            provider='environment',
            key=variable_name,
        )

    raise ValueError(
        f'{variable_name} or {file_variable} must be configured'
    )


@dataclass(frozen=True)
class NetBoxTargetConfig:
    """NetBox objects to which one source is reconciled."""

    site_slug: str
    device_role_slug: str
    platform_slug: str
    device_type_slug: str
    cluster_type_slug: str
    cluster_name: str
    onboarding_mapping: dict = field(default_factory=dict)

    def __post_init__(self):
        for field_name in (
            'site_slug',
            'device_role_slug',
            'platform_slug',
            'device_type_slug',
            'cluster_type_slug',
            'cluster_name',
        ):
            _require_text(
                getattr(self, field_name),
                field_name,
            )


@dataclass(frozen=True)
class SecretReference:
    """Opaque reference to a secret; never the secret value itself."""

    provider: str
    key: str

    def __post_init__(self):
        _require_text(self.provider, 'provider')
        _require_text(self.key, 'key')


@dataclass(frozen=True, repr=False)
class SourceCredentials:
    """Non-secret username and references to source API credentials."""

    username: str
    token_id: SecretReference
    token_secret: SecretReference

    def __post_init__(self):
        _require_text(self.username, 'username')

    @classmethod
    def for_password(cls, username, password_reference):
        """Build backward-compatible username/password credentials."""

        return cls(
            username=username,
            token_id=password_reference,
            token_secret=password_reference,
        )

    @property
    def password_reference(self):
        """Return the password reference for password-based source types."""

        return self.token_secret


@dataclass(frozen=True)
class SourceConfig:
    """Complete immutable configuration for one discovery source."""

    id: str
    source_instance: str
    name: str
    source_type: str
    address: str
    enabled: bool
    sync_enabled: bool
    sync_interval_seconds: int
    verify_ssl: bool
    target: NetBoxTargetConfig
    credentials: SourceCredentials
    legacy_identity_owner: bool = False
    settings: Mapping[str, object] = field(
        default_factory=dict
    )

    def __post_init__(self):
        for field_name in (
            'id',
            'name',
            'address',
        ):
            _require_text(
                getattr(self, field_name),
                field_name,
            )

        if not SOURCE_INSTANCE_PATTERN.fullmatch(
            self.source_instance
        ):
            raise ValueError(
                'source_instance must match '
                '^[a-z0-9][a-z0-9._-]{1,62}$'
            )

        if not SOURCE_TYPE_PATTERN.fullmatch(
            self.source_type
        ):
            raise ValueError(
                'source_type must match '
                '^[a-z][a-z0-9_-]{1,31}$'
            )

        if (
            not isinstance(self.sync_interval_seconds, int)
            or isinstance(self.sync_interval_seconds, bool)
            or self.sync_interval_seconds <= 0
        ):
            raise ValueError(
                'sync_interval_seconds must be '
                'a positive integer'
            )

        if not isinstance(self.settings, Mapping):
            raise ValueError('settings must be a mapping')

        if self.settings.get('onboarding_mapping'):
            object.__setattr__(self,'target',replace(self.target,onboarding_mapping=dict(self.settings['onboarding_mapping'])))

        object.__setattr__(
            self,
            'settings',
            MappingProxyType(dict(self.settings)),
        )

    @classmethod
    def from_legacy_environment(cls, environ=None):
        """Build the single source represented by legacy environment variables."""

        if environ is None:
            environ = os.environ

        source_instance = _required_environment(
            environ,
            'SOURCE_INSTANCE',
        )

        try:
            sync_interval_seconds = int(
                environ.get(
                    'SOURCE_SYNC_INTERVAL_SECONDS',
                    '600',
                )
            )
        except ValueError as exc:
            raise ValueError(
                'SOURCE_SYNC_INTERVAL_SECONDS must be an integer'
            ) from exc

        return cls(
            id=(
                environ.get('SOURCE_ID', '').strip()
                or source_instance
            ),
            source_instance=source_instance,
            name=(
                environ.get('SOURCE_NAME', '').strip()
                or source_instance
            ),
            source_type='proxmox',
            address=_required_environment(
                environ,
                'PVE_API_HOST',
            ),
            enabled=_environment_flag(
                environ,
                'SOURCE_ENABLED',
                'true',
            ),
            sync_enabled=_environment_flag(
                environ,
                'SOURCE_SYNC_ENABLED',
                'true',
            ),
            sync_interval_seconds=sync_interval_seconds,
            verify_ssl=_environment_flag(
                environ,
                'PVE_API_VERIFY_SSL',
                'false',
            ),
            target=NetBoxTargetConfig(
                site_slug=_required_environment(
                    environ,
                    'NB_SITE_SLUG',
                ),
                device_role_slug=_required_environment(
                    environ,
                    'NB_DEVICE_ROLE_SLUG',
                ),
                platform_slug=_required_environment(
                    environ,
                    'NB_PLATFORM_SLUG',
                ),
                device_type_slug=_required_environment(
                    environ,
                    'NB_DEVICE_TYPE_SLUG',
                ),
                cluster_type_slug=_required_environment(
                    environ,
                    'NB_CLUSTER_TYPE_SLUG',
                ),
                cluster_name=_required_environment(
                    environ,
                    'NB_CLUSTER_NAME',
                ),
            ),
            credentials=SourceCredentials(
                username=_required_environment(
                    environ,
                    'PVE_API_USER',
                ),
                token_id=_legacy_secret_reference(
                    environ,
                    'PVE_API_TOKEN',
                ),
                token_secret=_legacy_secret_reference(
                    environ,
                    'PVE_API_SECRET',
                ),
            ),
            legacy_identity_owner=_environment_flag(
                environ,
                'SOURCE_LEGACY_IDENTITY_OWNER',
                'true',
            ),
            settings={},
        )
