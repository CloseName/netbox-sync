"""Catalog writes never replay an uncertain POST or store the temporary token."""
from contextlib import nullcontext
import json
import os
import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest

from netbox_sync import catalog_creation as creation
from netbox_sync.bootstrap_state import BootstrapStore
from netbox_sync.bootstrap_probe import ProbeError


def payload():
    return dict(action='catalog-create', operation_id=str(uuid4()), kind='manufacturer',
                object={'name':'Example Vendor','slug':'example-vendor'},
                write_token=secrets.token_urlsafe(24), confirm=True)


@pytest.fixture
def store(tmp_path):
    if not hasattr(os,'geteuid') or os.geteuid()!=0:
        pytest.skip('protected catalog journal requires Linux root fixture')
    tmp_path.chmod(0o700)
    store=BootstrapStore(tmp_path)
    store.write(dict(format=1,status='READY', url='https://netbox.example.test', read_token=secrets.token_urlsafe(24)))
    return store


def test_uncertain_post_survives_restart_without_replay_or_secret(store):
    calls=[];request=payload()
    service=creation.CatalogCreation(store,lambda value:(calls.append(value['action']) or dict(status='UNCERTAIN',item=None)))
    first=service.execute(request)
    assert first['status']=='UNCERTAIN'
    reopened=creation.CatalogCreation(store,lambda _:pytest.fail('No second POST'))
    assert reopened.execute(request)==first
    assert reopened.execute({**request,'operation_id':str(uuid4())})==first
    journal=(store.root/('catalog-'+request['operation_id']+'.json')).read_text()
    assert request['write_token'] not in journal and 'read_token' not in journal
    assert calls==['create']
    checks=[]
    resumed=creation.CatalogCreation(store,lambda value:(checks.append(value['action']) or dict(status='MISSING',item=None)))
    assert resumed.execute(dict(action='catalog-reconcile',operation_id=request['operation_id']))['status']=='UNCERTAIN'
    assert checks==['read']


def test_journal_binds_definition_and_will_not_accept_new_payload(store):
    request=payload();service=creation.CatalogCreation(store,lambda _:dict(status='CREATED',item={'id':1}))
    result=service.execute(request)
    assert service.execute(request)==result
    with pytest.raises(ProbeError,match='CONFLICT'):
        service.execute({**request,'object':{'name':'Different','slug':'different'}})


@pytest.mark.parametrize('kind,obj',[
 ('cluster',{'name':'Test cluster','type':1,'scope_type':'dcim.site','scope_id':2}),
 ('device_type',{'model':'Operator model','slug':'model','manufacturer':1,'u_height':2}),
 ('manufacturer',{'name':'Vendor','slug':'vendor'}),
 ('platform',{'name':'Platform','slug':'platform'}),
 ('device_role',{'name':'Hypervisor','slug':'hypervisor'}),
 ('cluster_type',{'name':'Proxmox VE','slug':'proxmox-ve'}),
])
def test_closed_catalog_schema(kind,obj):
    assert creation.definition(kind,obj)==obj
    with pytest.raises(ProbeError):creation.definition(kind,{**obj,'url':'https://foreign.invalid'})


def session_fixture(monkeypatch,status=201,existing=False):
    calls=[]
    monkeypatch.setattr(creation,'EgressPolicy',lambda **_:SimpleNamespace(resolve=lambda h,p:(h,'192.0.2.1')))
    monkeypatch.setattr(creation,'pinned_dns',lambda *a:nullcontext())
    monkeypatch.setattr(creation,'configure_session',lambda _:None)
    monkeypatch.setattr(creation,'fetch',lambda *a:dict(count=int(existing),results=[{'id':1,'name':'Example Vendor','slug':'example-vendor'}] if existing else [],next=None))
    class Session:
        def post(self,url,**kwargs):
            calls.append((url,kwargs))
            body={'id':1,'name':'Example Vendor','slug':'example-vendor'}
            return nullcontext(SimpleNamespace(status_code=status,iter_content=lambda _:iter([json.dumps(body).encode()])))
    value=dict(action='create',url='https://netbox.example.test',read_token=secrets.token_urlsafe(24),
               write_token=secrets.token_urlsafe(24),kind='manufacturer',object=payload()['object'])
    return value,lambda:nullcontext(Session()),calls


