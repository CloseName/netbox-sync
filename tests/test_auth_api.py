"""No implicit authorization: real policy service behind the injected transport."""
import pytest
from fastapi.testclient import TestClient
from netbox_sync.api.app import create_app
from netbox_sync.api.settings import ApiSettings
from netbox_sync.api.auth import COOKIE, permission
from netbox_sync.auth_policy import AuthPolicy, AuthError, initial_state

class Client:
    def __init__(self): self.service=AuthPolicy(initial_state())
    def call(self, action, **payload): return self.service.call(dict(action=action,**payload))


def test_business_routes_reject_no_session_even_with_correct_origin():
    client=Client()
    with TestClient(create_app(settings=ApiSettings(bootstrap_socket=''),auth_client=client),base_url='https://localhost:8000') as http:
        for path in ('sources','runs','diagnostics','version','system/health','policy','auth/me','sources/source-1/operations'):
            assert http.get('/api/v1/'+path).status_code==401
        response=http.post('/api/v1/sources/test-connection',json={},headers={'Origin':'https://localhost:8000','X-NetBox-Sync-CSRF':'same-origin'})
        assert response.status_code==401
        assert http.get('/api/v1/health').json()=={'status':'healthy'}


def test_login_cookie_csrf_and_worker_outage():
    client=Client()
    token=client.service.root('invite',{})['invitation']
    headers={'Origin':'https://localhost:8000','X-NetBox-Sync-CSRF':'same-origin'}
    with TestClient(create_app(settings=ApiSettings(bootstrap_socket=''),auth_client=client),base_url='https://localhost:8000') as http:
        payload=dict(username='admin',password='test-only-local-password-9284',invitation=token)
        assert http.post('/api/v1/auth/enroll',json=payload).status_code==403
        response=http.post('/api/v1/auth/enroll',json=payload,headers=headers)
        assert response.status_code==200
        cookie=response.headers['set-cookie']
        assert all(value in cookie for value in ('__Host-','Secure','HttpOnly','SameSite=lax','Path=/'))
        assert 'Domain=' not in cookie and 'password' not in response.text
        assert http.get('/api/v1/auth/me').status_code==200
        assert http.post('/api/v1/auth/logout',json={},headers=headers).status_code==200
        assert http.get('/api/v1/auth/me').status_code==401
        def unavailable(*a,**k):raise AuthError('AUTH_UNAVAILABLE')
        client.call=unavailable
        assert http.get('/api/v1/policy').status_code==503


def test_all_declared_business_routes_have_explicit_permissions():
    app=create_app(settings=ApiSettings(bootstrap_socket='/test/bootstrap'),auth_client=Client())
    public={'/api/v1/health','/api/v1/auth/login','/api/v1/auth/enroll'}
    for template, methods in app.openapi()['paths'].items():
        if template in public:continue
        import re
        path=re.sub(r'\{[^}]+\}', 'source-1', template)
        for method in methods:
            assert permission(method.upper(),path)!='unmapped.deny',(method,path)
