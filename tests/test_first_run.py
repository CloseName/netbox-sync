"""First-run state/secrecy and strict service separation regressions."""
import json
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from netbox_sync.bootstrap_state import BootstrapStore, runtime_netbox
from netbox_sync.local_control import ControlError
from netbox_sync.api.bootstrap import BootstrapClient
from netbox_sync.api.settings import ApiSettings
from tests.auth_support import authenticated_app as create_app

def success():
    from netbox_sync.bootstrap_probe import FIELDS
    return dict(safe_code=None, checks=[dict(name=name,type=kind,models=list(models),ok=True)
                                      for name,(kind,models) in FIELDS.items()])

ROOT=Path(__file__).parents[1]
SECRET='SENTINEL-READ-TOKEN'
PAYLOAD=dict(action='configure',revision=0,url='https://netbox.example.test',read_token=SECRET,
             apply_token='SENTINEL-APPLY-TOKEN',replace_credentials=False)


@pytest.fixture
def store(tmp_path):
    if getattr(os,'geteuid',lambda:-1)()!=0:
        pytest.skip('Protected storage requires disposable Linux root test container')
    root=tmp_path/'netbox';root.mkdir(mode=0o700)
    return BootstrapStore(root)


def test_durable_state_finish_and_credential_replacement(store):
    assert store.status()['status']=='FRESH'
    state=store.configure(PAYLOAD)
    assert state['status']=='CONFIGURED' and SECRET not in json.dumps(state)
    with pytest.raises(ControlError):store.finish(1)
    store.validate(1,lambda value:success())
    assert store.finish(1)==store.finish(1)
    reopened=BootstrapStore(store.root)
    assert reopened.status()['status']=='READY'
    assert runtime_netbox(store.path,'read')==(PAYLOAD['url'],SECRET)
    assert runtime_netbox(store.path,'apply')[1]==PAYLOAD['apply_token']
    with pytest.raises(ControlError):reopened.configure({**PAYLOAD,'revision':1})
    reopened.configure({**PAYLOAD,'revision':1,'replace_credentials':True})
    with pytest.raises(ControlError):runtime_netbox(store.path,'read')
    assert (store.path.stat().st_mode&0o777)==0o600


def test_failed_validation_restart_and_expired_validation(store):
    store.configure(PAYLOAD)
    store.validate(1,lambda _:dict(safe_code='AUTH_FAILED',checks=[]))
    assert BootstrapStore(store.root).status()['safe_code']=='AUTH_FAILED'
    store.validate(1,lambda _:success())
    store.clock=lambda:10**12
    with pytest.raises(ControlError):store.finish(1)
    store.validate(1,lambda _:success())
    assert store.finish(1)['status']=='READY'


def test_revision_fencing_and_interrupted_recovery(store):
    store.configure(PAYLOAD)
    with pytest.raises(ControlError):store.configure(PAYLOAD)
    with store.locked():
        value=store.read();value.update(status='VALIDATING',validation_started=0);store.write(value)
    assert BootstrapStore(store.root).status()['safe_code']=='VALIDATION_INTERRUPTED'
    calls=[]
    store.validate(1,lambda _:calls.append(1) or success())
    store.validate(1,lambda _:calls.append(1))
    assert calls==[1]


def test_invalid_configuration_does_not_persist(store):
    for patch in ({'url':'http://netbox.test'},{'url':'https://user:secret@netbox.test'},
                  {'apply_token':SECRET},{'read_token':'secret\nvalue'},{'revision':True}):
        with pytest.raises(ControlError):store.configure({**PAYLOAD,**patch})
    assert store.status()['status']=='FRESH'


def test_bootstrap_write_origin_and_secrecy(monkeypatch,caplog):
    observed=[]
    def call(self,action,payload=None):
        observed.append((action,payload))
        return dict(revision=1,status='CONFIGURED',url=PAYLOAD['url'],completed=False,
                    read_token_present=True,apply_token_present=True,safe_code=None,checks=[],validated_at=None)
    monkeypatch.setattr(BootstrapClient,'call',call)
    client=TestClient(create_app(ApiSettings(bootstrap_socket='/test',allowed_write_hosts=('testserver',))))
    body={key:value for key,value in PAYLOAD.items() if key!='action'}
    assert client.post('/api/v1/bootstrap/configuration',json=body).status_code==403
    response=client.post('/api/v1/bootstrap/configuration',json=body,headers={'Origin':'http://testserver','X-NetBox-Sync-CSRF':'same-origin'})
    assert response.status_code==200 and SECRET not in response.text
    assert SECRET not in client.get('/api/v1/bootstrap').text and SECRET not in caplog.text
    assert observed[0][1]['read_token']==SECRET


def test_networkless_broker_and_separate_worker_mounts():
    text=(ROOT/'compose.production.yml').read_text()
    broker=text.split('  netbox-sync-secret-broker:',1)[1].split('  netbox-sync-lifecycle-worker:',1)[0]
    lifecycle=text.split('  netbox-sync-lifecycle-worker:',1)[1].split('  netbox-sync-bootstrap-worker:',1)[0]
    assert 'network_mode: none' in broker
    for forbidden in ('networks:', 'env_file:', 'APPLY_LOCK_DIR'):
        assert forbidden not in broker
    assert 'networks: [netbox-sync-db]' in lifecycle
    for forbidden in ('SOURCE_SECRET_DIR','NETBOX_SECRET_DIR','docker.sock','systemctl','netbox-sync-egress'):
        assert forbidden not in lifecycle
    code=(ROOT/'netbox_sync/secret_broker.py').read_text()
    assert 'source_lifecycle' not in code and 'LifecycleStore' not in code


