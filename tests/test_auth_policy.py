"""Actual local hash/session/policy behavior, no provider or transport mock."""
import copy
import time
import pytest
from netbox_sync.auth_policy import AuthPolicy, AuthError, initial_state
from netbox_sync.api.egress import EgressPolicy

PASSWORD = 'test-only-local-password-9284'


def enrolled():
    service = AuthPolicy(initial_state(), clock=lambda:1000)
    token = service.root('invite', {})['invitation']
    session = service.call({'action':'enroll','invitation':token,'username':'admin','password':PASSWORD})['session']
    return service, session, token


def call(service, session, action, **payload):
    return service.call(dict(action=action, session=session, **payload))


def test_enrollment_double_use_hash_and_recovery():
    service, session, invite = enrolled()
    principal = call(service,session,'authorize')['principal_id']
    assert PASSWORD not in str(service.state)
    assert invite not in str(service.state)
    assert session not in str(service.state)
    assert '$argon2id$v=19$m=19456,t=2,p=1$' in service.state['principal']['password_hash']
    with pytest.raises(AuthError,match='ENROLLMENT_INVALID'):
        service.call(dict(action='enroll',invitation=invite,username='other',password=PASSWORD))
    recovery = service.root('recover', {})['invitation']
    with pytest.raises(AuthError,match='AUTH_REQUIRED'):
        call(service,session,'authorize')
    replacement = service.call(dict(action='enroll',invitation=recovery,username='new-admin',password=PASSWORD))['session']
    assert call(service,replacement,'authorize')['principal_id'] == principal


def test_login_throttling_logout_idle_and_absolute_expiry():
    service,session,_ = enrolled()
    for _ in range(5):
        with pytest.raises(AuthError,match='AUTH_INVALID'):
            service.call(dict(action='login',username='admin',password='wrong'))
    with pytest.raises(AuthError,match='AUTH_RATE_LIMITED'):
        service.call(dict(action='login',username='admin',password=PASSWORD))
    service.now += 301
    fresh=service.call(dict(action='login',username='admin',password=PASSWORD))['session']
    call(service,fresh,'logout')
    with pytest.raises(AuthError,match='AUTH_REQUIRED'):call(service,fresh,'authorize')
    service.now += 1801
    with pytest.raises(AuthError,match='AUTH_REQUIRED'):call(service,session,'authorize')


def test_policy_cas_idempotency_and_receipt_revision_owner_fences():
    service,session,_=enrolled()
    with pytest.raises(AuthError,match='POLICY_HOST_MANAGED'):
        call(service,session,'policy.update',host='source.example.test',expected_revision=0,request_id='id-1')
    service.root('managed',{'ceiling':'public-ipv4'})
    result=call(service,session,'policy.update',host='source.example.test',expected_revision=1,request_id='id-1')
    assert result['revision']==2
    assert call(service,session,'policy.update',host='source.example.test',expected_revision=1,request_id='id-1')==result
    with pytest.raises(AuthError,match='POLICY_CONFLICT'):
        call(service,session,'policy.update',host='other.example.test',expected_revision=1,request_id='id-2')
    call(service,session,'receipt.issue',receipt='opaque-receipt',destination='source.example.test',provider='esxi',revision=2)
    with pytest.raises(AuthError,match='AUTH_REQUIRED'):
        call(service,'foreign-session','receipt.consume',receipt='opaque-receipt',destination='source.example.test',provider='esxi')
    call(service,session,'policy.update',host='another.example.test',expected_revision=2,request_id='id-3')
    with pytest.raises(AuthError,match='PROBE_RECEIPT_INVALID'):
        call(service,session,'receipt.consume',receipt='opaque-receipt',destination='source.example.test',provider='esxi')


def test_env_ceiling_never_expands_without_explicit_root_selection():
    baseline=EgressPolicy(allowed_cidrs=('10.1.0.0/16',),denied_cidrs=('10.1.2.0/24',))
    service,session,_=enrolled()
    service.baseline=baseline
    assert service.effective()==baseline
    service.root('managed',{'ceiling':'existing'})
    assert service.effective()==baseline
    with pytest.raises(AuthError,match='POLICY_HOST_MANAGED'):
        call(service,session,'policy.update',host='external.example.test',expected_revision=1,request_id='id')
    service.root('managed',{'ceiling':'public-ipv4'})
    assert service.effective().denied_cidrs==baseline.denied_cidrs
    for host in ('localhost','127.0.0.1','169.254.169.254','host.docker.internal'):
        with pytest.raises(AuthError,match='POLICY_INVALID'):
            call(service,session,'policy.update',host=host,expected_revision=2,request_id=host)


def test_unknown_permission_and_expired_invitation_fail_closed():
    service,session,_=enrolled()
    with pytest.raises(AuthError,match='AUTH_DENIED'):
        call(service,session,'authorize',permission='made-up-admin')
    for action in ('invite','recover','managed','revoke'):
        with pytest.raises(AuthError,match='AUTH_DENIED'):
            call(service,session,action,role='admin',root=True)
    with pytest.raises(AuthError,match='AUTH_REQUIRED'):
        call(service,'forged-session','policy.update',role='admin')
    invitation=service.root('recover',{})['invitation']
    service.now += 901
    with pytest.raises(AuthError,match='ENROLLMENT_INVALID'):
        service.call(dict(action='enroll',invitation=invitation,username='admin',password=PASSWORD))


