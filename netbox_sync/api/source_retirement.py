"""Admin-only review, confirmation and status; no NetBox credentials in API."""

from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from ..auth_policy import AuthError


class Status(BaseModel):
    """Identify a durable source retirement operation."""

    model_config = ConfigDict(extra="forbid")
    operation_id: UUID


class Review(Status):
    """Bind retirement review to the expected source revision."""

    revision: str = Field(pattern="^[a-f0-9]{64}$")


class Confirm(Status):
    """Confirm reviewed retirement evidence, source name and credential-cleanup choice."""

    digest: str = Field(pattern="^[a-f0-9]{64}$")
    confirmed: Literal[True]
    confirmed_source: str = Field(min_length=1, max_length=200)
    remove_credentials: StrictBool = True

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit(cls, value):
        """Require literal boolean confirmation before retirement execution."""

        if value is not True:
            raise ValueError("Explicit confirmation required")
        return value


class Queue(Review):
    """Explicit revision-bound confirmation for queued source removal."""

    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit(cls, value):
        """Require literal boolean confirmation before queuing removal."""

        if value is not True:
            raise ValueError("Explicit confirmation required")
        return value


def admin(http):
    """Extract an administrator actor only from authenticated middleware state."""

    # principal is supplied only by the existing authenticated server middleware.
    # Client role/body/header assertions are never consulted.
    principal = getattr(http.state, "principal", None)
    if not isinstance(principal, dict) or principal.get("role") != "admin":
        raise AuthError("AUTH_DENIED")
    actor = principal.get("principal_id")
    if not isinstance(actor, str) or not actor:
        raise AuthError("AUTH_DENIED")
    return actor


def routes(lifecycle):
    """Build administrator-only retirement review, confirmation, resume and status endpoints."""

    router = APIRouter(prefix="/api/v1/sources")

    @router.post("/lifecycle-review")
    def generations(http: Request):
        admin(http)
        return lifecycle.generations()

    @router.post("/{source}/archive-check")
    def archive_check(source: str, http: Request):
        return lifecycle.retirement("archive_check", source, actor_id=admin(http))

    @router.post("/{source}/archive-review")
    def archive_review(source: str, payload: Review, http: Request):
        return lifecycle.retirement(
            "archive_review",
            source,
            operation_id=str(payload.operation_id),
            actor_id=admin(http),
            revision=payload.revision,
        )

    @router.post("/{source}/retirement-context")
    def retained_context(source: str, http: Request):
        return lifecycle.retirement("context", source, actor_id=admin(http))

    @router.post("/{source}/removal-request")
    def enqueue(source: str, payload: Queue, http: Request):
        return lifecycle.removal(
            "request",
            source,
            operation_id=str(payload.operation_id),
            actor_id=admin(http),
            revision=payload.revision,
            confirmed=payload.confirmed,
        )

    @router.post("/{source}/removal-status")
    def queued_status(source: str, payload: Status, http: Request):
        return lifecycle.removal("status", source, operation_id=str(payload.operation_id), actor_id=admin(http))

    @router.post("/{source}/retirement-review")
    def review(source: str, payload: Review, http: Request):
        return lifecycle.retirement(
            "review", source, operation_id=str(payload.operation_id), actor_id=admin(http), revision=payload.revision
        )

    @router.post("/{source}/retire")
    def execute(source: str, payload: Confirm, http: Request):
        return lifecycle.retirement(
            "execute",
            source,
            operation_id=str(payload.operation_id),
            actor_id=admin(http),
            digest=payload.digest,
            confirmed_source=payload.confirmed_source,
            remove_credentials=payload.remove_credentials,
        )

    @router.post("/{source}/retirement-resume")
    def resume(source: str, payload: Confirm, http: Request):
        return lifecycle.retirement(
            "resume",
            source,
            operation_id=str(payload.operation_id),
            actor_id=admin(http),
            digest=payload.digest,
            confirmed_source=payload.confirmed_source,
            remove_credentials=payload.remove_credentials,
        )

    @router.post("/{source}/retirement-status")
    def status(source: str, payload: Status, http: Request):
        return lifecycle.retirement("status", source, operation_id=str(payload.operation_id), actor_id=admin(http))

    return router
