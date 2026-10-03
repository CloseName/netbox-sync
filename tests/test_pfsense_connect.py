import base64
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace as N
import pytest
from netbox_sync import pfsense_connect as m
from netbox_sync import netbox_catalog as catalog
from netbox_sync.pfsense_control import public
from netbox_sync.api.auth import permission


def test_csrf_and_only_output_marker_is_accepted():
    assert m.Page('<input value="abc&amp;def" name="__csrf_magic">').token=='abc&def'
    assert m.Page("var csrfMagicToken = 'token123';").token=='token123'
    payload=base64.b64encode(json.dumps({'installed':True}).encode()).decode()
    assert m.Page('<pre>NS_RESULT:'+payload+'</pre>').result()=={'installed':True}
    with pytest.raises(m.SetupError):m.Page('<textarea>NS_RESULT:'+payload+'</textarea>').result()
    with pytest.raises(m.SetupError):m.Page('<pre>NS_RESULT:'+payload+' NS_RESULT:'+payload+'</pre>').result()


def test_private_material_never_in_status():
    assert public(dict(status='CONNECTED',key='SECRET',public_key='PUBLIC',owner='OWNER',password='PASSWORD',host_key='HOST'))=={'status':'CONNECTED'}


def test_explicit_route_permissions():
    assert permission('GET','/api/v1/pfsense')=='source.read'
    assert permission('POST','/api/v1/pfsense/2609/connect')=='source.register'
    assert permission('POST','/api/v1/pfsense/2609/collect')=='source.apply'
    assert permission('DELETE','/api/v1/pfsense/2609/connect')=='unmapped.deny'


def prepare(monkeypatch,probe):
    session=N(headers={})
    monkeypatch.setattr(m.requests,'Session',lambda:nullcontext(session))
    monkeypatch.setattr(m,'configure_session',lambda *a:None)
    monkeypatch.setattr(m,'pinned_dns',lambda *a:nullcontext())
    monkeypatch.setattr(m,'EgressPolicy',lambda **kw:N(resolve=lambda h,p:(h,'10.24.0.1')))
    monkeypatch.setattr(m,'gui_request',lambda *a:'<input name="__csrf_magic" value="token">')
    monkeypatch.setattr(m,'ASSETS',Path(__file__).parents[1]/'deploy/pfsense')
    calls=[]
    def php(session,base,code):
        calls.append(code)
        return probe if len(calls)==1 else {'installed':True}
    monkeypatch.setattr(m,'php',php)
    value=dict(state=dict(address='fw.test',port=443,verify_tls=True,username='nb-sync-2609',owner='owned',public_key='ssh-ed25519 KEY'),
               data=dict(username='admin',password='SECRET'),policy={})
    return value,calls


@pytest.mark.parametrize('change,expected',[
    ({'version':'2.8.1-RELEASE'},'UNSUPPORTED_VERSION'),
    ({'ssh_enabled':False},'SSH_DISABLED'),
    ({'ifconfig':'ether 00:11:22:33:44:55'},'VM_IDENTITY_MISMATCH'),
])
def test_preflight_refuses_before_mutation(monkeypatch,change,expected):
    probe=dict(version='2.7.2-RELEASE',ssh_enabled=True,ifconfig='ether bc:24:11:90:8c:32',ssh_port=2233,host_key='ssh-ed25519 KEY')
    probe.update(change);value,calls=prepare(monkeypatch,probe)
    with pytest.raises(m.SetupError,match=expected):m.setup(value,[{'mac':'BC:24:11:90:8C:32'}])
    assert len(calls)==1


def test_provision_uses_bundled_assets_and_no_admin_password(monkeypatch):
    probe=dict(version='2.7.2-RELEASE',ssh_enabled=True,ifconfig='ether bc:24:11:90:8c:32',ssh_port=2233,host_key='ssh-ed25519 KEY')
    value,calls=prepare(monkeypatch,probe)
    assert m.setup(value,[{'mac':'BC:24:11:90:8C:32'}])==probe
    assert len(calls)==2 and 'SECRET' not in calls[1]
    assert 'restrict,command=' in calls[1] and 'USER_CONFLICT' in calls[1]


def test_changed_host_key_refused_before_provision(monkeypatch):
    probe=dict(version='2.7.2-RELEASE',ssh_enabled=True,ifconfig='ether bc:24:11:90:8c:32',ssh_port=2233,host_key='ssh-ed25519 NEW')
    value,calls=prepare(monkeypatch,probe);value['state']['host_key']='ssh-ed25519 OLD'
    with pytest.raises(m.SetupError,match='SSH_HOST_KEY_CHANGED'):m.setup(value,[{'mac':'bc:24:11:90:8c:32'}])
    assert len(calls)==1


def test_catalog_case_insensitive_candidates_and_fixed_links(monkeypatch):
    monkeypatch.setattr(catalog,'EgressPolicy',lambda **kw:N(resolve=lambda h,p:(h,'10.0.0.1')))
    monkeypatch.setattr(catalog,'pinned_dns',lambda *a:nullcontext())
    monkeypatch.setattr(catalog,'configure_session',lambda *a:None)
    names=['pfSense','INFRA-pfsense','Service-pfSense','pfSense2']
    seen=[]
    def fetch(session,url,token):
        seen.append(url)
        return {'count':4,'results':[dict(id=i+1,name=n,url='https://evil.test',custom_fields={'secret':'hidden'}) for i,n in enumerate(names)]}
    monkeypatch.setattr(catalog,'fetch',fetch)
    result=catalog.query(dict(url='https://nb.test',read_token='',query={'action':'pfsense-list'}),lambda:nullcontext(N()))
    assert [r['name'] for r in result['items']]==names
    assert all(r['url'].startswith('https://nb.test/') and 'custom_fields' not in r for r in result['items'])
    assert 'name__ic=pfsense' in seen[0]