def test_absolute_expiry_recent_policy_login_and_root_revocation():
    service,session,_=enrolled()
    service.root('managed',{'ceiling':'public-ipv4'})
    service.now += 901
    with pytest.raises(AuthError,match='AUTH_REAUTH_REQUIRED'):
        call(service,session,'policy.update',host='source.example.test',expected_revision=1,request_id='recent')
    call(service,session,'authorize')  # Other reads retain their normal session TTL.
    for _ in range(28):
        service.now += 900
        call(service,session,'authorize')
    service.now = 1000 + 28800
    with pytest.raises(AuthError,match='AUTH_REQUIRED'):call(service,session,'authorize')
    fresh=service.call(dict(action='login',username='admin',password=PASSWORD))['session']
    service.root('revoke',{})
    with pytest.raises(AuthError,match='AUTH_REQUIRED'):call(service,fresh,'authorize')


def test_valid_foreign_identity_cannot_consume_receipt():
    service,session,_=enrolled()
    call(service,session,'receipt.issue',receipt='receipt',destination='source.example.test',provider='esxi',revision=0)
    # Stage currently has one admin. Model a future independently authenticated
    # identity to exercise the actor fence, without introducing a second role.
    service.state['principal']['id']='different-principal'
    with pytest.raises(AuthError,match='PROBE_RECEIPT_INVALID'):
        call(service,session,'receipt.consume',receipt='receipt',destination='source.example.test',provider='esxi')
    with pytest.raises(AuthError,match='PROBE_RECEIPT_INVALID'):
        call(service,session,'receipt.cancel',receipt='receipt')


def test_policy_revoke_and_capacity_cannot_make_policy_unreadable():
    service,session,_=enrolled()
    service.root('managed',{'ceiling':'public-ipv4'})
    call(service,session,'policy.update',host='source.example.test',expected_revision=1,request_id='allow')
    call(service,session,'receipt.issue',receipt='receipt',destination='source.example.test',provider='esxi',revision=2)
    call(service,session,'policy.update',operation='revoke',host='source.example.test',expected_revision=2,request_id='revoke')
    assert service.state['allowed_hosts']==[] and service.state['receipts']=={}
    service.state['allowed_hosts']=['x'*63+'.'+'y'*63+'.'+'z'*63+'.'+str(i)+'.test' for i in range(40)]
    before=copy.deepcopy(service.state)
    with pytest.raises(AuthError,match='POLICY_INVALID'):
        call(service,session,'policy.update',host='w'*63+'.'+'v'*63+'.'+'u'*63+'.'+'t'*55,expected_revision=3,request_id='overflow')
    assert service.state==before


def test_idempotency_window_never_prevents_revocation():
    service,session,_=enrolled()
    service.root('managed',{'ceiling':'public-ipv4'})
    service.state['allowed_hosts']=['source.example.test']
    service.state['changes']={str(i):{'actor':'old','revision':i,'request':{}} for i in range(4096)}
    call(service,session,'policy.update',operation='revoke',host='source.example.test',expected_revision=1,request_id='latest')
    assert not service.state['allowed_hosts'] and len(service.state['changes'])==4096
    assert '0' not in service.state['changes']
    with pytest.raises(AuthError,match='POLICY_CONFLICT'):
        call(service,session,'policy.update',operation='revoke',host='source.example.test',expected_revision=1,request_id='0')


def test_readonly_placement_receipt_check_does_not_consume_or_bypass_owner():
    service,session,_=enrolled()
    call(service,session,'receipt.issue',receipt='checked-placement',destination='source.example.test',provider='esxi',revision=0)
    for _ in range(2): assert call(service,session,'receipt.check',receipt='checked-placement')=={'valid':True}
    with pytest.raises(AuthError): call(service,'foreign','receipt.check',receipt='checked-placement')
    call(service,session,'receipt.consume',receipt='checked-placement',destination='source.example.test',provider='esxi')
    with pytest.raises(AuthError,match='PROBE_RECEIPT_INVALID'):call(service,session,'receipt.check',receipt='checked-placement')


def test_recent_confirmation_is_not_session_loss():
    service, token, _ = enrolled()
    service.root('managed', {'ceiling':'public-ipv4'})
    service.now += 901
    with pytest.raises(AuthError, match='^AUTH_REAUTH_REQUIRED$'):
        call(service, token, 'policy.update', host='source.example.test', expected_revision=1, request_id='fresh-proof')
    assert call(service, token, 'authorize')['username'] == 'admin'
    assert service.state['revision'] == 1


