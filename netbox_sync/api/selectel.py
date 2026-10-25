"""Account inventory operations; credentials never enter response DTOs."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from .auth import COOKIE
from ..local_control import request as control


class Account(BaseModel):
    """Experimental Selectel account connection fields with a protected password."""

    model_config = ConfigDict(extra="forbid")
    account: str = Field(pattern=r"^[0-9]{1,20}$")
    name: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=1024)


class Schedule(BaseModel):
    """Experimental Selectel schedule envelope validated by the control worker."""

    model_config = ConfigDict(extra="forbid")
    schedule: dict


class Enabled(BaseModel):
    """Strict boolean control for an experimental Selectel account."""

    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


class Lifecycle(BaseModel):
    """Experimental Selectel lifecycle operation and optional resource key."""

    model_config = ConfigDict(extra="forbid", strict=True)
    operation: str = Field(pattern=r"^(delete|detach|activate)$")
    key: str | None = None


class LifecycleExecute(Lifecycle):
    """Digest-bound experimental Selectel lifecycle execution confirmation."""

    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: bool


def routes(settings):
    """Build experimental Selectel account, collection, schedule and lifecycle routes."""

    router = APIRouter(prefix="/api/v1/selectel")

    def call(request, operation, data):
        result = control(
            settings.bootstrap_socket,
            {"action": "selectel", "operation": operation, "session": request.cookies.get(COOKIE), "data": data},
            timeout=200 if operation == "reconcile" else 100 if operation.startswith("lifecycle-") else 10,
            response_limit=2 * 1024 * 1024,
        )["result"]
        return JSONResponse(
            result,
            status_code=(
                409 if result.get("error") and not (operation == "reconcile" and result.get("reconciliation")) else 200
            ),
            headers={"Cache-Control": "no-store"},
        )

    @router.get("")
    def accounts(request: Request):
        return call(request, "list", {})

    @router.post("")
    def save(request: Request, payload: Account):
        data = payload.model_dump()
        data["password"] = payload.password.get_secret_value()
        return call(request, "save", data)

    @router.post("/{account}/collect")
    def collect(request: Request, account: str):
        return call(request, "collect", {"account": account})

    @router.post("/{account}/reconcile")
    def reconcile(request: Request, account: str):
        return call(request, "reconcile", {"account": account})

    @router.post("/{account}/schedule")
    def schedule(request: Request, account: str, payload: Schedule):
        return call(request, "schedule", {"account": account, **payload.model_dump()})

    @router.post("/{account}/enabled")
    def enabled(request: Request, account: str, payload: Enabled):
        return call(request, "enabled", {"account": account, **payload.model_dump()})

    @router.post("/{account}/lifecycle-review")
    def lifecycle_review(request: Request, account: str, payload: Lifecycle):
        return call(request, "lifecycle-review", {"account": account, **payload.model_dump()})

    @router.post("/{account}/lifecycle-execute")
    def lifecycle_execute(request: Request, account: str, payload: LifecycleExecute):
        return call(request, "lifecycle-execute", {"account": account, **payload.model_dump()})

    return router
