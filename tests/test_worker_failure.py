"""Only closed codes and repository frame metadata cross worker boundaries."""
import json
import socket
import ssl
from types import SimpleNamespace

import pytest
from pynetbox.core.query import RequestError

from netbox_sync.worker_failure import classify, diagnostic, safe_diagnostic


@pytest.mark.parametrize('error,code', [
    (socket.gaierror('private endpoint'), 'SOURCE_DNS_FAILED'),
    (ConnectionRefusedError('private endpoint'), 'SOURCE_CONNECTION_FAILED'),
    (TimeoutError('private endpoint'), 'SOURCE_TIMEOUT'),
    (ssl.SSLError('private endpoint'), 'SOURCE_TLS_FAILED'),
])
def test_provider_classification_does_not_publish_exception_text(error, code):
    result = diagnostic(error, 'provider')
    assert result['code'] == code
    assert 'private endpoint' not in json.dumps(result)


@pytest.mark.parametrize('status,code', [(401, 'NETBOX_AUTH_FAILED'), (403, 'NETBOX_PERMISSION_DENIED')])
def test_netbox_permission_failure_inside_planner_retains_target(status, code):
    # Do not construct RequestError with real request data or credentials.
    error = RequestError.__new__(RequestError)
    error.req = SimpleNamespace(status_code=status)
    assert classify(error, 'planning') == code


@pytest.mark.parametrize('frames', [None, 7, 'untrusted', {}, [None, {}, {'line': True}]])
def test_malformed_child_diagnostics_fail_closed(frames):
    assert safe_diagnostic({'frames': frames}, 'PLANNER_FAILED') == {
        'code': 'PLANNER_FAILED', 'stage': 'planning', 'frames': []}


def test_child_metadata_is_filtered_and_cannot_override_code_or_stage():
    result = safe_diagnostic({'code': 'private', 'stage': 'private', 'frames': [
        {'module': 'runtime_plan', 'function': 'build_runtime_plan', 'line': 42,
         'locals': 'private', 'message': 'private'},
        {'module': '/private/path', 'function': 'unsafe', 'line': 1},
    ]}, 'PLANNER_FAILED')
    assert result['frames'] == [{'module': 'runtime_plan', 'function': 'build_runtime_plan', 'line': 42}]
    assert 'private' not in json.dumps(result)


@pytest.mark.parametrize('error,code',[(socket.gaierror('private'),'SOURCE_DNS_FAILED'),(ssl.SSLError('private'),'SOURCE_TLS_FAILED'),(TimeoutError('private'),'SOURCE_TIMEOUT')])
def test_esxi_client_preserves_only_safe_error_classification(error,code):
    from netbox_sync.esxi_client import EsxiClient,EsxiConnectionError
    def fail(*args):raise error
    client=EsxiClient(resolver=SimpleNamespace(resolve=lambda _: 'ephemeral'),connector=fail)
    source=SimpleNamespace(address='fixture.invalid',api_port=443,verify_ssl=True,credentials=SimpleNamespace(username='fixture',password_reference=None))
    with pytest.raises(EsxiConnectionError) as caught:
        with client.session(source):pytest.fail('No session after connection refusal')
    assert classify(caught.value,'provider')==code
    assert str(caught.value)=='ESXi connection failed'
    assert 'private' not in json.dumps(diagnostic(caught.value,'provider'))
