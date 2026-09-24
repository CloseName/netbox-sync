"""Bounded protocol refusals and ambiguity; real HTTPS is a separate model gate."""
import json
from uuid import uuid4
import pytest
import requests
from netbox_sync.retirement_transport import GuardClient, GuardTransportError, MAX_RESPONSE

class Response:
    def __init__(self, status, value):
        self.status_code = status
        self.body = json.dumps(value).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def iter_content(self, _size): yield self.body

class Session:
    verify = True
    trust_env = False
    def __init__(self, response): self.response, self.calls = response, []
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if isinstance(self.response, Exception): raise self.response
        return self.response

def client(response):
    session = Session(response)
    return GuardClient(session, 'https://netbox.example', 'Token fixture-only', str(uuid4())), session

@pytest.mark.parametrize('status,body,uncertain,code', [
    (409, {'code':'OWNERSHIP_CONFLICT'}, False, 'OWNERSHIP_CONFLICT'),
    (403, {'code':'PERMISSION_DENIED'}, False, 'PERMISSION_DENIED'),
    (503, {'code':'OWNERSHIP_CONFLICT'}, True, 'GUARD_RESPONSE_UNCONFIRMED'),
    (409, {'code':'arbitrary remote text'}, True, 'GUARD_RESPONSE_UNCONFIRMED'),
    (302, {'code':'PERMISSION_DENIED'}, True, 'GUARD_RESPONSE_UNCONFIRMED'),
    (200, {}, True, 'GUARD_RESPONSE_INVALID'),
])
def test_write_refusal_or_ambiguity(status, body, uncertain, code):
    guard, session = client(Response(status, body))
    with pytest.raises(GuardTransportError) as error:
        guard.execute(uuid4(), 'a'*64)
    assert error.value.code == code
    assert error.value.uncertain == uncertain
    assert len(session.calls) == 1
    assert session.calls[0][2]['allow_redirects'] is False
    assert session.calls[0][2]['timeout'] == (3,15)
    assert 'arbitrary' not in str(error.value)

@pytest.mark.parametrize('method', ['read', 'write'])
def test_connection_loss_is_not_retried(method):
    guard, session = client(requests.ConnectionError('untrusted payload'))
    with pytest.raises(GuardTransportError) as error:
        if method == 'read': guard.receipt(uuid4())
        else: guard.execute(uuid4(), 'b'*64)
    assert error.value.uncertain == (method == 'write')
    assert str(error.value) == 'GUARD_CONNECTION_FAILED'
    assert len(session.calls) == 1

def test_bounded_response():
    response = Response(200,{})
    response.body = b'x'*(MAX_RESPONSE+1)
    guard, _ = client(response)
    with pytest.raises(GuardTransportError, match='GUARD_RESPONSE_INVALID') as error:
        guard.execute(uuid4(), 'b'*64)
    assert error.value.uncertain

@pytest.mark.parametrize('url', ['http://netbox.example', 'https://user:secret@netbox.example',
                                'https://netbox.example?other=1', 'https://netbox.example/api/'])
def test_fixed_https_authority(url):
    with pytest.raises(GuardTransportError, match='GUARD_URL_INVALID'):
        GuardClient(Session(None), url, 'Token fixture-only', str(uuid4()))

@pytest.mark.parametrize('attribute,value', [('verify',False),('trust_env',True)])
def test_verification_and_environment_boundary(attribute,value):
    session = Session(None);setattr(session,attribute,value)
    with pytest.raises(GuardTransportError, match='GUARD_TLS_REQUIRED'):
        GuardClient(session,'https://netbox.example','Token fixture-only',str(uuid4()))

def test_other_namespace_cannot_supply_capabilities():
    guard, session = client(Response(200, {'protocol':1,'guard_instance':str(uuid4()),
        'netbox_version':'4.7.0','atomic_dependency_guard':True,'creation_receipts':True,'retirement_receipts':True}))
    with pytest.raises(GuardTransportError, match='GUARD_CAPABILITY_MISMATCH'):
        guard.capabilities()
    assert len(session.calls)==1

def test_wrong_nonce_is_not_terminal_result():
    guard, _ = client(Response(200, {'nonce':str(uuid4()),'digest':'a'*64,
                                    'manifest':{},'deleted':[],'status':'SUCCEEDED'}))
    with pytest.raises(GuardTransportError, match='GUARD_RESPONSE_INVALID') as error:
        guard.execute(uuid4(), 'a'*64)
    assert error.value.uncertain


def test_creation_receipt_is_get_only_and_binds_original_wire_request():
    import hashlib
    def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
    nonce=str(uuid4()); data={'name':'scoped','type':1}
    body={'nonce':nonce,'source_instance':'esxi-fixture','resource':'cluster','cluster_id':None,'data':data}
    value={'nonce':nonce,'source_instance':'esxi-fixture','resource':'cluster',
           'digest':digest(['esxi-fixture','cluster',{'wire':digest(body)},None]),'object':{'id':7}}
    guard, session=client(Response(200,value))
    assert guard.creation_receipt(nonce,'esxi-fixture','cluster',None,data)=={'id':7}
    assert session.calls[0][0]=='GET'
    with pytest.raises(GuardTransportError,match='GUARD_RESPONSE_INVALID'):
        guard.creation_receipt(nonce,'esxi-fixture','cluster',None,{'name':'changed','type':1})
    assert all(call[0]=='GET' for call in session.calls)
