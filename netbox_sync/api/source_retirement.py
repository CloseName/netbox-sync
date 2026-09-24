"""Admin-only review, confirmation and status; no NetBox credentials in API."""
from uuid import UUID
from typing import Literal
from fastapi import APIRouter,Request
from pydantic import BaseModel,ConfigDict,Field,StrictBool,field_validator
from ..auth_policy import AuthError

class Status(BaseModel):
    model_config=ConfigDict(extra='forbid')
    operation_id:UUID

class Review(Status):
    revision:str=Field(pattern='^[a-f0-9]{64}$')

class Confirm(Status):
    digest:str=Field(pattern='^[a-f0-9]{64}$')
    confirmed:Literal[True]
    confirmed_source:str=Field(min_length=1,max_length=200)
    remove_credentials:StrictBool=True
    @field_validator('confirmed',mode='before')
    @classmethod
    def explicit(cls,value):
        if value is not True:raise ValueError('Explicit confirmation required')
        return value


def admin(http):
    # principal is supplied only by the existing authenticated server middleware.
    # Client role/body/header assertions are never consulted.
    principal=getattr(http.state,'principal',None)
    if not isinstance(principal,dict) or principal.get('role')!='admin':
        raise AuthError('AUTH_DENIED')
    actor=principal.get('principal_id')
    if not isinstance(actor,str) or not actor:raise AuthError('AUTH_DENIED')
    return actor


def routes(lifecycle):
    router=APIRouter(prefix='/api/v1/sources')
    @router.post('/{source}/retirement-context')
    def retained_context(source:str,http:Request):
        return lifecycle.retirement('context',source,actor_id=admin(http))

    @router.post('/{source}/retirement-review')
    def review(source:str,payload:Review,http:Request):
        return lifecycle.retirement('review',source,operation_id=str(payload.operation_id),
            actor_id=admin(http),revision=payload.revision)
    @router.post('/{source}/retire')
    def execute(source:str,payload:Confirm,http:Request):
        return lifecycle.retirement('execute',source,operation_id=str(payload.operation_id),
            actor_id=admin(http),digest=payload.digest,
            confirmed_source=payload.confirmed_source,remove_credentials=payload.remove_credentials)
    @router.post('/{source}/retirement-resume')
    def resume(source:str,payload:Confirm,http:Request):
        return lifecycle.retirement('resume',source,operation_id=str(payload.operation_id),
            actor_id=admin(http),digest=payload.digest,
            confirmed_source=payload.confirmed_source,remove_credentials=payload.remove_credentials)
    @router.post('/{source}/retirement-status')
    def status(source:str,payload:Status,http:Request):
        return lifecycle.retirement('status',source,operation_id=str(payload.operation_id),actor_id=admin(http))
    return router
