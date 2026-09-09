"""WEB-3 application and API security boundaries, using only injected fakes."""

import socket
import ssl
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from netbox_sync.api.app import create_app
from netbox_sync.api.connection_probe import classify, probe_esxi, probe_proxmox
from netbox_sync.api.onboarding_dto import ConnectionRequest, RegistrationRequest
from netbox_sync.api.settings import ApiSettings
from netbox_sync.application.onboarding import (
    EphemeralOnboardingStore, OnboardingError, PendingCredentials, RegistrationWriteError,
    SecretReceipt, SourceOnboardingService,
)
from netbox_sync.application.observability import ErrorCode

SECRET = 'FAKE_CREDENTIAL_NEVER_ECHO'
HEADERS = {'Origin': 'http://testserver', 'X-NetBox-Sync-CSRF': 'same-origin'}


class FakeRegistry:
    """In-memory transaction outcomes; no update/delete interface exists."""

    def __init__(self):
        self.records = {}
        self.failure = None
        self.uncertain_lookup = False

    def find(self, instance):
        return self.records.get(instance)

    def create(self, config):
        if self.failure == 'before':
            raise RegistrationWriteError(definitely_failed=True)
        if self.failure == 'uncertain_before':
            raise RegistrationWriteError()
        self.records[config.source_instance] = config
        if self.failure == 'after':
            raise RegistrationWriteError()
        return config

    def reconcile(self, instance):
        if self.uncertain_lookup:
            raise OnboardingError(ErrorCode.REGISTRATION_UNCERTAIN)
        return self.find(instance)


class FakeSecrets:
    """Write and exact-receipt rollback port."""

    def __init__(self):
        self.values = {}
        self.fail_after = None

    def create(self, key, value):
        if self.fail_after == len(self.values):
            raise OnboardingError(ErrorCode.SECRET_STORE_FAILED)
        assert key not in self.values
        self.values[key] = value
        return SecretReceipt(key, 'receipt')

    def rollback(self, receipt):
        assert receipt.rollback_token == 'receipt'
        del self.values[receipt.key]


def command(token, source_type='proxmox', source_instance='new-source',
            address='source.test'):
    return RegistrationRequest(
        onboarding_token=token, source_type=source_type, source_instance=source_instance, name='New source',
        address=address, verify_ssl=True, sync_interval_seconds=600, site_slug='test', cluster_name='Test',
        platform_slug='platform', device_role_slug='host', device_type_slug='server', cluster_type_slug='cluster',
        confirm_sync_disabled=True,
    ).command()


def credentials(source_type='proxmox', address='source.test'):
    return PendingCredentials(source_type, address, True, 'user@realm', 'token-name', SECRET)


def service():
    registry, store = FakeRegistry(), FakeSecrets()
    instance = SourceOnboardingService({'proxmox': lambda _: None, 'esxi': lambda _: None},
                                       EphemeralOnboardingStore(), registry, store)
    return instance, registry, store


@pytest.mark.parametrize('source_type', ['proxmox', 'esxi'])
def test_successful_registration_defaults_and_references(source_type):
    instance, registry, store = service()
    token = instance.test_connection(credentials(source_type))
    assert registry.records == store.values == {}
    result = instance.register(command(token, source_type))
    assert result.enabled and not result.sync_enabled and not result.legacy_identity_owner
    assert result.settings == {}
    assert result.credentials.token_secret.provider == 'file'
    assert store.values[result.credentials.token_secret.key] == SECRET
    assert SECRET not in repr(result)
    assert SECRET not in repr(credentials(source_type))
    if source_type == 'esxi':
        assert result.credentials.token_id == result.credentials.token_secret


def test_two_proxmox_sources_receive_distinct_secret_references():
    instance, registry, store = service()
    first_token = instance.test_connection(credentials(address='pve-a.test'))
    first = instance.register(command(
        first_token, source_instance='pve-a', address='pve-a.test',
    ))
    second_token = instance.test_connection(credentials(address='pve-a-2.test'))
    second = instance.register(command(
        second_token, source_instance='pve-a-2', address='pve-a-2.test',
    ))

    first_keys = {
        first.credentials.token_id.key, first.credentials.token_secret.key,
    }
    second_keys = {
        second.credentials.token_id.key, second.credentials.token_secret.key,
    }
    assert first_keys.isdisjoint(second_keys)
    assert set(registry.records) == {'pve-a', 'pve-a-2'}
    assert set(store.values) == first_keys | second_keys


