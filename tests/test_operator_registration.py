"""Real API middleware and auth state machine; only external side effects are faked."""
import pytest
from fastapi.testclient import TestClient
from netbox_sync.api.app import create_app
from netbox_sync.api.auth import COOKIE
from netbox_sync.api.settings import ApiSettings
from netbox_sync.auth_policy import AuthError
from tests.test_directory_auth import configured
from tests.test_onboarding import service

HEADERS = {'Origin': 'https://localhost:8000', 'X-NetBox-Sync-CSRF': 'same-origin'}

@pytest.mark.parametrize('role', ['operator', 'admin'])
@pytest.mark.parametrize('provider', ['esxi', 'proxmox'])
def test_real_authorization_probe_receipt_and_registration(role, provider):
    policy, _, session = configured(role)
    class Client:
        def call(self, action, **payload):
            return policy.call(dict(action=action, **payload))
    onboarding, registry, secrets = service()
    app = create_app(settings=ApiSettings(bootstrap_socket='', probe_socket=''),
                     auth_client=Client(), onboarding_service=onboarding)
    with TestClient(app, base_url='https://localhost:8000') as http:
        http.cookies.set(COOKIE, session)
        checked = http.post('/api/v1/sources/test-connection', headers=HEADERS, json={
            'source_type': provider, 'address': 'source.test', 'username': 'fixture-user',
            'secret': 'fixture-only-password', **({'token_id':'fixture-token'} if provider=='proxmox' else {})})
        assert checked.status_code == 200, checked.text
        body = dict(onboarding_token=checked.json()['onboarding_token'], source_type=provider,
            source_instance='new-source', name='New source', address='source.test', verify_ssl=True,
            sync_interval_seconds=600, site_slug='test', cluster_name='Test', platform_slug='platform',
            device_role_slug='host', device_type_slug='server', cluster_type_slug='cluster', confirm_sync_disabled=True)
        response = http.post('/api/v1/sources', headers=HEADERS, json=body)
        assert response.status_code == 201, response.text
        assert not registry.records['new-source'].sync_enabled
        assert 'fixture-only-password' not in response.text
        assert http.post('/api/v1/sources', headers=HEADERS, json=body).status_code != 201
        assert len(registry.records)==1

@pytest.mark.parametrize('role', ['viewer','operator'])
def test_direct_admin_routes_remain_forbidden(role):
    policy, _, session = configured(role)
    class Client:
        def call(self, action, **payload): return policy.call(dict(action=action,**payload))
    with TestClient(create_app(settings=ApiSettings(bootstrap_socket=''),auth_client=Client()),base_url='https://localhost:8000') as http:
        http.cookies.set(COOKIE,session)
        for method,path in [('POST','catalog/cluster'),('POST','catalog/platform'),('POST','teams'),
            ('POST','policy'),('POST','sources/source-1/remove'),('PATCH','sources/source-1/name'),
            ('PATCH','sources/source-1/placement'),('GET','settings/ldap')]:
            response=http.request(method,'/api/v1/'+path,headers=HEADERS,**({'json':{}} if method!='GET' else {}))
            assert response.status_code==403,(method,path,response.status_code)
        if role=='viewer':
            for path in ('sources/test-connection','sources/check-destination','sources','sources/review-placement'):
                assert http.post('/api/v1/'+path,headers=HEADERS,json={}).status_code==403
        else:
            assert policy.call(dict(action='probe.policy',session=session))=={'revision':0}
            with pytest.raises(AuthError,match='AUTH_DENIED'):
                policy.call(dict(action='policy',session=session))