def test_two_configurators_cannot_replace_each_other(store):
    from concurrent.futures import ThreadPoolExecutor
    def configure(_):
        try:return store.configure(PAYLOAD)['revision']
        except ControlError:return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(configure,range(2)))
    assert results.count(1)==1
    assert store.status()['revision']==1


def test_lost_validation_callback_cannot_publish_after_recovery(store):
    store.configure(PAYLOAD)
    def callback(_):
        store.clock=lambda:10**12
        assert store.status()['status']=='ATTENTION'
        return success()
    assert store.validate(1,callback)['status']=='ATTENTION'


def test_read_only_probe_returns_only_expected_field_names():
    from netbox_sync.bootstrap_probe import probe,FIELDS,ENDPOINTS
    class Policy:
        def resolve(self,host,port):return host,'10.0.0.8'
    class Response:
        status_code=200
        def __init__(self,value):self.value=value
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def iter_content(self,_):yield json.dumps(self.value).encode()
    calls=[]
    class Session:
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def request(self,method,url,headers,**kwargs):
            calls.append(method)
            assert kwargs['allow_redirects'] is False
            if method=='OPTIONS':return Response({'actions':{} if headers['Authorization'].endswith(SECRET) else {'POST':{}}})
            if '/custom-fields/' in url:return Response({'next':None,'results':[dict(name=name,type=kind,object_types=list(models)) for name,(kind,models) in FIELDS.items()]})
            return Response({'count':0,'results':[]})
    result=probe(PAYLOAD,Session,Policy())
    assert result['safe_code'] is None and len(result['checks'])==len(FIELDS)
    assert set(calls)=={'GET','OPTIONS'} and SECRET not in json.dumps(result)


def test_old_attempt_cannot_finish_new_attempt_at_same_revision(store):
    store.configure(PAYLOAD)
    def old_probe(_):
        store.clock=lambda:10**12
        store.status()
        with store.locked():
            value=store.read()
            value.update(status='VALIDATING',validation_id='new-attempt',validation_started=10**12)
            store.write(value)
        return success()
    assert store.validate(1,old_probe)['status']=='VALIDATING'
    assert store.read()['validation_id']=='new-attempt'


@pytest.mark.parametrize('result',[{},None,{'safe_code':None,'checks':[]}, {'safe_code':None,'checks':[{'name':SECRET}]}])
def test_malformed_probe_cannot_mark_ready_or_leak(store,result):
    store.configure(PAYLOAD)
    state=store.validate(1,lambda _:result)
    assert state['status']=='ATTENTION'
    assert SECRET not in json.dumps(state)
    with pytest.raises(ControlError):store.finish(1)


def test_ready_revalidation_and_fixed_target(store):
    store.configure(PAYLOAD);store.validate(1,lambda _:success());store.finish(1)
    with pytest.raises(ControlError):store.configure({**PAYLOAD,'revision':1,'replace_credentials':True,'url':'https://other.example.test'})
    assert store.validate(1,lambda _:dict(safe_code='NETWORK_UNREACHABLE',checks=[]))['status']=='ATTENTION'
    with pytest.raises(ControlError):runtime_netbox(store.path,'apply')


def test_api_blocks_source_writes_before_ready(monkeypatch):
    from netbox_sync.api.bootstrap import State
    monkeypatch.setattr(BootstrapClient,'call',lambda *args:State(revision=0,status='FRESH',url='',completed=False,
        read_token_present=False,apply_token_present=False,safe_code=None,checks=[],validated_at=None))
    client=TestClient(create_app(ApiSettings(bootstrap_socket='/test',allowed_write_hosts=('testserver',))))
    response=client.post('/api/v1/sources',json={},headers={'Origin':'http://testserver','X-NetBox-Sync-CSRF':'same-origin'})
    assert response.status_code==409 and 'BOOTSTRAP_NOT_READY' in response.text


@pytest.mark.parametrize('failure,expected',[(401,'AUTH_FAILED'),(403,'PERMISSION_DENIED'),(302,'RESPONSE_INVALID'),
    ('tls','TLS_FAILED'),('network','NETWORK_UNREACHABLE'),('html','RESPONSE_INVALID')])
def test_probe_failure_classes_are_closed(failure,expected):
    import requests
    from netbox_sync.bootstrap_probe import probe
    class Policy:
        def resolve(self,*_):return 'netbox.example.test','10.0.0.8'
    class Response:
        status_code=failure if isinstance(failure,int) else 200
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def iter_content(self,_):yield ('<html>'+SECRET+'</html>').encode()
    class Session:
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def request(self,*args,**kwargs):
            if failure=='tls':raise requests.exceptions.SSLError(SECRET)
            if failure=='network':raise requests.exceptions.ConnectionError(SECRET)
            return Response()
    result=probe(PAYLOAD,Session,Policy())
    assert result['safe_code']==expected and result['checks']==[]
    assert {c['name'] for c in result['access_checks']}=={'network','tls','read_auth','apply_auth','permissions','prerequisites'}
    assert next(c['status'] for c in result['access_checks'] if c['name']=='apply_auth')=='not_run'
    assert SECRET not in json.dumps(result)


def test_bootstrap_public_destination_still_denies_metadata():
    from netbox_sync.bootstrap_probe import probe
    result=probe({**PAYLOAD,'url':'https://169.254.169.254'})
    assert result['safe_code']=='DESTINATION_DENIED'