def test_reauthentication_confirms_only_existing_session_without_writes_or_extension():
    from netbox_sync.auth_policy import digest
    service, token, _ = enrolled()
    service.root('managed', {'ceiling':'public-ipv4'})
    original = copy.deepcopy(service.state['sessions'][digest(token)])
    service.now += 901
    for _ in range(5):
        with pytest.raises(AuthError, match='^AUTH_INVALID$'):
            call(service, token, 'reauthenticate', password='invalid-test-password')
    with pytest.raises(AuthError, match='AUTH_RATE_LIMITED'):
        call(service, token, 'reauthenticate', password=PASSWORD)
    assert 'confirmed_at' not in service.state['sessions'][digest(token)]
    service.now += 301
    assert call(service, token, 'reauthenticate', password=PASSWORD) == {'confirmed':True}
    assert service.state['revision'] == 1 and not service.state['allowed_hosts']
    saved = service.state['sessions'][digest(token)]
    assert saved['expires'] == original['expires'] and saved['issued'] == original['issued']
    assert len(service.state['sessions']) == 1
    assert call(service, token, 'policy.update', host='source.example.test', expected_revision=1, request_id='fresh-proof')['revision'] == 2
    assert PASSWORD not in str(service.audit) + str(service.state)
    service.now = original['expires']
    with pytest.raises(AuthError, match='^AUTH_REQUIRED$'):
        call(service, token, 'reauthenticate', password=PASSWORD)


def test_http_reauthentication_preserves_csrf_identity_and_policy_fences():
    from fastapi.testclient import TestClient
    from netbox_sync.api.app import create_app
    from netbox_sync.api.auth import COOKIE
    from netbox_sync.api.settings import ApiSettings
    service, token, _ = enrolled()
    service.root('managed', {'ceiling':'public-ipv4'})
    service.now += 901
    class Transport:
        def call(self, action, **payload): return service.call(dict(action=action, **payload))
    headers={'Origin':'https://localhost:8000', 'X-NetBox-Sync-CSRF':'same-origin'}
    change=dict(host='source.example.test', expected_revision=1, request_id='reauth-test-request')
    with TestClient(create_app(settings=ApiSettings(), auth_client=Transport()), base_url='https://localhost:8000') as http:
        assert http.post('/api/v1/auth/reauthenticate', headers=headers, json={'password':PASSWORD}).status_code == 401
        http.cookies.set(COOKIE,token)
        r=http.post('/api/v1/policy', headers=headers, json=change)
        assert r.status_code==403 and r.json()['error']['code']=='AUTH_REAUTH_REQUIRED'
        assert http.get('/api/v1/auth/me').status_code==200
        assert http.post('/api/v1/auth/reauthenticate', json={'password':PASSWORD}).status_code==403
        assert http.post('/api/v1/auth/reauthenticate', headers=headers, json={'password':PASSWORD,'username':'someone-else'}).status_code==422
        r=http.post('/api/v1/auth/reauthenticate', headers=headers, json={'password':PASSWORD})
        assert r.status_code==200 and 'set-cookie' not in r.headers
        assert service.state['revision']==1
        assert http.post('/api/v1/policy', headers=headers, json=change).status_code==200
        assert http.post('/api/v1/policy', headers=headers, json={**change,'request_id':'another-test-request'}).status_code==409


def test_reauthentication_error_crosses_closed_auth_transport(monkeypatch):
    from netbox_sync.api.auth import AuthClient
    from netbox_sync.local_control import ControlError, SAFE_CODES
    assert 'AUTH_REAUTH_REQUIRED' in SAFE_CODES
    def refused(*args, **kwargs): raise ControlError('AUTH_REAUTH_REQUIRED')
    monkeypatch.setattr('netbox_sync.api.auth.request', refused)
    with pytest.raises(AuthError, match='^AUTH_REAUTH_REQUIRED$'):
        AuthClient('/unused').call('policy.update')


def test_real_unix_auth_confirmation_transport(tmp_path):
    import os
    import socket
    import multiprocessing
    from netbox_sync.local_control import serve
    from netbox_sync.api.auth import AuthClient
    if not hasattr(socket, 'SO_PEERCRED') or not hasattr(os,'geteuid') or os.geteuid()!=0:
        pytest.skip('Linux root Unix peer-credential transport gate')
    service, token, _ = enrolled()
    service.root('managed', {'ceiling':'public-ipv4'})
    service.now += 901
    path=str(tmp_path/'auth.sock')
    process=multiprocessing.get_context('fork').Process(target=serve,args=(path,service.call),kwargs={'allowed_uid':0},daemon=True)
    process.start()
    try:
        client=AuthClient(path)
        deadline=time.monotonic()+5
        while not (tmp_path/'auth.sock').exists():
            if time.monotonic()>deadline: pytest.fail('local Unix listener did not start')
            time.sleep(.01)
        change=dict(session=token,host='source.example.test',expected_revision=1,request_id='unix-confirmation')
        with pytest.raises(AuthError,match='^AUTH_REAUTH_REQUIRED$'): client.call('policy.update',**change)
        assert client.call('authorize',session=token)['username']=='admin'
        assert client.call('reauthenticate',session=token,password=PASSWORD)=={'confirmed':True}
        assert client.call('policy.update',**change)['revision']==2
    finally:
        process.terminate();process.join(5)
        if process.is_alive(): process.kill();process.join(5)
        assert not process.is_alive()
