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
    with pytest.raises(AuthError,match='AUTH_REQUIRED'):
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