def test_explicit_post_and_no_redirects(monkeypatch):
    value,session,calls=session_fixture(monkeypatch)
    result=creation.query(value,session)
    assert result['status']=='CREATED' and result['item']['id']==1
    assert len(calls)==1 and calls[0][1]['allow_redirects'] is False
    assert value['write_token'] not in json.dumps(result)


@pytest.mark.parametrize('status,expected',[(401,'AUTH_FAILED'),(403,'PERMISSION_DENIED'),(400,'SELECTION_REQUIRED'),(409,'CONFLICT')])
def test_write_refusals_are_explicit_and_never_return_remote_text(monkeypatch,status,expected):
    value,session,calls=session_fixture(monkeypatch,status)
    assert creation.query(value,session)==dict(status='REFUSED',error=expected,item=None)
    assert len(calls)==1


def test_concurrent_existing_object_requires_review_without_post(monkeypatch):
    value,session,calls=session_fixture(monkeypatch,existing=True)
    assert creation.query(value,session)['status']=='EXISTS_REVIEW_REQUIRED'
    assert calls==[]


def test_read_permission_failure_before_post_is_not_uncertain(monkeypatch):
    value,session,calls=session_fixture(monkeypatch)
    monkeypatch.setattr(creation,'fetch',lambda *a:(_ for _ in ()).throw(ProbeError('PERMISSION_DENIED')))
    assert creation.query(value,session)==dict(status='REFUSED',error='PERMISSION_DENIED',item=None)
    assert calls==[]


def test_real_https_catalog_create_permissions_and_lost_response(tmp_path,monkeypatch):
    import shutil,ssl,subprocess
    from tests.fakes import FakeNetBox
    from tests.fakes.netbox_http import netbox_http
    from netbox_sync.netbox_tls import configure_session
    if not shutil.which('openssl'):pytest.skip('controlled TLS fixture requires openssl')
    key=tmp_path/'server.key';cert=tmp_path/'server.crt'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
        '-keyout',str(key),'-out',str(cert),'-subj','/CN=127.0.0.1',
        '-addext','subjectAltName=IP:127.0.0.1','-addext','basicConstraints=critical,CA:TRUE'],
        check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    key.chmod(0o600);cert.chmod(0o644)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
    read=secrets.token_urlsafe(24);write=secrets.token_urlsafe(24)
    def authorize(method,header):return header=='Token '+(write if method=='POST' else read)
    monkeypatch.setattr(creation,'EgressPolicy',lambda **_:SimpleNamespace(resolve=lambda h,p:(h,'127.0.0.1')))
    monkeypatch.setattr(creation,'configure_session',lambda session:configure_session(session,cert))
    behavior={}
    with netbox_http(FakeNetBox(),context,authorize,behavior) as (api,rows,writes):
        value=dict(action='create',url=api.base_url.rstrip('/').removesuffix('/api'),read_token=read,
                   write_token=read,kind='manufacturer',object={'name':'New Vendor','slug':'new-vendor'})
        assert creation.query(value)['error']=='PERMISSION_DENIED'
        assert writes==[]
        value['write_token']=write
        assert creation.query(value)['status']=='CREATED'
        assert len(writes)==1
        assert creation.query(value)['status']=='EXISTS_REVIEW_REQUIRED'
        assert len(writes)==1
        value['object']={'name':'Response lost','slug':'response-lost'};behavior['drop_next_post']=True
        assert creation.query(value)['status']=='UNCERTAIN'
        count=len(writes)
        assert creation.query({**value,'action':'read'})['status']=='EXISTS_REVIEW_REQUIRED'
        assert len(writes)==count
        rows['dcim.sites'][1]={'id':1,'name':'Existing site','slug':'existing-site'}
        definitions=[
            ('device_type',{'model':'Operator model','slug':'operator-model','manufacturer':8,'u_height':2}),
            ('platform',{'name':'Custom platform','slug':'custom-platform'}),
            ('device_role',{'name':'Hypervisor','slug':'hypervisor'}),
            ('cluster_type',{'name':'Custom type','slug':'custom-type'}),
        ]
        for kind,obj in definitions:
            result=creation.query({**value,'kind':kind,'object':obj})
            assert result['status']=='CREATED',(kind,result)
            assert len(writes)==count+1;count+=1
            assert creation.query({**value,'kind':kind,'object':obj})['status']=='EXISTS_REVIEW_REQUIRED'
            assert len(writes)==count
        cluster={'name':'Source cluster','type':result['item']['id'],'scope_type':'dcim.site','scope_id':1}
        result=creation.query({**value,'kind':'cluster','object':cluster})
        assert result['status']=='CREATED' and result['item']['scope_id']==1
        assert result['item']['type']['id']==cluster['type']
        assert len(writes)==count+1


