"""State-machine coverage; protocol/TLS evidence belongs to LDAPS runtime tests."""
import copy
import uuid
import pytest
from netbox_sync.auth_policy import AuthPolicy, AuthError, initial_state, digest
from netbox_sync.ldap_directory import DEFAULT, DirectoryError
from netbox_sync.roles import permissions, ADMIN

class Directory:
    role = 'viewer'
    failure = None
    identity = 'stable-directory-id'
    def __init__(self): self.calls = []
    def call(self, config, secret, operation, **kwargs):
        self.calls.append(operation)
        if self.failure: raise DirectoryError(self.failure)
        return {'identity': self.identity, 'role': self.role}

class Secrets:
    def __init__(self): self.values = {'bind-ref': 'fixture-bind-only'}
    def read(self, key): return self.values[key]
    def create(self, value):
        key = 'ref-' + str(len(self.values))
        self.values[key] = value
        return key

def configured(role='viewer'):
    directory = Directory(); directory.role = role
    service = AuthPolicy(initial_state(), clock=lambda:1000, directory=directory, auth_secrets=Secrets())
    invite = service.root('invite', {})['invitation']
    local = service.call(dict(action='enroll', invitation=invite, username='admin', password='fixture-local-password'))['session']
    service.state['ldap'] = dict(revision=1, directory_id=str(uuid.uuid4()), secret_key='bind-ref', config={
        **copy.deepcopy(DEFAULT), 'enabled':True, 'host':'directory.example.test',
        'bind_dn':'cn=reader,dc=test', 'user_base':'ou=people,dc=test', 'group_base':'ou=groups,dc=test',
        'mappings':[{'dn':'cn=readers,ou=groups,dc=test','role':'viewer'}]})
    token = service.call(dict(action='login', provider='ldap', username='person', password='fixture-user-password'))['session']
    return service, local, token

def auth(service, token, permission=None):
    return service.call(dict(action='authorize', session=token, permission=permission))

@pytest.mark.parametrize('role', ['viewer','operator','admin'])
def test_exact_role_permissions_and_no_caller_role_assertion(role):
    service, local, token = configured(role)
    for permission in sorted(ADMIN):
        if permission in permissions(role):
            assert auth(service, token, permission)['role'] == role
        else:
            with pytest.raises(AuthError, match='AUTH_DENIED'): auth(service, token, permission)
    with pytest.raises(AuthError, match='AUTH_DENIED'):
        service.call(dict(action='authorize', session=token, permission='unknown', role='admin'))
    assert auth(service, local, 'identity.manage')['provider'] == 'local'
    assert digest(token) not in service.state['sessions']  # old local-only code fails closed
    assert token not in str(service.state) and 'fixture-user-password' not in str(service.state)


def test_read_cache_bound_write_revalidation_and_no_privilege_after_outage():
    service, local, token = configured('operator')
    service.directory.role = 'viewer'
    assert auth(service, token, 'source.read')['role'] == 'operator'
    with pytest.raises(AuthError, match='AUTH_DENIED'): auth(service, token, 'source.apply')
    assert auth(service, token)['role'] == 'viewer'
    service.directory.failure = 'LDAP_UNAVAILABLE'
    service.now += 30
    with pytest.raises(AuthError, match='AUTH_UNAVAILABLE'): auth(service, token, 'source.read')
    with pytest.raises(AuthError, match='AUTH_REQUIRED'): auth(service, token, 'source.read')
    assert auth(service, local, 'identity.manage')['role'] == 'admin'

@pytest.mark.parametrize('failure', ['LDAP_ACCESS_DENIED','LDAP_TLS_FAILED','LDAP_UNAVAILABLE','LDAP_BIND_FAILED'])
def test_failed_login_never_creates_session_or_leaks_secret(failure):
    service, local, token = configured()
    service.directory.failure = failure
    before = copy.deepcopy(service.state['ldap_sessions'])
    with pytest.raises(AuthError):
        service.call(dict(action='login', provider='ldap', username='unknown', password='fixture-sensitive'))
    assert service.state['ldap_sessions'] == before
    assert 'fixture-sensitive' not in str(service.state) + str(service.audit)
    assert auth(service, local)['provider'] == 'local'

