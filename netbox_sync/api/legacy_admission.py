"""Admin-only source-bound investigation; new-source credentials are never reused."""
from uuid import UUID
from typing import Literal
from fastapi import APIRouter,Request
from pydantic import BaseModel,ConfigDict,Field,SecretStr,field_validator
from .auth import COOKIE
from .lifecycle_client import LifecycleRequestError
from ..application.onboarding import EphemeralOnboardingStore
from ..host_registration import esxi_anchor

class Probe(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:str=Field(pattern='^[a-f0-9]{64}$')
    username:SecretStr=Field(exclude=True,repr=False,min_length=1,max_length=512)
    secret:SecretStr=Field(exclude=True,repr=False,min_length=1,max_length=4096)

    @field_validator('username','secret')
    @classmethod
    def valid_credentials(cls,value):
        raw=value.get_secret_value()
        if not raw.strip() or raw!=raw.strip() or len(raw.encode())>4096 or '\x00' in raw:
            raise ValueError('Credential field invalid')
        return value

class Decision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    operation:UUID
    revision:str=Field(pattern='^[a-f0-9]{64}$')
    decision:Literal['ISOLATE','OBSERVE']
    reason:str=Field(min_length=3,max_length=500)
    evidence_token:str|None=Field(default=None,repr=False,max_length=200)
    confirmed:Literal[True]
    @field_validator('confirmed',mode='before')
    @classmethod
    def explicit(cls,value):
        if value is not True:raise ValueError('Explicit confirmation required')
        return value


def routes(settings,auth,lifecycle):
    router=APIRouter(prefix='/api/v1/sources')
    evidence=EphemeralOnboardingStore()
    @router.post('/{source}/legacy-review')
    def review(source:str):return lifecycle.legacy('describe',source)

    @router.post('/{source}/legacy-probe')
    def probe(source:str,payload:Probe,http:Request):
        from ..probe_worker import remote_test_authorized
        meta=lifecycle.legacy('describe',source)
        if meta['revision']!=payload.revision:raise LifecycleRequestError('SOURCE_LIFECYCLE_CONFLICT')
        if not settings.probe_socket:raise LifecycleRequestError('LIFECYCLE_UNAVAILABLE')
        session=http.cookies.get(COOKIE);actor=http.state.principal['principal_id']
        policy=auth.call('probe.policy',session=session)
        from .onboarding_dto import ConnectionRequest
        credentials=ConnectionRequest(source_type='esxi',address=meta['address'],verify_ssl=meta['verify_ssl'],port=meta['port'],username=payload.username,secret=payload.secret).credentials()
        preview=remote_test_authorized(settings.probe_socket,credentials,session,policy['revision'],preview=True)
        anchor=esxi_anchor(preview)
        token=evidence.issue(None,dict(source=source,revision=meta['revision'],actor=actor,anchor=anchor))
        return dict(evidence_token=token,host_uuid=anchor,comparison='OBSERVED_AT_RECORDED_ENDPOINT',physical_identity_proved=False,object_ownership_proved=False)

    @router.post('/{source}/legacy-confirm')
    def confirm(source:str,payload:Decision,http:Request):
        actor=http.state.principal['principal_id'];anchor=None
        prior=lifecycle.legacy('status',source,actor=actor,operation=str(payload.operation))
        if prior:
            anchor=prior['proof']['anchor']
        elif payload.decision=='OBSERVE':
            proof=evidence.preview(payload.evidence_token)
            if (proof['source'],proof['revision'],proof['actor'])!=(source,payload.revision,actor):
                raise LifecycleRequestError('SOURCE_LIFECYCLE_CONFLICT')
            anchor=proof['anchor']
        result=lifecycle.legacy('confirm',source,actor=actor,operation=str(payload.operation),
            revision=payload.revision,decision=payload.decision,reason=payload.reason,anchor=anchor)
        return result
    return router
