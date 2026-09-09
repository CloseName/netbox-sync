"""WEB-3 security regressions. No real network or database connections."""

import json
import io
import logging
import socket
import ssl
import subprocess
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from netbox_sync.api import connection_probe as probe
from netbox_sync.api.egress import EgressPolicy, pinned_dns, validate_host
from netbox_sync.api.onboarding_adapters import BrokerSecretStore, RegistrationRegistry
from netbox_sync.application.onboarding import EphemeralOnboardingStore, OnboardingError, SourceOnboardingService
from tests.test_onboarding import credentials, command, FakeSecrets, SECRET


@pytest.mark.parametrize('exception', [ValueError, TypeError])
@pytest.mark.parametrize('outcome', ['matching', 'absent', 'mismatch', 'unavailable'])
def test_post_commit_conversion_never_authorizes_rollback(exception, outcome):
    writer = RegistrationRegistry('', 'test_schema')
    registry = MagicMock()
    registry._create_parameters.return_value = tuple(range(22))
    registry._row_to_record.side_effect = exception(SECRET)
    writer._registry = lambda: registry
    writer.find = lambda _instance: None
    store = FakeSecrets()
    service = SourceOnboardingService({'proxmox': lambda _: None}, EphemeralOnboardingStore(), writer, store)
    committed = []
    config_seen = []
    registry._validate_config.side_effect = config_seen.append
    connection = registry._connect.return_value.__enter__.return_value
    registry._connect.return_value.__exit__.side_effect = lambda *args: committed.append(True)
    lookups = []

    def reconcile(instance):
        assert committed and connection.cursor.return_value.__enter__.return_value.execute.called
        lookups.append(instance)
        if outcome == 'unavailable':
            raise OnboardingError(probe.ErrorCode.REGISTRATION_UNCERTAIN)
        if outcome == 'absent':
            return None
        return config_seen[0] if outcome == 'matching' else replace(config_seen[0], name='different')

    writer.reconcile = reconcile
    request = command(service.test_connection(credentials()))
    if outcome == 'matching':
        assert service.register(request) == config_seen[0]
    else:
        with pytest.raises(OnboardingError, match='REGISTRATION_UNCERTAIN'):
            service.register(request)
    assert lookups == ['new-source']
    assert len(store.values) == 2


def answers(*addresses):
    return [(socket.AF_INET6 if ':' in address else socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))
            for address in addresses]


@pytest.mark.parametrize('address', ['127.0.0.1', '169.254.169.254', '169.254.1.2', '0.0.0.0',
                                     '224.0.0.1', '255.255.255.255', '192.0.2.1', '100.64.0.1'])
def test_special_destinations_always_denied(address):
    with pytest.raises(OnboardingError, match='SOURCE_DESTINATION_DENIED'):
        EgressPolicy(allowed_cidrs=('0.0.0.0/0',)).resolve(address, 443)


@pytest.mark.parametrize('address', ['10.24.0.2', '172.16.0.2', '192.168.1.2'])
def test_private_infrastructure_allowed_by_default(address):
    assert EgressPolicy().resolve(address, 443)[1] == address


def test_internal_hostname_and_all_dns_answers_checked():
    assert EgressPolicy().resolve('esxi.infra.internal', 443, lambda *args: answers('10.1.2.3'))[1] == '10.1.2.3'
    for values in [('127.0.0.1',), ('10.1.2.3', '169.254.169.254'), ('10.1.2.3', 'fe80::1')]:
        with pytest.raises(OnboardingError, match='SOURCE_DESTINATION_DENIED'):
            EgressPolicy().resolve('esxi.infra.internal', 443, lambda *args: answers(*values))


def test_operator_allow_deny_and_container_name_policy():
    with pytest.raises(OnboardingError):
        EgressPolicy().resolve('netbox-sync-postgres', 443, lambda *args: answers('10.1.1.1'))
    assert EgressPolicy(allowed_hosts=('esxi',)).resolve('esxi', 443, lambda *args: answers('10.1.1.1'))[1]
    with pytest.raises(OnboardingError):
        EgressPolicy().resolve('8.8.8.8', 443)
    assert EgressPolicy(allowed_cidrs=('8.8.8.8/32',)).resolve('8.8.8.8', 443)[1] == '8.8.8.8'
    with pytest.raises(OnboardingError):
        EgressPolicy(allowed_hosts=('esxi.infra',), denied_cidrs=('10.0.0.0/8',)).resolve(
            'esxi.infra', 443, lambda *args: answers('10.1.1.1'))


@pytest.mark.parametrize('value', ['::1', 'https://host', 'user@host', 'host/path', 'host?query',
                                   'host#fragment', 'host:443', '127.1', '0177.0.0.1', 'a\x00b'])
def test_address_syntax(value):
    with pytest.raises(ValueError):
        validate_host(value)


