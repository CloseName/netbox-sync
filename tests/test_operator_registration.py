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
    onboarding, _, _ = service()
    with TestClient(create_app(settings=ApiSettings(bootstrap_socket=''),auth_client=Client(),onboarding_service=onboarding),base_url='https://localhost:8000') as http:
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


@pytest.mark.parametrize('role',['operator','viewer'])
def test_recovery_and_recovery_probe_are_admin_only(monkeypatch,role):
    from uuid import uuid4
    from netbox_sync.api.lifecycle_client import LifecycleClient
    policy,_,session=configured(role)
    class Client:
        def call(self,action,**payload):return policy.call(dict(action=action,**payload))
    monkeypatch.setattr(LifecycleClient,'identity',lambda *args,**kw:pytest.fail('No identity capability for this role'))
    monkeypatch.setattr(LifecycleClient,'recovery',lambda *args,**kw:pytest.fail('No lifecycle capability for this role'))
    monkeypatch.setattr('netbox_sync.probe_worker.remote_test_authorized',lambda *args,**kw:pytest.fail('No recovery probe for this role'))
    app=create_app(settings=ApiSettings(bootstrap_socket='',probe_socket='/test-only'),auth_client=Client())
    with TestClient(app,base_url='https://localhost:8000') as http:
        http.cookies.set(COOKIE,session)
        for route,body in [
            ('identity-review',{}),
            ('identity-confirm',{'revision':'a'*64,'discovery_id':str(uuid4()),'digest':'a'*64,'confirmed':True}),
            ('recovery-review',{'onboarding_token':'x'*32}),
            ('recover',{'onboarding_token':'x'*32,'operation_id':str(uuid4()),'digest':'0'*64,'confirmed':True}),
            ('recovery-abandon',{'operation_id':str(uuid4())}),
            ('recovery-status',{'operation_id':str(uuid4())})]:
            assert http.post('/api/v1/sources/old-source/'+route,headers=HEADERS,json=body).status_code==403
        assert http.post('/api/v1/sources/test-connection',headers=HEADERS,json={
            'source_type':'esxi','address':'source.test','username':'fixture-user',
            'secret':'fixture-only','recovery_source':'old-source'}).status_code==403


@pytest.mark.parametrize('value',[1,'true',False,None])
def test_recovery_requires_explicit_boolean_confirmation(value):
    from uuid import uuid4
    from pydantic import ValidationError
    from netbox_sync.api.source_recovery import ConfirmRequest
    with pytest.raises(ValidationError):
        ConfirmRequest(onboarding_token='x'*32,operation_id=uuid4(),digest='a'*64,confirmed=value)


@pytest.mark.parametrize('role',['admin','operator','viewer'])
@pytest.mark.parametrize('mode',['same','distinct','missing','catalog_error','changed'])
def test_identity_audit_is_admin_read_only_and_never_selects_owner(monkeypatch,role,mode):
    from netbox_sync.api.lifecycle_client import LifecycleClient,LifecycleRequestError
    from netbox_sync.api.catalog import CatalogError
    import netbox_sync.api.source_recovery as recovery
    policy,_,session=configured(role)
    class Client:
        def call(self,action,**payload):return policy.call(dict(action=action,**payload))
    calls=[]
    def identity(self,action,source,**kw):
        assert action=='describe' and not kw
        calls.append(source)
        if source=='second' and mode=='missing':raise LifecycleRequestError('SOURCE_DISCOVERY_REQUIRED')
        return dict(source_instance=source,host_uuid='uuid-b' if source=='second' and mode=='distinct' else 'uuid-a',
            recorded_uuid='old-uuid' if mode=='changed' else None,site_slug='site',cluster_name='cluster',
            observed_at='2026-09-23T00:00:00Z',revision='a'*64,discovery_id='fixture')
    def catalog(path,payload):
        assert payload['action']=='identity-evidence'
        if mode=='catalog_error':raise CatalogError('remote-sensitive-error')
        return dict(blockers=[],digest='a'*64,owned=[{'kind':'device','id':7}])
    monkeypatch.setattr(LifecycleClient,'identity',identity)
    monkeypatch.setattr(recovery,'call',catalog)
    with TestClient(create_app(settings=ApiSettings(bootstrap_socket=''),auth_client=Client()),base_url='https://localhost:8000') as http:
        http.cookies.set(COOKIE,session)
        result=http.post('/api/v1/sources/identity-audit',headers=HEADERS,json={'sources':['first','second']})
        if role!='admin':
            assert result.status_code==403 and not calls
            return
        assert result.status_code==200,result.text
        data=result.json()
        assert not data['writes_performed'] and not data['automatic_remediation']
        assert data['comparison']==({'distinct':'DISTINCT_OBSERVED_UUIDS','missing':'UNPROVED'}.get(mode,'SAME_OBSERVED_UUID'))
        assert calls==['first','second']
        if mode=='changed':assert all('RECORDED_IDENTITY_CHANGED' in entry['proof']['blockers'] for entry in data['sources'])
        if mode=='catalog_error':
            assert all(entry['evidence_error']=='UNAVAILABLE' for entry in data['sources'])
            assert 'remote-sensitive-error' not in result.text
        assert http.post('/api/v1/sources/identity-audit',headers=HEADERS,json={'sources':['first','first']}).status_code==422
        assert calls==['first','second']