def test_similar_multi_provider_instances_never_collide_secret_keys():
    instance, registry, store = service()
    created = []
    cases = (
        ('proxmox', 'pve-a'), ('proxmox', 'pve_a'),
        ('proxmox', 'pve-a-1'), ('esxi', 'esxi-a'),
    )
    for index, (source_type, source_instance) in enumerate(cases):
        address = f'source-{index}.test'
        token = instance.test_connection(credentials(source_type, address))
        created.append(instance.register(command(
            token, source_type, source_instance, address,
        )))

    keys = [
        reference.key
        for config in created
        for reference in {config.credentials.token_id, config.credentials.token_secret}
    ]
    assert len(keys) == len(set(keys)) == 7
    assert set(registry.records) == {item[1] for item in cases}
    assert set(store.values) == set(keys)


def test_duplicate_is_rejected_without_new_secret_or_mutation():
    instance, registry, store = service()
    first = instance.register(command(instance.test_connection(credentials())))
    before = dict(store.values)
    with pytest.raises(OnboardingError, match='SOURCE_ALREADY_EXISTS'):
        instance.register(command(instance.test_connection(credentials())))
    assert registry.records == {'new-source': first}
    assert store.values == before


def test_definite_failure_rolls_back_only_attempt_secrets():
    instance, registry, store = service()
    store.values['preexisting'] = 'keep'
    registry.failure = 'before'
    with pytest.raises(OnboardingError, match='REGISTRATION_FAILED'):
        instance.register(command(instance.test_connection(credentials())))
    assert store.values == {'preexisting': 'keep'}


def test_partial_secret_failure_never_writes_registry():
    instance, registry, store = service()
    store.fail_after = 1
    with pytest.raises(OnboardingError, match='SECRET_STORE_FAILED'):
        instance.register(command(instance.test_connection(credentials())))
    assert registry.records == store.values == {}


@pytest.mark.parametrize('lookup_fails', [False, True])
def test_uncertain_commit_never_blindly_removes_secrets(lookup_fails):
    instance, registry, store = service()
    registry.failure = 'uncertain_before'
    registry.uncertain_lookup = lookup_fails
    with pytest.raises(OnboardingError, match='REGISTRATION_UNCERTAIN'):
        instance.register(command(instance.test_connection(credentials())))
    assert len(store.values) == 2


def test_commit_success_reconciled_after_lost_ack():
    instance, registry, store = service()
    registry.failure = 'after'
    result = instance.register(command(instance.test_connection(credentials())))
    assert registry.records['new-source'] == result
    assert len(store.values) == 2


def test_single_use_and_expired_tokens():
    store = EphemeralOnboardingStore(clock=lambda: 0)
    token = store.issue(credentials())
    assert store.consume(token) == credentials()
    with pytest.raises(OnboardingError):
        store.consume(token)
    expired = store.issue(credentials())
    store._clock = lambda: 1000
    with pytest.raises(OnboardingError):
        store.consume(expired)


@pytest.mark.parametrize(('exception', 'code'), [
    (socket.timeout(), 'SOURCE_TIMEOUT'), (ssl.SSLError(SECRET), 'SOURCE_TLS_FAILED'),
    (ConnectionError(SECRET), 'SOURCE_CONNECTION_FAILED'),
])
def test_connection_errors_are_redacted(exception, code):
    assert classify(exception).value == code
    assert SECRET not in str(OnboardingError(classify(exception)))


def test_proxmox_only_reads_version_and_sets_timeout():
    calls = []
    def getter(host, port, path, context, headers):
        calls.append((host, port, path))
        assert headers['Authorization'] == 'PVEAPIToken=user@realm!token-name=' + SECRET
        return b'{"data":{"version":"8"}}'
    probe_proxmox(credentials(), 'source.test', None, getter=getter)
    assert calls == [('source.test', 8006, '/api2/json/version')]