def test_concurrent_intents_send_only_one_post(store):
    from concurrent.futures import ThreadPoolExecutor
    import threading,time
    calls=[];barrier=threading.Barrier(4)
    def child(value):
        calls.append(value['action']);time.sleep(0.05)
        return dict(status='UNCERTAIN',item=None)
    request=payload()
    def submit(_):
        barrier.wait(timeout=5)
        from netbox_sync.local_control import ControlError
        try:return creation.CatalogCreation(store,child).execute({**request,'operation_id':str(uuid4())})
        except ControlError as exc:
            assert exc.code=='BOOTSTRAP_BUSY'
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(submit,range(4)))
    assert calls==['create']
    completed=[row for row in results if row is not None]
    assert len({row['operation_id'] for row in completed})==1
    assert all(row['status']=='UNCERTAIN' for row in completed)
    # After contention ends, a fresh intent reconciles to the durable request.
    assert creation.CatalogCreation(store,lambda _:pytest.fail('No second POST')).execute({**request,'operation_id':str(uuid4())})==completed[0]


def test_failed_journal_write_prevents_remote_post(store,monkeypatch):
    def failed(*_):raise OSError('test disk failure')
    monkeypatch.setattr(BootstrapStore,'write',failed)
    with pytest.raises(OSError):
        creation.CatalogCreation(store,lambda _:pytest.fail('No POST without durable intent')).execute(payload())


def test_unsafe_journal_permissions_fail_closed(store):
    request=payload()
    creation.CatalogCreation(store,lambda _:dict(status='UNCERTAIN',item=None)).execute(request)
    (store.root/('catalog-'+request['operation_id']+'.json')).chmod(0o644)
    with pytest.raises(ProbeError,match='RESPONSE_INVALID'):
        creation.CatalogCreation(store,lambda _:pytest.fail('No POST from unsafe journal')).execute(request)


@pytest.mark.parametrize('code,expected',[('BOOTSTRAP_BUSY','BUSY'),('SOURCE_APPLY_ACTIVE','BUSY'),('CONTROL_UNAVAILABLE','UNAVAILABLE')])
def test_gateway_distinguishes_confirmed_lock_refusal_from_transport_failure(monkeypatch,code,expected):
    from netbox_sync.api import catalog
    from netbox_sync.local_control import ControlError
    def refusal(*args,**kwargs):raise ControlError(code)
    monkeypatch.setattr(catalog,'request',refusal)
    with pytest.raises(catalog.CatalogError) as caught:catalog.create_call('/fixture',{})
    assert caught.value.code==expected
