"""Explicit server route permissions and bounded auth RPC."""
import re
from typing import Literal
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from ..auth_policy import AuthError, CODES
from ..local_control import request, ControlError

COOKIE = '__Host-netbox-sync-session'
PUBLIC = {('GET', '/api/v1/health'), ('POST', '/api/v1/auth/login'), ('POST', '/api/v1/auth/enroll')}
ROUTES = (
    ('GET', r'/api/v1/auth/me', 'source.read'),
    ('POST', r'/api/v1/auth/logout', 'source.read'),
    ('GET', r'/api/v1/policy', 'policy.read'),
    ('POST', r'/api/v1/policy', 'policy.write'),
    ('GET', r'/api/v1/(system/health|version|diagnostics)', 'diagnostics.read'),
    ('GET', r'/api/v1/runs(?:/[^/]+)?', 'run.read'),
    ('GET', r'/api/v1/sources(?:/[^/]+(?:/(schedule|operations|lifecycle))?)?', 'source.read'),
    ('POST', r'/api/v1/sources/test-connection', 'source.probe'),
    ('POST', r'/api/v1/sources(?:/cancel-onboarding)?', 'source.register'),
    ('PATCH', r'/api/v1/sources/[^/]+/schedule', 'source.schedule'),
    ('POST', r'/api/v1/sources/[^/]+/(discovery|operations/discovery|operations/plan|sync-plan)', 'source.plan'),
    ('POST', r'/api/v1/sources/[^/]+/(sync|sync-confirmations)', 'source.apply'),
    ('POST', r'/api/v1/sources/[^/]+/remove', 'source.remove'),
    ('GET', r'/api/v1/bootstrap(?:/.*)?', 'bootstrap.manage'),
    ('POST', r'/api/v1/bootstrap(?:/.*)?', 'bootstrap.manage'),
)


def permission(method, path):
    for verb, pattern, value in ROUTES:
        if method == verb and re.fullmatch(pattern, path):
            return value
    return 'unmapped.deny'


class AuthClient:
    def __init__(self, path):
        self.path = path

    def call(self, action, **payload):
        try:
            return request(self.path, {'action': action, **payload})['result']
        except ControlError as exc:
            raise AuthError(exc.code if exc.code in CODES else 'AUTH_UNAVAILABLE') from None
        except Exception:
            raise AuthError('AUTH_UNAVAILABLE') from None


class Login(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256, repr=False)


class Enrollment(Login):
    invitation: str = Field(min_length=32, max_length=128, repr=False)


class PolicyChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: Literal['allow', 'revoke'] = 'allow'
    host: str = Field(min_length=1, max_length=253)
    expected_revision: int = Field(ge=0, strict=True)
    request_id: str = Field(min_length=16, max_length=64)


def routes(client):
    router = APIRouter(prefix='/api/v1')

    def session_response(result):
        response = JSONResponse({'authenticated': True})
        response.set_cookie(COOKIE, result['session'], max_age=result['max_age'],
                            secure=True, httponly=True, samesite='lax', path='/')
        return response

    @router.post('/auth/login')
    def login(payload: Login):
        return session_response(client.call('login', **payload.model_dump()))

    @router.post('/auth/enroll')
    def enroll(payload: Enrollment):
        return session_response(client.call('enroll', **payload.model_dump()))

    @router.get('/auth/me')
    def me(request: Request):
        return request.state.principal

    @router.post('/auth/logout')
    def logout(request: Request):
        client.call('logout', session=request.cookies.get(COOKIE))
        response = JSONResponse({'logged_out': True})
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite='lax', path='/')
        return response

    @router.get('/policy')
    def policy(request: Request):
        return client.call('policy', session=request.cookies.get(COOKIE))

    @router.post('/policy')
    def update(request: Request, payload: PolicyChange):
        return client.call('policy.update', session=request.cookies.get(COOKIE), **payload.model_dump())

    return router