@pytest.mark.parametrize('change', ['disabled','replaced_identity'])
def test_current_account_and_stable_identity_rechecked_before_write(change):
    service, _, token = configured('operator')
    if change == 'disabled': service.directory.failure = 'LDAP_ACCESS_DENIED'
    else: service.directory.identity = 'replacement-account'
    with pytest.raises(AuthError, match='AUTH_REQUIRED'): auth(service, token, 'source.plan')
    assert digest(token) not in service.state['ldap_sessions']


def test_idle_absolute_logout_and_root_recovery():
    service, _, token = configured()
    service.now += 1800
    with pytest.raises(AuthError, match='AUTH_REQUIRED'): auth(service, token)
    service, _, token = configured()
    for _ in range(31):
        service.now += 900
        auth(service, token)
    service.now = 1000 + 28800
    with pytest.raises(AuthError, match='AUTH_REQUIRED'): auth(service, token)
    service, local, token = configured()
    service.call(dict(action='logout', session=token))
    with pytest.raises(AuthError, match='AUTH_REQUIRED'): auth(service, token)
    assert auth(service, local)['provider'] == 'local'
    service, local, token = configured()
    service.root('recover', {})
    for item in (local,token):
        with pytest.raises(AuthError, match='AUTH_REQUIRED'): auth(service, item)


def test_test_save_revision_proof_and_secret_projection():
    service, local, token = configured()
    config = copy.deepcopy(service.state['ldap']['config'])
    payload = dict(session=local, expected_revision=1, config=config, bind_password='')
    with pytest.raises(AuthError, match='LDAP_INVALID'): service.call(dict(action='ldap.save', **payload))
    service.call(dict(action='ldap.test', **payload))
    altered = copy.deepcopy(payload); altered['config']['mappings'][0]['role']='operator'
    with pytest.raises(AuthError, match='LDAP_INVALID'): service.call(dict(action='ldap.save', **altered))
    result = service.call(dict(action='ldap.save', **payload))
    assert result['revision'] == 2 and result['bind_secret_present'] is True
    assert 'secret_key' not in str(result) and 'fixture-bind-only' not in str(result)
    assert service.state['ldap']['secret_key'] == 'bind-ref'
    with pytest.raises(AuthError, match='AUTH_REQUIRED'): auth(service, token)
    with pytest.raises(AuthError, match='LDAP_CONFLICT'): service.call(dict(action='ldap.save', **payload))
    assert auth(service, local)['role'] == 'admin'

@pytest.mark.parametrize('field,value', [('host','different.example.test'),('port',1636),('bind_dn','cn=other,dc=test')])
def test_existing_bind_secret_not_forwarded_to_new_authority(field,value):
    service, local, _ = configured()
    config = copy.deepcopy(service.state['ldap']['config']); config[field]=value
    before = len(service.directory.calls)
    with pytest.raises(AuthError, match='LDAP_INVALID'):
        service.call(dict(action='ldap.test',session=local,expected_revision=1,config=config,bind_password=''))
    assert len(service.directory.calls) == before


def test_disable_available_without_directory_or_bind_file():
    service, local, token = configured()
    service.directory.failure='LDAP_UNAVAILABLE'; service.auth_secrets.values.clear()
    config=copy.deepcopy(service.state['ldap']['config']); config['enabled']=False
    result=service.call(dict(action='ldap.save',session=local,expected_revision=1,config=config,bind_password=''))
    assert not result['config']['enabled']
    assert auth(service,local,'identity.manage')['role']=='admin'
    with pytest.raises(AuthError,match='AUTH_REQUIRED'): auth(service,token)


def test_test_proof_expires_and_settings_reject_nonadmin():
    service, local, token = configured()
    for action in ('ldap.settings','ldap.test','ldap.save','ldap.revoke','roles'):
        with pytest.raises(AuthError,match='AUTH_DENIED'): service.call(dict(action=action,session=token))
    payload=dict(session=local,expected_revision=1,config=copy.deepcopy(service.state['ldap']['config']),bind_password='')
    service.call(dict(action='ldap.test',**payload)); service.now += 300
    with pytest.raises(AuthError,match='LDAP_INVALID'): service.call(dict(action='ldap.save',**payload))


