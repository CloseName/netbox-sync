"""Actual AuthPolicy permission checks and explicit server role guard."""
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from netbox_sync.api.app import create_app
from netbox_sync.api.settings import ApiSettings
from netbox_sync.api.auth import COOKIE
from tests.test_directory_auth import configured

@pytest.mark.parametrize('role', ['viewer','operator','admin'])
@pytest.mark.parametrize('route', ['retirement-review','retirement-status','retire','retirement-resume'])
def test_retirement_is_admin_only(monkeypatch,role,route):
    service,_,session=configured(role)
    class Auth:
        def call(self,action,**payload):return service.call(dict(action=action,**payload))
    calls=[]
    def control(_path,payload,**options):
        calls.append(payload)
        expected={'retire':'execute','retirement-resume':'resume','retirement-review':'review','retirement-status':'status'}
        assert payload['action']=='retirement_'+expected[route]
        assert options=={'timeout':60,'response_limit':2*1024*1024}
        return {'result':{'source_instance':payload['source_instance'],'state':'READY'}}
    # Keep the real API -> LifecycleClient validation, including action allowlist.
    monkeypatch.setattr('netbox_sync.local_control.request',control)
    app=create_app(ApiSettings(bootstrap_socket=''),auth_client=Auth())
    payload={'operation_id':str(uuid4())}
    if route=='retirement-review':payload['revision']='a'*64
    if route in {'retire','retirement-resume'}:payload.update(digest='b'*64,confirmed=True,confirmed_source='fixture',remove_credentials=False)
    with TestClient(app,base_url='https://localhost:8000') as http:
        http.cookies.set(COOKIE,session)
        response=http.post('/api/v1/sources/esxi-fixture/'+route,json=payload,
            headers={'Origin':'https://localhost:8000','X-NetBox-Sync-CSRF':'same-origin'})
    assert response.status_code==(200 if role=='admin' else 403)
    assert bool(calls)==(role=='admin')
    if calls:assert calls[0]['actor_id']!='admin' # stable server principal, not label/body
