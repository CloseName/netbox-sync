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


def test_provider_progress_counts_are_closed_and_content_free():
    result=safe_diagnostic({'phases':[{'phase':'esxi_properties','state':'failed','duration_ms':100,
        'requests':2,'objects':'secret description','token':'private'}]},'DISCOVERY_TIMEOUT')
    assert result['phases']==[{'phase':'esxi_properties','state':'failed','duration_ms':100,'requests':2}]


def test_failed_stage_is_not_reported_as_successful_completion(monkeypatch):
    from netbox_sync.worker_failure import failure_stage, DiagnosticFailure
    values=[]
    monkeypatch.setattr('netbox_sync.child_process.phase_progress',lambda *args,**kwargs:values.append((args,kwargs)))
    with pytest.raises(DiagnosticFailure):
        with failure_stage('provider'):raise ValueError('private')
    assert values[0][0]==('provider',)
    assert values[-1][1]=={'failed':True}

@pytest.mark.parametrize('duration,accepted', [(None, True), (0, True), (86400000, True),
    (True, False), (-1, False), (86400001, False), ('10', False)])
def test_phase_duration_bounds_and_exact_integer_contract(duration, accepted):
    row = {'phase': 'esxi_properties', 'state': 'finished', 'duration_ms': duration,
           'requests': True, 'objects': 10000000, 'private': 'hidden'}
    result = safe_diagnostic({'phases': [row]}, 'PLANNER_FAILED')
    assert result['phases'] == ([{'phase': 'esxi_properties', 'state': 'finished',
        'duration_ms': duration, 'objects': 10000000}] if accepted else [])


def test_diagnostic_limits_apply_before_filtering():
    frame = {'module': 'safe', 'function': 'safe', 'line': 1}
    phase = {'phase': 'esxi_properties', 'state': 'finished'}
    result = safe_diagnostic({'frames': [None] * 8 + [frame],
                             'phases': [phase] + [None] * 64}, 'PLANNER_FAILED')
    assert result['frames'] == [] and result['phases'] == []


@pytest.mark.parametrize('status', [True, 99, 600, '200', None])
def test_http_metadata_requires_bounded_exact_integer_status(status):
    result = safe_diagnostic({'http': {'status': status, 'method': 'GET'}}, 'PLANNER_FAILED')
    assert 'http' not in result


def test_http_metadata_drops_unknown_fields_without_dropping_valid_status():
    result = safe_diagnostic({'http': {'status': 200, 'method': 'PRIVATE',
        'endpoint': '/private', 'headers': 'secret'}}, 'PLANNER_FAILED')
    assert result['http'] == {'status': 200}


@pytest.mark.parametrize('stage,code', [('planning', 'PLANNER_FAILED'),
    ('provider', 'PROVIDER_UNAVAILABLE'), ('netbox', 'NETBOX_UNAVAILABLE'),
    ('unknown', 'DISCOVERY_FAILED')])
def test_unknown_exception_uses_stage_fallback_without_message(stage, code):
    assert classify(ValueError('private'), stage) == code


@pytest.mark.parametrize('name,code', [('InvalidLogin', 'SOURCE_AUTH_FAILED'),
    ('vim.fault.InvalidLogin', 'SOURCE_AUTH_FAILED'), ('NoPermission', 'SOURCE_PERMISSION_DENIED'),
    ('vim.fault.NoPermission', 'SOURCE_PERMISSION_DENIED')])
def test_provider_named_faults_preserve_http_precedence(name, code):
    error = type(name, (Exception,), {})('private')
    assert classify(error, 'netbox') == code
    assert classify(error, []) == code
    error.status_code = 401
    assert classify(error, 'netbox') == 'NETBOX_AUTH_FAILED'
    error.code = 'PLANNER_FAILED'
    assert classify(error, 'netbox') == 'PLANNER_FAILED'