@pytest.mark.parametrize('role', ['operator','admin'])
@pytest.mark.parametrize('outcome', ['CREATED','UNCERTAIN','EXISTS_REVIEW_REQUIRED','transport','registry_failure','REFUSED'])
def test_cluster_is_created_only_at_final_registration_after_server_checks(monkeypatch, role, outcome):
    from uuid import uuid4
    from tests.test_netbox_catalog import row
    import netbox_sync.api.catalog as catalog
    from tests.test_onboarding import credentials
    policy, _, session=configured(role)
    class Client:
        def call(self, action, **payload): return policy.call(dict(action=action,**payload))
    onboarding, registry, secrets=service()
    token=onboarding.accept_checked_credentials(credentials('esxi'),{'hosts':[{'id':'host-a'}]})
    policy.call(dict(action='receipt.issue',session=session,receipt=token,provider='esxi',destination='source.test',revision=0))
    refs={kind:row(kind) for kind in ('site','platform','device_role','cluster_type')}
    if outcome=='registry_failure': registry.failure='before'
    writes=[]
    def read(_path, query):
        return {'selections':[dict(kind=choice['kind'],**row(choice['kind'])) for choice in query['selections']]}
    def create(_path, payload):
        assert set(payload)=={'action','operation_id','name','site_id','cluster_type_id'}
        assert payload['action']=='registration-cluster' and payload['name']=='Example'
        writes.append(payload)
        if outcome=='transport': raise catalog.CatalogError('UNAVAILABLE')
        return dict(status='CREATED' if outcome=='registry_failure' else outcome,operation_id=payload['operation_id'],item=row('cluster'),error='PERMISSION_DENIED')
    monkeypatch.setattr(catalog,'call',read);monkeypatch.setattr(catalog,'create_call',create)
    body=dict(onboarding_token=token,source_type='esxi',source_instance='new-source',name='Example',address='source.test',
        verify_ssl=True,sync_interval_seconds=600,site_slug='example',cluster_name='Example',platform_slug='example',
        device_role_slug='example',device_type_slug='example',cluster_type_slug='example',references=refs,
        host_types={'host-a':row('device_type')},confirm_sync_disabled=True,create_cluster=True,registration_id=str(uuid4()))
    app=create_app(settings=ApiSettings(bootstrap_socket=''),auth_client=Client(),onboarding_service=onboarding)
    with TestClient(app,base_url='https://localhost:8000') as http:
        http.cookies.set(COOKIE,session)
        review={key:body[key] for key in ('onboarding_token','references','host_types','create_cluster')}
        assert http.post('/api/v1/sources/review-placement',headers=HEADERS,json=review).status_code==200
        assert not writes and not registry.records
        # A forged destination never reaches the worker, even with a valid actor receipt.
        assert http.post('/api/v1/sources',headers=HEADERS,json={**body,'address':'other.test'}).status_code==409
        assert not writes and not registry.records
        assert http.post('/api/v1/sources',headers=HEADERS,json={**body,'cluster_name':'Different'}).status_code==422
        response=http.post('/api/v1/sources',headers=HEADERS,json=body)
        assert len(writes)==1
        if outcome=='CREATED':
            assert response.status_code==201,response.text
            assert not registry.records['new-source'].sync_enabled
            assert http.post('/api/v1/sources',headers=HEADERS,json=body).status_code!=201
            assert len(writes)==1
        else:
            assert response.status_code in (409,503),response.text
            assert not registry.records and not secrets.values
            if outcome=='REFUSED':
                assert response.json()['error']['code']=='CATALOG_PERMISSION_DENIED'
            if outcome=='registry_failure':
                assert response.json()['error']['code']=='REGISTRATION_CLUSTER_RETAINED'
            if outcome in ('UNCERTAIN','transport'):
                assert response.json()['error']['code']=='REGISTRATION_UNCERTAIN'

@pytest.mark.parametrize('role', ['operator','admin','viewer'])
def test_registration_reconciliation_is_actor_bound_and_read_only(monkeypatch,role):
    from uuid import uuid4,uuid5,UUID
    import netbox_sync.api.catalog as catalog
    policy,_,session=configured(role)
    class Client:
        def call(self,action,**payload):return policy.call(dict(action=action,**payload))
    calls=[]
    def read(path,payload):
        calls.append(payload)
        return {'status':'CREATED','item':{'unexpected':'must not escape'}}
    monkeypatch.setattr(catalog,'create_call',read)
    body={'source_instance':'new-source','registration_id':str(uuid4())}
    with TestClient(create_app(settings=ApiSettings(bootstrap_socket=''),auth_client=Client()),base_url='https://localhost:8000') as http:
        http.cookies.set(COOKIE,session)
        response=http.post('/api/v1/sources/registration-status',headers=HEADERS,json=body)
        if role=='viewer':
            assert response.status_code==403 and not calls
            return
        assert response.status_code==200 and response.json()=={'status':'CREATED'}
        principal=policy.call(dict(action='authorize',session=session))['principal_id']
        expected=str(uuid5(UUID('b6c311eb-0d55-45af-80a5-b949a20bfe47'),principal+':new-source:'+body['registration_id']))
        assert calls==[{'action':'catalog-reconcile','operation_id':expected}]
        assert http.post('/api/v1/sources/registration-status',headers=HEADERS,json={**body,'operation_id':str(uuid4())}).status_code==422
        assert len(calls)==1

@pytest.mark.parametrize('role',['operator','admin','viewer'])
def test_resolution_uses_server_preview_and_permission(monkeypatch,role):
    from tests.test_onboarding import credentials
    import netbox_sync.api.catalog as catalog
    policy,_,session=configured(role)
    class Client:
        def call(self,action,**payload):return policy.call(dict(action=action,**payload))
    onboarding,_,_=service()
    preview={'provider':'esxi','hosts':[{'id':'server-proof','manufacturer':'Vendor','model':'Generic'}]}
    token=onboarding.accept_checked_credentials(credentials('esxi'),preview)
    policy.call(dict(action='receipt.issue',session=session,receipt=token,provider='esxi',destination='source.test',revision=0)) if role!='viewer' else None
    seen=[]
    def read(path,payload):
        seen.append(payload)
        return {'references':{},'host_types':{},'issues':[{'kind':'site','code':'MISSING'}],'sites':[],'create_cluster':False}
    monkeypatch.setattr(catalog,'call',read)
    with TestClient(create_app(settings=ApiSettings(bootstrap_socket='',default_site_slug='configured'),auth_client=Client(),onboarding_service=onboarding),base_url='https://localhost:8000') as http:
        http.cookies.set(COOKIE,session)
        body={'onboarding_token':token,'name':'Reviewed name'}
        result=http.post('/api/v1/sources/resolve-placement',headers=HEADERS,json=body)
        if role=='viewer':
            assert result.status_code==403 and not seen
        else:
            assert result.status_code==200
            assert seen[0]['hosts']==preview['hosts'] and seen[0]['default_site_slug']=='configured'
            assert http.post('/api/v1/sources/resolve-placement',headers=HEADERS,json={**body,'hosts':[{'id':'forged'}]}).status_code==422
            assert len(seen)==1
