"""Fixed contract, fencing, reconciliation and ephemeral token lifecycle."""
import json
import os
import pytest
from netbox_sync.prerequisites import FIELDS, definition, reconcile
from netbox_sync.netbox_auth import authorization, token_key
from netbox_sync.bootstrap_setup import Preparation
from netbox_sync.bootstrap_state import BootstrapStore
from netbox_sync.local_control import ControlError
from tests.test_first_run import PAYLOAD, success


def row(name, index=1, **changes):return {**definition(name), 'id':index, 'status':{'value':'active'}, **changes}


def test_contract_all_models_and_status_constraints():
    assert len(FIELDS)==16
    rows=[row(name,i+1) for i,name in enumerate(FIELDS)]
    assert all(f['status']=='ready' for f in reconcile(rows))
    assert all(f['status']=='missing' for f in reconcile([]))
    for changes, expected in [({'type':'integer'},'conflict'),({'status':'provisioning'},'provisioning'),
                              ({'status':'deleting'},'conflict'),({'required':True},'conflict'),
                              ({'unique':True},'conflict'),({'validation_maximum':0},'conflict')]:
        fields=reconcile([row('sync_identities',**changes)])
        assert fields[0]['status']==expected
    assert definition('guest_os_type')['group_name']=='NetBox Sync'
    assert 'memory_mb' not in {n for n,(_,models) in FIELDS.items() if 'virtualization.virtualmachine' in models}


def test_token_versions_use_syntax_not_length():
    assert authorization('some-long-v1-credential')=='Token some-long-v1-credential'
    assert token_key('nbt_ABCDEFGHIJKL.short')=='ABCDEFGHIJKL'
    assert authorization('nbt_ABCDEFGHIJKL.short')=='Bearer nbt_ABCDEFGHIJKL.short'
    with pytest.raises(ValueError):authorization('nbt_invalid')


class NetBox:
    def __init__(self):self.rows=[];self.calls=[];self.fail=None;self.revoke='CONFIRMED'
    def __call__(self, value):
        self.calls.append(dict(value))
        if value['action']=='inspect':return {'fields':reconcile(self.rows)}
        if value['action']=='identify':return {'token_id':91}
        if value['action']=='revoke':return {'code':self.revoke}
        if value['action']=='create':
            if self.fail==value['name']:return {'code':'UNCERTAIN'}
            self.rows.append(row(value['name'],len(self.rows)+1));return {'code':'CREATED'}
        raise AssertionError(value['action'])


@pytest.fixture(params=["journal-unit", "protected-linux"])
def setup(tmp_path, request, monkeypatch):
    if request.param == "journal-unit":
        from contextlib import nullcontext
        # Exercise orchestration cross-platform; protected-linux retains real locks/fsync/modes.
        monkeypatch.setattr(BootstrapStore, "locked", lambda self: nullcontext())
        monkeypatch.setattr(BootstrapStore, "write", lambda self, value: (self.path.write_text(json.dumps(value)), self.path.chmod(0o600)))
    elif getattr(os,'geteuid',lambda:-1)()!=0:pytest.skip('Linux root protected state')
    root=tmp_path/'state';root.mkdir(mode=0o700)
    store=BootstrapStore(root);store.configure(PAYLOAD)
    remote=NetBox();return store,remote,Preparation(store,remote)


def confirm(store, control):
    state=control.plan(1)
    return {'revision':1,'digest':state['preparation']['digest'],'confirm':True,'setup_token':'nbt_ABCDEFGHIJKL.SECRETSETUPONLY'}


def test_fresh_create_finish_and_confirmed_revocation(setup):
    store,remote,control=setup
    payload=confirm(store,control)
    result=control.apply(payload)
    assert result['preparation']['status']=='PREPARED'
    assert result['preparation']['revocation']=='CONFIRMED'
    assert result['preparation']['local_secret']=='NOT_STORED'
    assert len(remote.rows)==16 and len([c for c in remote.calls if c['action']=='create'])==16
    assert 'SECRETSETUPONLY' not in json.dumps(result)+store.path.read_text()
    assert 'setup_token' not in payload
    with pytest.raises(ControlError):store.finish(1)
    store.validate(1,lambda _:success());assert store.finish(1)['status']=='READY'