def test_pinning_prevents_second_dns_lookup_and_port_host_changes():
    resolver = Mock(return_value=answers('10.1.2.3'))
    host, address = EgressPolicy().resolve('esxi.infra', 443, resolver)
    resolver.return_value = answers('127.0.0.1')
    original = socket.getaddrinfo
    with pinned_dns(host, address, 443):
        assert socket.getaddrinfo(host, 443)[0][4] == ('10.1.2.3', 443)
        with pytest.raises(OnboardingError):
            socket.getaddrinfo('elsewhere.infra', 443)
        with pytest.raises(OnboardingError):
            socket.getaddrinfo(host, 80)
    assert socket.getaddrinfo is original
    resolver.assert_called_once()


@pytest.mark.parametrize('status', [301, 302, 307, 308])
@pytest.mark.parametrize('location', ['http://127.0.0.1/latest', 'https://other.infra:443/'])
def test_redirect_never_followed_or_credentials_forwarded(status, location):
    factory = Mock()
    connection = factory.return_value
    response = connection.getresponse.return_value
    response.status = status
    response.getheader.return_value = location
    with pytest.raises(OnboardingError, match='SOURCE_CONNECTION_FAILED'):
        probe.https_get('approved.infra', 8006, '/api2/json/version', None,
                        {'Authorization': SECRET}, factory=factory)
    factory.assert_called_once_with('approved.infra', port=8006, timeout=5, context=None)
    connection.request.assert_called_once()
    response.read.assert_not_called()
    response.getheader.assert_not_called()


@pytest.mark.parametrize('stage', ['request', 'getresponse', 'read'])
def test_proxmox_connect_and_read_timeouts(stage):
    factory = Mock()
    connection = factory.return_value
    response = connection.getresponse.return_value
    response.status = 200
    target = response if stage == 'read' else connection
    getattr(target, stage).side_effect = TimeoutError(SECRET)
    with pytest.raises(TimeoutError) as caught:
        probe.https_get('approved.infra', 8006, '/api2/json/version', None, factory=factory)
    assert probe.classify(caught.value) == probe.ErrorCode.SOURCE_TIMEOUT
    assert factory.call_args.kwargs['timeout'] == 5
    connection.close.assert_called_once()


def test_esxi_initial_probe_uses_bounded_https_and_no_smartconnect():
    def timeout(connection):
        assert connection.timeout == 5
        raise TimeoutError(SECRET)
    with patch('http.client.HTTPSConnection.connect', autospec=True, side_effect=timeout):
        with pytest.raises(TimeoutError):
            probe.probe_esxi(credentials('esxi'), 'approved.infra', ssl.create_default_context())


def test_esxi_real_connect_passes_timeout_to_soap_stub():
    xml = b'<namespaces version="1.0"><namespace><version>6.7</version></namespace></namespaces>'
    with patch('pyVim.connect.SoapStubAdapter', side_effect=TimeoutError(SECRET)) as stub:
        with pytest.raises(TimeoutError):
            probe.probe_esxi(credentials('esxi'), 'approved.infra', None, getter=lambda *args: xml)
    assert stub.call_args.kwargs['httpConnectionTimeout'] == 5


def test_whole_deadline_kills_and_reaps_child_without_credential_argv(monkeypatch):
    factory = MagicMock()
    process = factory.return_value.__enter__.return_value
    process.communicate.side_effect = [subprocess.TimeoutExpired('probe', 15), (b'', b'')]
    monkeypatch.setenv('NETBOX_SYNC_REGISTRATION_DSN', 'MUST_NOT_INHERIT')
    with pytest.raises(OnboardingError, match='SOURCE_TIMEOUT') as caught:
        probe.run_connection_test(credentials(), popen=factory)
    assert SECRET not in str(caught.value) + repr(factory.call_args)
    assert 'NETBOX_SYNC_REGISTRATION_DSN' not in factory.call_args.kwargs['env']
    assert process.communicate.call_args_list[0].kwargs['timeout'] == 15
    process.kill.assert_called_once()
    assert process.communicate.call_count == 2
    assert factory.call_args.kwargs['stderr'] == subprocess.DEVNULL


def test_broker_success_bookkeeping_released():
    store = BrokerSecretStore('/not-used')
    store._request = Mock(return_value={'ok': True, 'rollback_token': 'receipt'})
    receipt = store.create('src-test-0123456789abcdef', SECRET)
    assert store._operations
    store.forget([receipt])
    assert store._operations == {}
    assert store._request.call_count == 1


def test_successful_registration_calls_forget():
    from tests.test_onboarding import service
    instance, _registry, store = service()
    store.forget = Mock()
    instance.register(command(instance.test_connection(credentials())))
    assert len(store.forget.call_args.args[0]) == 2


