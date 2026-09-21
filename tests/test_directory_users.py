"""Individual roles, atomic snapshots and migration through the serialized policy API."""
import copy
import pytest
from netbox_sync.auth_policy import AuthPolicy, AuthError
from netbox_sync.ldap_directory import DirectoryError
from tests.test_directory_auth import configured, auth

class Snapshot:
    def __init__(self):
        self.rows=[dict(identity='stable-new',username='new-user',display_name='New User',active=True)]
        self.failure=None
    def call(self,config,secret,operation,**kwargs):
        if self.failure: raise DirectoryError(self.failure)
        if operation=='sync': return {'users':copy.deepcopy(self.rows),'complete':True}
        return copy.deepcopy(self.rows[0])

def setup():
    service,local,_=configured()
    service.state['ldap_users']={};service.directory=Snapshot()
    return service,local

def sync(service,local): return service.call(dict(action='ldap.users.sync',session=local))
def listing(service,local): return service.call(dict(action='ldap.users',session=local))
def role(service,local,value):
    rows=listing(service,local)
    return service.call(dict(action='ldap.users.role',session=local,id=rows['users'][0]['id'],role=value,revision=rows['revision']))

def test_before_first_login_role_retention_rename_removal_disable_and_outage():
    service,local=setup();sync(service,local)
    row=listing(service,local)['users'][0]
    assert row['role']=='viewer' and row['active']
    role(service,local,'operator')
    service.directory.rows[0].update(username='renamed',display_name='Renamed User')
    sync(service,local);updated=listing(service,local)['users'][0]
    assert updated['id']==row['id'] and updated['role']=='operator' and updated['username']=='renamed'
    last=listing(service,local)['sync']['success_at']
    service.directory.failure='LDAP_UNAVAILABLE';service.now+=301
    with pytest.raises(AuthError,match='LDAP_UNAVAILABLE'): sync(service,local)
    assert listing(service,local)['users']==[updated]
    assert listing(service,local)['sync']['success_at']==last
    service.directory.failure=None;service.directory.rows[0]['active']=False
    sync(service,local);assert listing(service,local)['users'][0]['access_state']=='disabled'
    service.directory.rows=[];sync(service,local)
    assert listing(service,local)['users'][0]['access_state']=='not_member'
    assert auth(service,local,'identity.manage')['role']=='admin'

@pytest.mark.parametrize('role_name',['operator','viewer'])
def test_admin_handlers_refuse_operator_and_viewer(role_name):
    service,_,token=configured(role_name)
    for action in ('ldap.users','ldap.users.sync','ldap.users.role'):
        with pytest.raises(AuthError,match='AUTH_DENIED'): service.call(dict(action=action,session=token))

@pytest.mark.parametrize('count',[1,2])
def test_legacy_migration_never_grants_group_privileges_and_keeps_local_admin(count):
    service,local,token=configured('admin')
    saved=service.state['ldap'];saved.pop('user_model');saved['config'].pop('group_dn')
    saved['config']['mappings']=[{'dn':f'cn=group{i},dc=test','role':'admin'} for i in range(count)]
    migrated=AuthPolicy(copy.deepcopy(service.state),clock=lambda:1000,directory=service.directory,auth_secrets=service.auth_secrets)
    assert auth(migrated,local,'identity.manage')['provider']=='local'
    assert migrated.state['ldap_users']=={} and migrated.state['ldap_sessions']=={}
    assert migrated.state['ldap']['config']['enabled']==(count==1)
    assert 'mappings' not in migrated.settings()['config']
    with pytest.raises(AuthError): auth(migrated,token)
    again=AuthPolicy(copy.deepcopy(migrated.state),clock=lambda:1000)
    assert again.state==migrated.state

def test_atomic_invalid_snapshot_pagination_role_cas_and_session_revocation():
    service,local=setup();sync(service,local)
    user=listing(service,local)['users'][0]
    token=service.call(dict(action='login',username='new-user',password='fixture-user'))['session']
    role(service,local,'admin')
    with pytest.raises(AuthError,match='AUTH_REQUIRED'): auth(service,token)
    with pytest.raises(AuthError,match='LDAP_CONFLICT'):
        service.call(dict(action='ldap.users.role',session=local,id=user['id'],role='viewer',revision=0))
    assert any(e['action']=='ldap.user.role_changed' for e in service.audit)
    before=copy.deepcopy(service.state['ldap_users']);service.directory.rows*=2
    with pytest.raises(AuthError):sync(service,local)
    assert before==service.state['ldap_users']
    service.directory.rows=[dict(identity=str(i),username=f'user-{i:03}',display_name='User',active=True) for i in range(61)]
    sync(service,local)
    assert len(listing(service,local)['users'])==10
    assert len(service.call(dict(action='ldap.users',session=local,offset=60))['users'])==2
    assert service.call(dict(action='ldap.users',session=local,q='user-059'))['total']==1

def test_automatic_due_sync_and_outage_do_not_disable_local_access():
    service,local=setup()
    assert service.root('ldap.sync.due',{})['synced']
    assert service.root('ldap.sync.due',{})=={'skipped':True}
    service.now+=300;service.directory.failure='LDAP_UNAVAILABLE'
    with pytest.raises(AuthError):service.root('ldap.sync.due',{})
    assert listing(service,local)['users'][0]['active']
    assert auth(service,local,'identity.manage')['provider']=='local'


def test_user_page_fits_bounded_unix_transport_with_long_unicode_names():
    import json
    service,local=setup()
    service.directory.rows=[dict(identity=str(i),username='Ж'*128,display_name='Ж'*256,active=True) for i in range(30)]
    sync(service,local)
    page=listing(service,local)
    assert len(page['users'])==10 and page['total']==30
    assert len(json.dumps({'ok':True,'result':page}).encode())+1<32768
