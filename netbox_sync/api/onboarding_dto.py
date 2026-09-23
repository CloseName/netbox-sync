"""Strict onboarding transport inputs; secrets are excluded from repr and serialization."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator

from ..application.onboarding import PendingCredentials, RegistrationCommand
from ..application.sources import SourceReadError, source_view
from .dto import PublicModel
from .egress import validate_host


class ConnectionRequest(PublicModel):
    """Credentials are accepted only in JSON bodies, never URL parameters."""

    recovery_source: str | None = Field(default=None,pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
    preview: bool = Field(default=False, strict=True)
    source_type: Literal['proxmox', 'esxi']
    address: str = Field(min_length=1, max_length=253)
    verify_ssl: bool = Field(default=True, strict=True)
    port: int | None = Field(default=None, strict=True, ge=1, le=65535)
    username: Annotated[SecretStr, Field(exclude=True, repr=False)]
    token_id: Annotated[SecretStr | None, Field(exclude=True, repr=False)] = None
    secret: Annotated[SecretStr, Field(exclude=True, repr=False)]

    @field_validator('address')
    @classmethod
    def endpoint(cls, value):
        validate_host(value)
        return value

    @model_validator(mode='after')
    def credentials_valid(self):
        values = [self.username.get_secret_value(), self.secret.get_secret_value()]
        if self.source_type == 'proxmox':
            if self.token_id is None:
                raise ValueError('Token name required')
            values.append(self.token_id.get_secret_value())
            if '!' in values[-1]:
                raise ValueError('Use the token name without user prefix')
        elif self.token_id is not None:
            raise ValueError('Token name is not used for ESXi')
        if any(not value.strip() or value != value.strip() or len(value.encode()) > 4096
               or '\x00' in value for value in values):
            raise ValueError('Credential field invalid')
        return self

    def credentials(self):
        """Create ephemeral internal values, never a public response."""
        return PendingCredentials(
            self.source_type, self.address, self.verify_ssl, self.username.get_secret_value(),
            self.token_id.get_secret_value() if self.token_id else '', self.secret.get_secret_value(), port=self.port,
        )


class ConnectionResult(PublicModel):
    """One-time registration capability; no credential echo."""

    status: Literal['success'] = 'success'
    message: str = 'Connection and authentication succeeded'
    onboarding_token: str = Field(repr=False)
    expires_in_seconds: int = 600
    preview: dict | None = None
    suggested_source_instance: str | None = None


class CancellationRequest(PublicModel):
    """Opaque token to revoke, never echoed or logged."""

    onboarding_token: str = Field(min_length=20, max_length=128, repr=False, exclude=True)


class CancellationResult(PublicModel):
    """Idempotent acknowledgement without revealing token existence."""

    status: Literal['cancelled'] = 'cancelled'


class RegistrationRequest(PublicModel):
    """Immutable metadata plus an opaque, single-use onboarding capability."""

    onboarding_token: str = Field(min_length=20, max_length=128, repr=False, exclude=True)
    source_type: Literal['proxmox', 'esxi']
    source_instance: str = Field(pattern=r'^[a-z0-9][a-z0-9._-]{1,62}$')
    name: str
    address: str
    verify_ssl: bool = Field(strict=True)
    port: int | None = Field(default=None, strict=True, ge=1, le=65535)
    sync_interval_seconds: int = Field(strict=True, gt=0, le=2147483647)
    site_slug: str
    cluster_name: str
    platform_slug: str
    device_role_slug: str
    device_type_slug: str
    cluster_type_slug: str
    references: dict[str, dict] = Field(default_factory=dict, max_length=5)
    host_types: dict[str, dict] = Field(default_factory=dict, max_length=16)
    create_cluster: bool = Field(default=False, strict=True)
    automatic_placement: bool = Field(default=False, strict=True)
    registration_id: UUID | None = None
    confirm_sync_disabled: Literal[True]

    @field_validator('confirm_sync_disabled', mode='before')
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError('Explicit boolean confirmation required')
        return value

    @model_validator(mode='after')
    def public_fields(self):
        if self.create_cluster and (not self.registration_id or self.cluster_name != self.name or len(self.name)>100 or 'cluster' in self.references):
            raise ValueError('Cluster creation must match the source name and confirmed registration')
        try:
            source_view(dict(
                source_instance=self.source_instance, source_type=self.source_type, name=self.name, address=self.address,
                enabled=True, sync_enabled=False, verify_ssl=self.verify_ssl,
                sync_interval_seconds=self.sync_interval_seconds, site_slug=self.site_slug,
                cluster_name=self.cluster_name, platform_slug=self.platform_slug, device_role_slug=self.device_role_slug,
                device_type_slug=self.device_type_slug, cluster_type_slug=self.cluster_type_slug, legacy_identity_owner=False,
            ))
        except SourceReadError:
            raise ValueError('Invalid source metadata') from None
        return self

    def command(self):
        """Translate explicitly to application command, retaining no transport dependency."""
        return RegistrationCommand(
            onboarding_token=self.onboarding_token, source_type=self.source_type,
            source_instance=self.source_instance, name=self.name, address=self.address,
            verify_ssl=self.verify_ssl, port=self.port, sync_interval_seconds=self.sync_interval_seconds,
            site_slug=self.site_slug, cluster_name=self.cluster_name, platform_slug=self.platform_slug,
            device_role_slug=self.device_role_slug, device_type_slug=self.device_type_slug,
            cluster_type_slug=self.cluster_type_slug, confirm_sync_disabled=self.confirm_sync_disabled,
        )


class PlacementReviewRequest(PublicModel):
    """Read-only placement revalidation before registration confirmation."""
    onboarding_token: str = Field(min_length=20, max_length=128, repr=False, exclude=True)
    references: dict[str, dict] = Field(max_length=5)
    host_types: dict[str, dict] = Field(max_length=16)
    create_cluster: bool = Field(default=False, strict=True)


class DestinationRequest(PublicModel):
    source_type: Literal['proxmox','esxi']
    address: str = Field(min_length=1,max_length=253)
    port: int | None = Field(default=None,strict=True,ge=1,le=65535)

    @field_validator('address')
    @classmethod
    def endpoint(cls,value):
        return validate_host(value)


class RegistrationStatusRequest(PublicModel):
    source_instance: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,62}$")
    registration_id: UUID


class PlacementResolutionRequest(PublicModel):
    onboarding_token: str = Field(min_length=20,max_length=128,repr=False,exclude=True)
    name: str = Field(max_length=100)
    site_id: int | None = Field(default=None,strict=True,gt=0)
