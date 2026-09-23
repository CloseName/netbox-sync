"""Admin-only same-source restoration using server-held probe and catalog evidence."""
from uuid import UUID,uuid4
from typing import Literal
from fastapi import APIRouter,Request
from pydantic import BaseModel,ConfigDict,Field,field_validator
from .auth import COOKIE
from .lifecycle_client import LifecycleRequestError
from .catalog import call


class ReviewRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    onboarding_token: str=Field(min_length=20,max_length=200,repr=False)


class ConfirmRequest(ReviewRequest):
    operation_id: UUID
    digest: str=Field(pattern='^[a-f0-9]{64}$')
    confirmed: Literal[True]

    @field_validator('confirmed',mode='before')
    @classmethod
    def explicit_confirmation(cls,value):
        if value is not True:
            raise ValueError('Explicit boolean confirmation required')
        return value


class AbandonRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    operation_id: UUID


def routes(settings,onboarding,auth,lifecycle,sources):
    router=APIRouter(prefix='/api/v1/sources')
    def evidence(meta):
        return call(settings.bootstrap_socket,{'action':'recovery-evidence',
            **{k:meta[k] for k in ('source_instance','host_uuid','site_id','cluster_id')}})

    @router.post('/{source}/recovery-review')
    def review(source: str,payload: ReviewRequest,http: Request):
        actor=http.state.principal['principal_id']
        auth.call('receipt.check',session=http.cookies.get(COOKIE),receipt=payload.onboarding_token)
        onboarding.recovery_review(payload.onboarding_token,source)
        meta=lifecycle.recovery('describe',source,actor_id=actor)
        proof=evidence(meta)
        identifier=meta['pending_operation'] or str(uuid4())
        value={'meta':meta,'proof':proof,'operation_id':identifier}
        onboarding.recovery_review(payload.onboarding_token,source,value)
        return {'source_instance':source,'name':meta['name'],'operation_id':identifier,
                'proof':proof,'schedule_enabled_after_restore':False}

    @router.post('/{source}/recover')
    def recover(source: str,payload: ConfirmRequest,http: Request):
        session=http.cookies.get(COOKIE);actor=http.state.principal['principal_id']
        auth.call('receipt.check',session=session,receipt=payload.onboarding_token)
        reviewed=onboarding.recovery_review(payload.onboarding_token,source)
        if (not reviewed or reviewed['operation_id']!=str(payload.operation_id)
                or reviewed['proof']['digest']!=payload.digest or reviewed['proof']['blockers']):
            raise LifecycleRequestError('SOURCE_RECOVERY_EVIDENCE_CHANGED')
        meta=reviewed['meta'];fresh=evidence(meta)
        if fresh!=reviewed['proof']:raise LifecycleRequestError('SOURCE_RECOVERY_EVIDENCE_CHANGED')
        attempt={'operation_id':str(payload.operation_id),'actor_id':actor}
        lifecycle.recovery('prepare',source,**attempt,revision=meta['revision'],proof=fresh)
        credentials=onboarding.take_recovery_credentials(payload.onboarding_token,source)
        auth.call('receipt.consume',session=session,receipt=payload.onboarding_token,
                  destination=credentials.address,provider=credentials.source_type)
        pending=lifecycle.recovery('credentials',source,**attempt)
        if pending['state']!='RESTORED':
            onboarding.create_recovery_secret(credentials,pending['plan'])
            # A failure here leaves the same durable attempt and exact broker key.
            # Neither absence nor a timeout authorizes cleanup or another key.
            current=evidence(meta)
            lifecycle.recovery('complete',source,**attempt,proof=current,metadata={
                'username':credentials.username,'address':credentials.address,
                'verify_ssl':credentials.verify_ssl,'port':credentials.port})
        return {'status':'RESTORED','source_instance':source,'source_url':'/sources/'+source}

    @router.post('/{source}/recovery-status')
    def status(source: str,payload: AbandonRequest,http: Request):
        return lifecycle.recovery('status',source,operation_id=str(payload.operation_id),
                                  actor_id=http.state.principal['principal_id'])

    @router.post('/{source}/recovery-abandon')
    def abandon(source: str,payload: AbandonRequest,http: Request):
        result=lifecycle.recovery('abandon',source,operation_id=str(payload.operation_id),
                                  actor_id=http.state.principal['principal_id'])
        return {'state':result['state'],'source_instance':source}
    return router
