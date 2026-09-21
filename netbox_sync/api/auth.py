"""Explicit server route permissions and bounded auth RPC."""
import re
from typing import Literal
from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from ..auth_policy import AuthError, CODES
from ..local_control import request, ControlError

COOKIE = '__Host-netbox-sync-session'
PUBLIC = {('GET', '/api/v1/health'), ('GET', '/api/v1/auth/status'), ('POST', '/api/v1/auth/login'), ('POST', '/api/v1/auth/enroll')}
ROUTES = (
    ('GET', r'/api/v1/users', 'identity.manage'),
    ('POST', r'/api/v1/users/(sync|role)', 'identity.manage'),
    ('GET', r'/api/v1/settings/(ldap|roles)', 'identity.manage'),
    ('POST', r'/api/v1/settings/ldap(?:/(test|revoke))?', 'identity.manage'),
    ('POST', r'/api/v1/catalog/[^/]+', 'catalog.create'),
    ('GET', r'/api/v1/catalog-operations/[^/]+', 'catalog.create'),
    ('GET', r'/api/v1/catalog/[^/]+', 'source.register'),
    ('GET', r'/api/v1/auth/me', 'source.read'),
    ('POST', r'/api/v1/auth/logout', 'source.read'),
    ('GET', r'/api/v1/teams', 'source.read'),
    ('POST', r'/api/v1/teams', 'source.configure'),
    ('GET', r'/api/v1/policy', 'policy.read'),
    ('POST', r'/api/v1/policy', 'policy.write'),
    ('GET', r'/api/v1/(system/health|version|diagnostics)', 'diagnostics.read'),
    ('GET', r'/api/v1/runs(?:/[^/]+)?', 'run.read'),
    ('GET', r'/api/v1/sources(?:/[^/]+(?:/(schedule|operations|lifecycle))?)?', 'source.read'),
    ('POST', r'/api/v1/sources/(test-connection|check-destination)', 'source.probe'),
    ('POST', r'/api/v1/sources(?:/(cancel-onboarding|review-placement|registration-status|resolve-placement))?', 'source.register'),
    ('GET', r'/api/v1/sources/[^/]+/placement', 'source.configure'),
    ('PATCH', r'/api/v1/sources/[^/]+/placement', 'source.configure'),
    ('PATCH', r'/api/v1/sources/[^/]+/name', 'source.configure'),
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
            return request(self.path, {'action': action, **payload}, timeout=25)['result']
        except ControlError as exc:
            raise AuthError(exc.code if exc.code in CODES else 'AUTH_UNAVAILABLE') from None
        except Exception:
            raise AuthError('AUTH_UNAVAILABLE') from None


class Login(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256, repr=False)
    provider: Literal['local','ldap'] | None = None


class Enrollment(Login):
    invitation: str = Field(min_length=32, max_length=128, repr=False)


class PolicyChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: Literal['allow', 'revoke'] = 'allow'
    host: str = Field(min_length=1, max_length=253)
    expected_revision: int = Field(ge=0, strict=True)
    request_id: str = Field(min_length=16, max_length=64)


class DirectoryRoleChange(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id: str=Field(min_length=36,max_length=36)
    role: Literal['viewer','operator','admin']
    revision: int=Field(ge=0,strict=True)


def routes(client, source_reader=None):
    router = APIRouter(prefix='/api/v1')

    def session_response(result):
        response = JSONResponse({'authenticated': True})
        response.set_cookie(COOKIE, result['session'], max_age=result['max_age'],
                            secure=True, httponly=True, samesite='lax', path='/')
        return response

    @router.get('/auth/status')
    def login_status():
        return client.call('login.status')

    @router.post('/auth/login')
    def login(payload: Login):
        return session_response(client.call('login', **payload.model_dump()))

    @router.post('/auth/enroll')
    def enroll(payload: Enrollment):
        return session_response(client.call('enroll', **payload.model_dump(exclude={'provider'})))

    @router.get('/auth/me')
    def me(request: Request):
        return request.state.principal

    @router.post('/auth/logout')
    def logout(request: Request):
        client.call('logout', session=request.cookies.get(COOKIE))
        response = JSONResponse({'logged_out': True})
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite='lax', path='/')
        return response

    @router.get('/teams')
    def teams(request: Request):
        return client.call('teams',session=request.cookies.get(COOKIE))

    @router.post('/teams')
    def change_teams(request: Request, payload: dict):
        if payload.get('operation') not in ('create','rename','assign') or set(payload)-{'operation','revision','team_id','name','source_instance'}:
            raise AuthError('TEAM_INVALID')
        if payload['operation']=='assign':
            if not isinstance(payload.get('source_instance'),str): raise AuthError('TEAM_INVALID')
            if source_reader is None: raise AuthError('AUTH_UNAVAILABLE')
            source_reader.get_source(payload['source_instance'])
        values={k:v for k,v in payload.items() if k!='operation'}
        return client.call('teams.'+payload['operation'],session=request.cookies.get(COOKIE),**values)

    @router.get('/policy')
    def policy(request: Request):
        return client.call('policy', session=request.cookies.get(COOKIE))

    @router.post('/policy')
    def update(request: Request, payload: PolicyChange):
        return client.call('policy.update', session=request.cookies.get(COOKIE), **payload.model_dump())

    from .ldap_dto import DirectoryChange

    @router.get('/settings/ldap')
    def ldap_settings(request: Request):
        return client.call('ldap.settings',session=request.cookies.get(COOKIE))

    @router.get('/settings/roles')
    def roles(request: Request):
        return client.call('roles',session=request.cookies.get(COOKIE))

    @router.post('/settings/ldap/test')
    def test_ldap(request: Request, payload: DirectoryChange):
        return client.call('ldap.test',session=request.cookies.get(COOKIE),**payload.model_dump())

    @router.post('/settings/ldap')
    def save_ldap(request: Request, payload: DirectoryChange):
        return client.call('ldap.save',session=request.cookies.get(COOKIE),**payload.model_dump())

    @router.post('/settings/ldap/revoke')
    def revoke_ldap(request: Request):
        return client.call('ldap.revoke',session=request.cookies.get(COOKIE))

    @router.get('/users')
    def directory_users(request: Request, q: str=Query(default='',max_length=128), offset: int=Query(default=0,ge=0,le=10000)):
        return client.call('ldap.users',session=request.cookies.get(COOKIE),q=q,offset=offset)

    @router.post('/users/sync')
    def sync_users(request: Request):
        return client.call('ldap.users.sync',session=request.cookies.get(COOKIE))

    @router.post('/users/role')
    def user_role(request: Request, payload: DirectoryRoleChange):
        return client.call('ldap.users.role',session=request.cookies.get(COOKIE),**payload.model_dump())

    return router