def test_real_child_rejects_loopback_without_network_or_registry():
    with pytest.raises(OnboardingError, match='SOURCE_DESTINATION_DENIED'):
        probe.run_connection_test(replace(credentials(), address='127.0.0.1'))


def test_child_logging_policy_blocks_dependency_bodies(monkeypatch, caplog):
    payload = {'credentials': credentials().__dict__, 'policy': {}}
    monkeypatch.setattr(probe.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(json.dumps(payload).encode())))
    output = io.StringIO()
    monkeypatch.setattr(probe.sys, 'stdout', output)
    def noisy_failure(*_args):
        for name in ('proxmoxer.core', 'requests', 'urllib3', 'pyVmomi'):
            logging.getLogger(name).error(SECRET)
        raise ssl.SSLError(SECRET)
    monkeypatch.setattr(probe, 'execute', noisy_failure)
    old = logging.root.manager.disable
    try:
        probe.main()
        assert SECRET not in output.getvalue() + caplog.text
        assert json.loads(output.getvalue()) == {'ok': False, 'error': 'SOURCE_TLS_FAILED'}
    finally:
        logging.disable(old)


def test_pinned_https_keeps_original_tls_server_name():
    context = Mock()
    context.post_handshake_auth = None
    connection = probe.http.client.HTTPSConnection('esxi.infra', port=443, context=context, timeout=5)
    with pinned_dns('esxi.infra', '10.1.2.3', 443), patch('socket.socket') as sockets:
        connection.connect()
    sockets.return_value.connect.assert_called_once_with(('10.1.2.3', 443))
    assert context.wrap_socket.call_args.kwargs['server_hostname'] == 'esxi.infra'


def test_secret_layout_fallback_preserves_legacy_priority_and_custom_root(tmp_path):
    from netbox_sync.secret_resolver import FileSecretResolver, SecretResolutionError
    from netbox_sync.source_config import SecretReference
    old, new = tmp_path / 'old', tmp_path / 'new'
    old.mkdir()
    new.mkdir()
    key = 'src-test-secret-0123456789abcdef'
    (new / key).write_text('NEW_FAKE')
    reference = SecretReference('file', key)
    resolver = FileSecretResolver(secret_root=old, source_secret_root=new)
    assert resolver.resolve(reference) == 'NEW_FAKE'
    (old / key).write_text('LEGACY_FAKE')
    assert resolver.resolve(reference) == 'LEGACY_FAKE'
    (old / key).write_text('')
    with pytest.raises(SecretResolutionError, match='empty'):
        resolver.resolve(reference)
    (old / key).unlink()
    with pytest.raises(SecretResolutionError):
        FileSecretResolver(secret_root=old).resolve(reference)


def test_secret_layout_never_falls_back_on_permission_error(tmp_path):
    from pathlib import Path
    from netbox_sync.secret_resolver import FileSecretResolver, SecretResolutionError
    from netbox_sync.source_config import SecretReference
    with patch.object(Path, 'read_text', side_effect=PermissionError('blocked')) as read:
        with pytest.raises(SecretResolutionError):
            FileSecretResolver(secret_root=tmp_path, source_secret_root=tmp_path / 'new').resolve(
                SecretReference('file', 'logical-key'))
    assert read.call_count == 1


def test_cancellation_revokes_token_without_registry_or_broker_writes():
    from fastapi.testclient import TestClient
    from tests.auth_support import authenticated_app as create_app
    from netbox_sync.api.settings import ApiSettings
    from tests.test_onboarding import service, HEADERS
    instance, registry, secrets = service()
    token = instance.test_connection(credentials())
    with TestClient(create_app(ApiSettings(allowed_write_hosts=('testserver',)), onboarding_service=instance)) as client:
        path = '/api/v1/sources/cancel-onboarding'
        assert client.post(path, json={'onboarding_token': token}).status_code == 403
        for _attempt in range(2):
            result = client.post(path, json={'onboarding_token': token}, headers=HEADERS)
            assert result.status_code == 200 and result.json() == {'status': 'cancelled'}
    with pytest.raises(OnboardingError, match='ONBOARDING_TOKEN_INVALID'):
        instance.register(command(token))
    assert registry.records == secrets.values == {}

@pytest.mark.parametrize('name', ['localhost','host.docker.internal','gateway.docker.internal','kubernetes.default.svc'])
def test_protected_service_names_cannot_be_explicitly_allowed(name):
    with pytest.raises(OnboardingError, match='SOURCE_DESTINATION_DENIED'):
        EgressPolicy(allowed_hosts=(name,)).resolve(name,443,lambda *args: answers('10.1.1.1'))

def test_dns_error_has_safe_distinct_code():
    assert probe.classify(socket.gaierror('private resolver detail')).value == 'SOURCE_DNS_FAILED'