def test_partial_uncertain_restart_does_not_blindly_retry(setup):
    store,remote,control=setup;remote.fail='cpu_vendor'
    result=control.apply(confirm(store,control))
    assert result['preparation']['status']=='UNCERTAIN' and len(remote.rows)==4
    assert result['preparation']['revocation']=='UNCONFIRMED'
    control=Preparation(BootstrapStore(store.root),remote)
    plan=control.plan(1)
    assert plan['preparation']['uncertain']=='cpu_vendor'
    with pytest.raises(ControlError):control.apply({'revision':1,'digest':plan['preparation']['digest'],'confirm':True,'setup_token':'separate-setup-token'})
    # A later authoritative observation resolves the ambiguous POST.
    remote.rows.append(row('cpu_vendor',5));remote.fail=None
    control.apply(confirm(store,control))
    assert len(remote.rows)==16
    assert len([c for c in remote.calls if c.get('name')=='cpu_vendor'])==1


def test_conflict_stale_plan_and_same_runtime_token_refused(setup):
    store,remote,control=setup
    payload=confirm(store,control)
    with pytest.raises(ControlError):control.apply({**payload,'setup_token':PAYLOAD['read_token']})
    with pytest.raises(ControlError):control.apply({**payload,'confirm':False})
    remote.rows=[row('cpu_vendor',type='integer')]
    assert control.apply(payload)['preparation']['status']=='STALE'
    payload=confirm(store,control)
    with pytest.raises(ControlError):control.apply(payload)
    assert not any(c['action']=='create' for c in remote.calls)


def test_two_browser_and_restart_recovery(setup):
    store,remote,control=setup;payload=confirm(store,control)
    with store.locked():
        value=store.read();value['preparation'].update(status='RUNNING',started_at=0,uncertain='cpu_model');store.write(value)
    # Concurrent callers cannot acquire another execution fence.
    with pytest.raises(ControlError):control.apply(payload)
    assert BootstrapStore(store.root).status()['preparation']['status']=='UNCERTAIN'
    assert control.plan(1)['preparation']['uncertain']=='cpu_model'
    control.cancel(1)
    assert control.plan(1)['preparation']['uncertain']=='cpu_model'


def test_expired_plan_and_unconfirmed_revoke_preserve_fields(setup):
    store,remote,control=setup;payload=confirm(store,control)
    now=store.clock();store.clock=lambda:now+301
    with pytest.raises(ControlError):control.apply(payload)
    remote.revoke='UNCONFIRMED'
    result=control.apply(confirm(store,control))
    assert result['preparation']['status']=='PREPARED' and len(remote.rows)==16
    assert result['preparation']['revocation']=='UNCONFIRMED'


@pytest.fixture
def executor(monkeypatch):
    from contextlib import nullcontext
    from netbox_sync import bootstrap_setup_probe as module
    class Session:
        def __init__(self):self.calls=[];self.status=204
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            self.calls.append(('POST',url,kwargs));return Response(201)
        def delete(self,url,**kwargs):
            self.calls.append(('DELETE',url,kwargs));return Response(self.status)
    class Response:
        def __init__(self,status):self.status_code=status
        def __enter__(self):return self
        def __exit__(self,*args):pass
    session=Session();queries=[]
    token='nbt_ABCDEFGHIJKL.SETUPSECRET'
    identity={'key':'ABCDEFGHIJKL','version':2,'id':91}
    def fetch(session,url,token,method='GET'):
        queries.append((url,method))
        if method=='OPTIONS':return {'actions':{'POST':{}}}
        if '/users/tokens/?' in url:return {'count':1,'next':None,'results':[identity.copy()]}
        if '/users/tokens/' in url:return identity.copy()
        return {'results':[],'next':None}
    monkeypatch.setattr(module.EgressPolicy,'resolve',lambda *args:('netbox.test','192.0.2.10'))
    monkeypatch.setattr(module,'pinned_dns',lambda *args:nullcontext())
    monkeypatch.setattr(module.requests,'Session',lambda:session)
    monkeypatch.setattr(module,'configure_session',lambda s:None)
    monkeypatch.setattr(module,'fetch',fetch)
    return module,session,queries,identity,{'url':'https://netbox.test','token':token}