def test_esxi_reads_content_and_disconnects_with_timeout():
    closed = []
    def connect(**kwargs):
        assert kwargs['httpConnectionTimeout'] == 5
        return SimpleNamespace(RetrieveContent=lambda: SimpleNamespace(about=SimpleNamespace(version='6.7')))
    probe_esxi(credentials('esxi'), 'source.test', None, connector=connect, disconnecter=closed.append,
               getter=lambda *args: b'<namespaces version="1.0"><namespace><version>6.7</version></namespace></namespaces>')
    assert len(closed) == 1


def test_api_confirmation_and_redaction(caplog):
    instance, registry, store = service()
    settings = ApiSettings(allowed_write_hosts=('testserver',))
    with TestClient(create_app(settings, onboarding_service=instance)) as client:
        payload = dict(source_type='proxmox', address='source.test', verify_ssl=True,
                       username='user@realm', token_id='token-name', secret=SECRET)
        response = client.post('/api/v1/sources/test-connection', json=payload, headers=HEADERS)
        assert response.status_code == 200
        assert registry.records == store.values == {}
        assert SECRET not in response.text + caplog.text
        token = response.json()['onboarding_token']
        request = command(token).__dict__
        invalid = client.post('/api/v1/sources', json={**request, 'confirm_sync_disabled': False}, headers=HEADERS)
        assert invalid.status_code == 422
        created = client.post('/api/v1/sources', json=request, headers=HEADERS)
        assert created.status_code == 201
        assert created.json()['sync_enabled'] is False
        assert not any(key in created.json() for key in ('credentials', 'username', 'settings', 'id'))
        malformed = client.post('/api/v1/sources/test-connection', json={**payload, 'address': SECRET + '/bad'},
                                headers=HEADERS)
        assert malformed.status_code == 422
        assert malformed.json()["error"]["code"] == "SOURCE_ADDRESS_INVALID"
        assert SECRET not in created.text + malformed.text + caplog.text


@pytest.mark.parametrize('headers', [{}, {'Origin': 'http://foreign.test'},
    {'Origin': 'http://testserver', 'X-NetBox-Sync-CSRF': 'bad'},
    {**HEADERS, 'Sec-Fetch-Site': 'cross-site'}])
def test_write_forgery_is_rejected(headers):
    with TestClient(create_app(ApiSettings(allowed_write_hosts=('testserver',)))) as client:
        response = client.post('/api/v1/sources/test-connection', json={}, headers=headers)
    assert response.status_code == 403
    assert response.json()['error']['request_id'] == response.headers['X-Request-ID']


def test_request_repr_and_dump_protect_credentials():
    request = ConnectionRequest(source_type='esxi', address='host.test', username=SECRET, secret=SECRET)
    assert SECRET not in repr(request)
    assert 'secret' not in request.model_dump()


def test_legacy_runtime_credential_repr_is_protected():
    from netbox_sync.secret_resolver import ResolvedSourceCredentials
    from netbox_sync.source_config import SourceCredentials, SecretReference
    reference = SecretReference('file', 'logical-key')
    assert SECRET not in repr(SourceCredentials(SECRET, reference, reference))
    assert SECRET not in repr(ResolvedSourceCredentials(SECRET, SECRET, SECRET))


def test_auth_failure_is_classified_without_echo():
    class InvalidLogin(Exception):
        pass
    assert classify(InvalidLogin(SECRET)) == ErrorCode.SOURCE_AUTH_FAILED

def test_no_unauthenticated_policy_management_or_disclosure_endpoint():
    instance, registry, store = service()
    with TestClient(create_app(ApiSettings(allowed_write_hosts=('testserver',)), onboarding_service=instance)) as client:
        for method in ('GET','POST','PATCH'):
            response=client.request(method,'/api/v1/source-access-policy',headers=HEADERS)
            assert response.status_code==404
        assert registry.records == store.values == {}