@pytest.mark.parametrize('role',['viewer','operator','admin'])
def test_http_endpoint_matrix_rejects_forbidden_before_handlers(role):
    import re
    from fastapi.testclient import TestClient
    from netbox_sync.api.app import create_app
    from netbox_sync.api.settings import ApiSettings
    from netbox_sync.api.auth import COOKIE, permission, PUBLIC
    service, _, token = configured(role)
    class Transport:
        def call(self, action, **payload):
            return service.call(dict(action=action,**payload))
    app=create_app(settings=ApiSettings(bootstrap_socket='/fixture/bootstrap'),auth_client=Transport())
    checked=0
    with TestClient(app,base_url='https://localhost:8000') as http:
        http.cookies.set(COOKIE,token)
        for template,methods in app.openapi()['paths'].items():
            path=re.sub(r'\{[^}]+\}','source-fixture',template)
            for method in methods:
                verb=method.upper()
                if (verb,path) in PUBLIC: continue
                required=permission(verb,path)
                assert required!='unmapped.deny',(verb,path)
                if required in permissions(role): continue
                checked+=1
                response=http.request(verb,path,json={} if verb!='GET' else None,
                    headers={'Origin':'https://localhost:8000','X-NetBox-Sync-CSRF':'same-origin'})
                assert response.status_code==403,(verb,path,response.status_code)
                assert response.json()['error']['code']=='AUTH_DENIED'
                assert 'fixture-bind-only' not in response.text
        response=http.get('/api/v1/settings/ldap')
        assert response.status_code==(200 if role=='admin' else 403)
        if role=='admin':
            assert 'secret_key' not in response.text and 'fixture-bind-only' not in response.text
    assert role=='admin' or checked>10


def test_role_revocation_after_prepare_blocks_apply_dispatch():
    from fastapi.testclient import TestClient
    from netbox_sync.api.app import create_app
    from netbox_sync.api.settings import ApiSettings
    from netbox_sync.api.auth import COOKIE
    service, _, token = configured('operator')
    class Transport:
        def call(self, action, **payload): return service.call(dict(action=action,**payload))
    class Worker:
        applied = False
        actor = None
        def prepare(self, source, digest, actor_id=None):
            self.actor=actor_id
            return {'confirmation_token':'a'*64,'expires_in_seconds':300}
        def apply(self,*args,**kwargs):
            self.applied=True
            raise AssertionError('revoked permission reached worker')
    worker=Worker()
    with TestClient(create_app(settings=ApiSettings(bootstrap_socket=''),auth_client=Transport(),apply_client=worker),base_url='https://localhost:8000') as http:
        http.cookies.set(COOKIE,token)
        headers={'Origin':'https://localhost:8000','X-NetBox-Sync-CSRF':'same-origin'}
        response=http.post('/api/v1/sources/pve-fixture/sync-confirmations',headers=headers,json={'plan_digest':'b'*64,'confirmed':True})
        assert response.status_code==200
        assert worker.actor==auth(service,token)['principal_id']
        service.directory.role='viewer'
        response=http.post('/api/v1/sources/pve-fixture/sync',headers=headers,json={'confirmation_token':'a'*64})
        assert response.status_code==403 and response.json()['error']['code']=='AUTH_DENIED'
        assert not worker.applied


def test_directory_failed_login_budget_is_separate_from_emergency_login():
    service,local,_=configured()
    for _ in range(21):
        service.call(dict(action='login',provider='ldap',username='person',password='fixture-user-password'))
    assert service.state['ldap_attempts']==[]
    service.directory.failure='LDAP_ACCESS_DENIED'
    for _ in range(20):
        with pytest.raises(AuthError,match='AUTH_INVALID'):
            service.call(dict(action='login',provider='ldap',username='person',password='incorrect'))
    with pytest.raises(AuthError,match='AUTH_RATE_LIMITED'):
        service.call(dict(action='login',provider='ldap',username='person',password='incorrect'))
    assert auth(service,local,'identity.manage')['role']=='admin'
