"""Secret-free bootstrap projection and narrow local control routes."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool
from fastapi import APIRouter
from ..local_control import request, ControlError


class Revision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0, strict=True)


class Configuration(Revision):
    url: str = Field(max_length=2048)
    read_token: SecretStr = Field(min_length=8, max_length=4096)
    apply_token: SecretStr = Field(min_length=8, max_length=4096)
    replace_credentials: StrictBool = False


class SetupApply(Revision):
    digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    confirm: StrictBool
    setup_token: SecretStr = Field(min_length=8, max_length=4096)


class Check(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str
    type: Literal['text', 'integer', 'json']
    models: list[str]
    ok: StrictBool


class AccessCheck(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Literal['network','tls','read_auth','apply_auth','permissions','prerequisites']
    status: Literal['not_run','passed','failed','preliminary','pending']


class Translation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    en: str
    ru: str


class PreparationField(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str
    type: Literal['text','integer','json']
    models: list[str]
    status: Literal['missing','ready','conflict','provisioning']
    differences: list[str]
    id: int | None
    label: Translation
    purpose: Translation


class PreparationState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int | None = None
    status: Literal['PLANNED','RUNNING','UNCERTAIN','CANCELLED','STALE','TOKEN_REJECTED','EXPIRED','REJECTED','PREPARED','WAITING']
    fields: list[PreparationField] = Field(default_factory=list)
    digest: str | None = None
    planned_at: float | None = None
    started_at: float | None = None
    run_id: str | None = None
    uncertain: str | None = None
    created: list[str] = Field(default_factory=list)
    revocation: Literal['NOT_ATTEMPTED','CONFIRMED','UNCONFIRMED'] = 'NOT_ATTEMPTED'
    local_secret: Literal['NOT_STORED','MEMORY_ONLY']


class State(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int
    status: Literal['FRESH','CONFIGURED','VALIDATING','VALIDATED','READY','ATTENTION']
    url: str
    completed: StrictBool
    read_token_present: StrictBool
    apply_token_present: StrictBool
    safe_code: Literal['NETWORK_UNREACHABLE','TLS_FAILED','AUTH_FAILED','PERMISSION_DENIED',
                       'RESPONSE_INVALID','PREREQUISITES_MISSING','DESTINATION_DENIED',
                       'VALIDATION_UNAVAILABLE','VALIDATION_INTERRUPTED'] | None
    checks: list[Check]
    validated_at: float | None
    preparation: PreparationState | None = None
    access_checks: list[AccessCheck] = Field(default_factory=list)


class BootstrapClient:
    def __init__(self, path):
        self.path = path

    def call(self, action, payload=None):
        try:
            response = request(self.path, {'action': action, **(payload or {})}, timeout=220 if action=='prerequisites-apply' else 50 if action in ('validate','prerequisites-plan') else 10)
            return State.model_validate(response['result'])
        except ControlError:
            raise
        except Exception:
            raise ControlError() from None


def routes(client):
    router = APIRouter(prefix='/api/v1/bootstrap')

    @router.get('', response_model=State)
    def status():
        return client.call('status')

    @router.post('/configuration', response_model=State)
    def configure(payload: Configuration):
        value = payload.model_dump(exclude={'read_token','apply_token'})
        value['read_token'] = payload.read_token.get_secret_value()
        value['apply_token'] = payload.apply_token.get_secret_value()
        return client.call('configure', value)

    @router.post('/validate', response_model=State)
    def validate(payload: Revision):
        return client.call('validate', payload.model_dump())

    @router.post('/finish', response_model=State)
    def finish(payload: Revision):
        return client.call('finish', payload.model_dump())

    @router.post('/prerequisites-plan', response_model=State)
    def prerequisite_plan(payload: Revision):
        return client.call('prerequisites-plan', payload.model_dump())

    @router.post('/prerequisites-cancel', response_model=State)
    def prerequisite_cancel(payload: Revision):
        return client.call('prerequisites-cancel', payload.model_dump())

    @router.post('/prerequisites-apply', response_model=State)
    def prerequisite_apply(payload: SetupApply):
        value = payload.model_dump(exclude={'setup_token'})
        value['setup_token'] = payload.setup_token.get_secret_value()
        return client.call('prerequisites-apply', value)

    return router