def test_executor_only_identifies_and_revokes_exact_supplied_v2(executor):
    module,session,queries,identity,value=executor
    assert module.operate({**value,'action':'identify'})=={'token_id':91}
    assert queries[-1][0].endswith('?version=2&key=ABCDEFGHIJKL&limit=2')
    assert all('SETUPSECRET' not in url for url,_ in queries)
    assert module.operate({**value,'action':'revoke','token_id':91})=={'code':'CONFIRMED'}
    assert session.calls[-1][1]=='https://netbox.test/api/users/tokens/91/'
    assert session.calls[-1][2]['headers']['Authorization'].startswith('Bearer ')
    session.calls.clear();identity['key']='OTHERKEY1234'
    assert module.operate({**value,'action':'revoke','token_id':91})=={'code':'UNCONFIRMED'}
    assert not session.calls
    assert module.operate({**value,'action':'revoke','token_id':-1})=={'code':'INVALID'}


def test_executor_v1_manual_revoke_and_fixed_create_payload(executor):
    module,session,queries,identity,value=executor
    assert module.operate({**value,'token':'legacy-setup-token','action':'identify'})=={'token_id':None}
    assert not any('/users/tokens/' in url for url,_ in queries)
    assert module.operate({**value,'action':'create','name':'arbitrary'})=={'code':'INVALID'}
    assert not session.calls
    assert module.operate({**value,'action':'create','name':'cpu_model','payload':{'required':True}})=={'code':'CREATED'}
    assert session.calls[0][2]['json']==definition('cpu_model')
    assert session.calls[0][2]['allow_redirects'] is False


def test_executor_unconfirmed_delete_does_not_claim_revocation(executor):
    module,session,queries,identity,value=executor
    session.status=403
    assert module.operate({**value,'action':'revoke','token_id':91})=={'code':'UNCONFIRMED'}
    assert len(session.calls)==1


@pytest.mark.parametrize('rejected',['AUTH_FAILED','PERMISSION_DENIED'])
def test_setup_authority_rejected_without_write_or_secret_retention(setup,rejected):
    store,remote,control=setup
    original=control.execute
    control.execute=lambda value: {'code':rejected} if value['action']=='identify' else original(value)
    result=control.apply(confirm(store,control))
    assert result['preparation']['status']=='TOKEN_REJECTED'
    assert result['preparation']['local_secret']=='NOT_STORED'
    assert not remote.rows


def test_provisioning_is_pending_and_existing_fields_are_not_recreated(setup):
    store,remote,control=setup
    remote.rows=[row(name,i+1) for i,name in enumerate(FIELDS)]
    remote.rows[0]['status']='provisioning'
    payload=confirm(store,control)
    with pytest.raises(ControlError):control.apply(payload)
    remote.rows[0]['status']='active'
    assert control.apply(confirm(store,control))['preparation']['status']=='PREPARED'
    assert not any(c['action']=='create' for c in remote.calls)


def test_setup_api_origin_and_secret_redaction(monkeypatch,caplog):
    from fastapi.testclient import TestClient
    from netbox_sync.api.app import create_app
    from netbox_sync.api.settings import ApiSettings
    from netbox_sync.api.bootstrap import BootstrapClient
    observed=[]
    def call(self,action,payload=None):
        observed.append((action,payload))
        return dict(revision=1,status='CONFIGURED',url=PAYLOAD['url'],completed=False,
            read_token_present=True,apply_token_present=True,safe_code=None,checks=[],validated_at=None)
    monkeypatch.setattr(BootstrapClient,'call',call)
    client=TestClient(create_app(ApiSettings(bootstrap_socket='/test',allowed_write_hosts=('testserver',))))
    body={'revision':1,'digest':'a'*64,'confirm':True,'setup_token':'SENTINEL-SETUP-SECRET'}
    path='/api/v1/bootstrap/prerequisites-apply'
    assert client.post(path,json=body).status_code==403 and not observed
    headers={'Origin':'http://testserver','X-NetBox-Sync-CSRF':'same-origin'}
    result=client.post(path,json=body,headers=headers)
    assert result.status_code==200
    assert 'SENTINEL' not in result.text+caplog.text
    assert observed[-1][1]['setup_token']==body['setup_token']
    result=client.post(path,json={**body,'confirm':'SENTINEL-INVALID-SECRET'},headers=headers)
    assert result.status_code==422 and 'SENTINEL' not in result.text+caplog.text
