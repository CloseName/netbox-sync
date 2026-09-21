"""WEB-5 apply worker rejects capability-bearing input and sanitizes children."""

from io import BytesIO, StringIO
import json
import subprocess
import sys
from types import SimpleNamespace
from uuid import UUID

import pytest

from netbox_sync.apply_worker import (ApplySupervisor, ApplyWorkerError, _receive,
                                          child_main)
from netbox_sync.application.confirmation import ConfirmationClaims, ConfirmationStore
from netbox_sync.discovery_worker import _safe_environment
from netbox_sync.run_history import RunStatus

from tests.sample_data import sample_source_config


class Connection:
    """One-shot local socket fixture."""

    def __init__(self, value):
        self.value = value

    def settimeout(self, _value):
        """Accept the worker's bounded-read timeout."""

    def recv(self, _size):
        value, self.value = self.value, b''
        return value


class ChildInput:
    """Text-stream shape exposing binary child input."""

    def __init__(self, payload):
        self.buffer = BytesIO(json.dumps(payload).encode())


def test_apply_child_redirects_executor_output_and_emits_only_json(monkeypatch):
    output, errors = StringIO(), StringIO()

    def execute(_payload):
        print('guarded apply output')
        return {'status': 'SUCCEEDED', 'plan_digest': 'a' * 64}

    monkeypatch.setattr('netbox_sync.apply_worker.execute_child', execute)
    monkeypatch.setattr('netbox_sync.apply_worker.sys.stdin', ChildInput(
        {'operation': 'apply'}))
    monkeypatch.setattr('netbox_sync.apply_worker.sys.stdout', output)
    monkeypatch.setattr('netbox_sync.apply_worker.sys.stderr', errors)
    child_main()
    assert json.loads(output.getvalue()) == {'result': {
        'status': 'SUCCEEDED', 'plan_digest': 'a' * 64,
    }}
    assert 'guarded apply output' not in output.getvalue()
    assert 'guarded apply output' in errors.getvalue()


def test_worker_accepts_only_fixed_well_formed_prepare_and_apply_requests():
    """Digest/token shape is validated before privileged work."""
    prepare = {'operation': 'prepare', 'source_instance': 'pve-test',
               'plan_digest': 'a' * 64}
    apply = {'operation': 'apply', 'source_instance': 'pve-test',
             'confirmation_token': 'b' * 64}
    assert _receive(Connection(json.dumps(prepare).encode())) == prepare
    assert _receive(Connection(json.dumps(apply).encode())) == apply


@pytest.mark.parametrize('payload', [
    {'operation': 'apply', 'source_instance': 'pve-test', 'confirmation_token': 'x',
     'command': 'docker'},
    {'operation': 'apply', 'source_instance': 'pve-test', 'confirmation_token': 'x',
     'operations': ['delete']},
    {'operation': 'prepare', 'source_instance': 'pve-test', 'plan_digest': 'x',
     'secret_path': '/etc/shadow'},
])
def test_worker_protocol_rejects_commands_operations_and_paths(payload):
    with pytest.raises(ApplyWorkerError, match='REQUEST_INVALID'):
        _receive(Connection(json.dumps(payload).encode()))


def test_apply_child_environment_has_no_registration_or_registry_writer_credentials(monkeypatch):
    monkeypatch.setenv('NETBOX_SYNC_REGISTRATION_DSN', 'registration-secret')
    monkeypatch.setenv('NETBOX_SYNC_APPLY_REGISTRY_DSN', 'reader-secret')
    monkeypatch.setenv('NETBOX_SYNC_RUN_WRITER_DSN', 'run-writer-secret')
    monkeypatch.setenv('NB_APPLY_API_TOKEN', 'apply-secret')
    environment = _safe_environment()
    assert 'NETBOX_SYNC_REGISTRATION_DSN' not in environment
    assert 'NETBOX_SYNC_APPLY_REGISTRY_DSN' not in environment
    assert 'NETBOX_SYNC_RUN_WRITER_DSN' not in environment
    assert 'NB_APPLY_API_TOKEN' not in environment


class TimedOutProcess:
    """Popen-shaped timeout fixture."""

    returncode = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def communicate(self, _payload=None, timeout=None):
        if timeout is not None:
            raise subprocess.TimeoutExpired('child', timeout)
        return b'', b''

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


@pytest.mark.parametrize(('operation', 'code'), [
    ('plan', 'FAILED_BEFORE_WRITE'), ('apply', 'OUTCOME_UNCERTAIN'),
])
def test_timeout_distinguishes_prewrite_from_uncertain_apply(operation, code):
    """A timed-out write is never retried or misreported as safely failed."""
    supervisor = ApplySupervisor('', '', '', '', '', '', '', popen=lambda *_args, **_kwargs:
                                 TimedOutProcess())
    with pytest.raises(ApplyWorkerError, match=code):
        supervisor._child({'operation': operation})  # pylint: disable=protected-access


class RunRecorder:
    """Minimal history boundary for manual apply lifecycle assertions."""

    def __init__(self):
        self.started = []
        self.finished = []

    def reconciliation_required(self, source_instance):
        return False

    def start_run(self, source_instance, source_type, trigger, created_by):
        run = SimpleNamespace(run_id=UUID('11111111-1111-4111-8111-111111111111'))
        self.started.append((source_instance, source_type, trigger.value, created_by))
        return run

    def bind_plan(self, run_id, digest, version):
        self.bound = (run_id, digest, version)

    def finish_run(self, run_id, status, counts=None, plan_digest=None,
                   planner_version=None, error_code=None, error_message_safe=None):
        self.finished.append({
            'run_id': run_id, 'status': status, 'counts': counts,
            'plan_digest': plan_digest, 'planner_version': planner_version,
            'error_code': error_code, 'error_message_safe': error_message_safe,
        })


def _manual_supervisor(monkeypatch, child):
    config = sample_source_config()
    confirmations, recorder = ConfirmationStore(), RunRecorder()
    supervisor = ApplySupervisor('', '', '', '', '', '', '/run/netbox-sync/apply.lock',
                                 confirmations=confirmations, run_repository=recorder)
    monkeypatch.setattr(supervisor, '_source', lambda _instance: config)
    monkeypatch.setattr(supervisor, '_payload', lambda *_args: {'operation': 'apply'})
    monkeypatch.setattr(supervisor, '_child', child)
    monkeypatch.setitem(sys.modules, 'fcntl', SimpleNamespace(
        LOCK_EX=1, LOCK_NB=2, flock=lambda *_args: None,
    ))
    monkeypatch.setattr('netbox_sync.apply_worker.os.O_NOFOLLOW', 0, raising=False)
    monkeypatch.setattr('netbox_sync.apply_worker.os.open', lambda *_args: 99)
    monkeypatch.setattr('netbox_sync.apply_worker.os.close', lambda _fd: None)
    claims = ConfirmationClaims(config.source_instance, config.id, 'a' * 64, 'web-5a-1',
                                'source-fingerprint', 'target-fingerprint')
    return supervisor, confirmations.issue(claims), recorder


def test_successful_manual_sync_records_one_terminal_run_and_returns_run_id(monkeypatch):
    supervisor, token, recorder = _manual_supervisor(
        monkeypatch, lambda _payload: {
            'status': 'SUCCEEDED', 'plan_digest': 'a' * 64,
            'planner_version': 'web-5a-1',
            'action_counts': {'create': 2, 'update': 1},
        })
    result = supervisor.apply('pve-infra-test', token)
    assert recorder.started == [('pve-infra-test', 'proxmox', 'manual', 'web/manual')]
    assert len(recorder.finished) == 1
    assert recorder.finished[0]['status'] is RunStatus.SUCCEEDED
    assert recorder.finished[0]['counts'].create == 2
    assert result['run_id'] == '11111111-1111-4111-8111-111111111111'


@pytest.mark.parametrize(('worker_code', 'expected_status'), [
    ('PLAN_STALE', RunStatus.FAILED),
    ('OUTCOME_UNCERTAIN', RunStatus.OUTCOME_UNCERTAIN),
])
def test_manual_worker_failure_records_safe_terminal_outcome(
        monkeypatch, worker_code, expected_status):
    def fail(_payload):
        raise ApplyWorkerError(worker_code)
    supervisor, token, recorder = _manual_supervisor(monkeypatch, fail)
    with pytest.raises(ApplyWorkerError, match=worker_code):
        supervisor.apply('pve-infra-test', token)
    assert len(recorder.started) == len(recorder.finished) == 1
    assert recorder.finished[0]['run_id'] == UUID('11111111-1111-4111-8111-111111111111')
    assert recorder.finished[0]['status'] is expected_status
    assert recorder.finished[0]['error_code'] == worker_code
    assert 'secret' not in recorder.finished[0]['error_message_safe'].casefold()


def test_post_child_digest_mismatch_is_uncertain_on_same_run(monkeypatch):
    secret = 'RAW_CHILD_SECRET_MUST_NOT_APPEAR'
    supervisor, token, recorder = _manual_supervisor(
        monkeypatch, lambda _payload: {
            'status': 'SUCCEEDED', 'plan_digest': 'b' * 64,
            'planner_version': 'web-5a-1', 'action_counts': {},
            'raw_detail': secret,
        })

    with pytest.raises(ApplyWorkerError, match='OUTCOME_UNCERTAIN'):
        supervisor.apply('pve-infra-test', token)

    assert len(recorder.started) == len(recorder.finished) == 1
    assert recorder.finished[0]['run_id'] == UUID('11111111-1111-4111-8111-111111111111')
    assert recorder.finished[0]['status'] is RunStatus.OUTCOME_UNCERTAIN
    assert recorder.finished[0]['error_code'] == 'OUTCOME_UNCERTAIN'
    assert recorder.finished[0]['error_code'] != 'PLAN_STALE'
    assert secret not in repr(recorder.finished)


def test_manual_confirmation_failure_still_records_terminal_attempt(monkeypatch):
    supervisor, _token, recorder = _manual_supervisor(
        monkeypatch, lambda _payload: pytest.fail('child must not execute'))
    with pytest.raises(ApplyWorkerError, match='CONFIRMATION_INVALID'):
        supervisor.apply('pve-infra-test', '0' * 64)
    assert recorder.finished[0]['status'] is RunStatus.FAILED
    assert recorder.finished[0]['error_code'] == 'CONFIRMATION_INVALID'


def test_manual_apply_lock_records_locked_without_starting_child(monkeypatch):
    supervisor, token, recorder = _manual_supervisor(
        monkeypatch, lambda _payload: pytest.fail('child must not execute'))

    def locked(*_args):
        raise OSError('busy')
    monkeypatch.setitem(sys.modules, 'fcntl', SimpleNamespace(
        LOCK_EX=1, LOCK_NB=2, flock=locked,
    ))
    with pytest.raises(ApplyWorkerError, match='APPLY_LOCKED'):
        supervisor.apply('pve-infra-test', token)
    assert recorder.finished[0]['status'] is RunStatus.LOCKED
    assert recorder.finished[0]['error_code'] == 'APPLY_LOCKED'


class GenerationGuard:
    def __init__(self):
        self.current = '11111111-1111-4111-8111-111111111111'
        self.calls = []

    def review_guard(self, source, digest, operation_id):
        from contextlib import contextmanager
        from netbox_sync.source_operations import OperationError
        @contextmanager
        def guard():
            self.calls.append((source, digest, operation_id))
            if operation_id != self.current:
                raise OperationError('PLAN_STALE')
            yield
        return guard()


def test_replaced_generation_cannot_apply_even_with_unchanged_digest(monkeypatch):
    writes = []
    supervisor, _, recorder = _manual_supervisor(monkeypatch, writes.append)
    gate = GenerationGuard()
    supervisor.operations = gate
    config = sample_source_config()
    claims = ConfirmationClaims(config.source_instance, config.id, 'a' * 64, 'version',
                                'source', 'target', gate.current)
    token = supervisor._confirmations.issue(claims)
    gate.current = '22222222-2222-4222-8222-222222222222'
    with pytest.raises(ApplyWorkerError, match='PLAN_STALE'):
        supervisor.apply(config.source_instance, token)
    assert writes == []
    assert recorder.finished[-1]['error_code'] == 'PLAN_STALE'
    with pytest.raises(ApplyWorkerError, match='CONFIRMATION_INVALID'):
        supervisor.apply(config.source_instance, token)


def test_prepare_requires_reviewed_generation_and_binds_token(monkeypatch):
    config = sample_source_config()
    supervisor = ApplySupervisor('', '', '', '', '', '', '')
    gate = GenerationGuard()
    supervisor.operations = gate
    calls = []
    monkeypatch.setattr(supervisor, '_source', lambda _: config)
    monkeypatch.setattr(supervisor, '_payload', lambda *_: {})
    def plan(_):
        calls.append(True)
        return dict(apply_allowed=True, digest='a'*64, planner_version='v',
                    source_fingerprint='s', target_fingerprint='t', items=[{'action':'CREATE'}])
    monkeypatch.setattr(supervisor, '_child', plan)
    with pytest.raises(ApplyWorkerError, match='PLAN_STALE'):
        supervisor.prepare(config.source_instance, 'a'*64)
    assert calls == []
    response = supervisor.prepare(config.source_instance, 'a'*64, gate.current)
    claims = supervisor._confirmations.consume(response['confirmation_token'], config.source_instance)
    assert claims.operation_id == gate.current
    assert claims.plan_digest == 'a'*64


def test_confirmation_actor_binding_prevents_other_operator_apply(monkeypatch):
    config = sample_source_config()
    supervisor = ApplySupervisor('', '', '', '', '', '', '/unused-fixture-lock')
    monkeypatch.setattr(supervisor, '_source', lambda _: config)
    monkeypatch.setattr(supervisor, '_payload', lambda *_: {})
    monkeypatch.setattr(supervisor, '_child', lambda _: dict(apply_allowed=True,digest='a'*64,
        planner_version='v',source_fingerprint='s',target_fingerprint='t',items=[{'action':'CREATE'}]))
    actor='11111111-1111-4111-8111-111111111111'
    result=supervisor.prepare(config.source_instance,'a'*64,actor_id=actor)
    with pytest.raises(ApplyWorkerError,match='CONFIRMATION_INVALID'):
        supervisor.apply(config.source_instance,result['confirmation_token'],actor_id='22222222-2222-4222-8222-222222222222')
    # Invalid use consumes the capability and never reaches the lock or child.
    with pytest.raises(ApplyWorkerError,match='CONFIRMATION_INVALID'):
        supervisor.apply(config.source_instance,result['confirmation_token'],actor_id=actor)


@pytest.mark.parametrize('items',[[],[{'action':'NO_CHANGE'}],[{'action':'UNSUPPORTED'}]])
def test_empty_manual_plan_cannot_issue_confirmation(monkeypatch,items):
    config=sample_source_config()
    supervisor=ApplySupervisor('','','','','','','')
    monkeypatch.setattr(supervisor,'_source',lambda _:config)
    monkeypatch.setattr(supervisor,'_payload',lambda *_:{})
    monkeypatch.setattr(supervisor,'_child',lambda _:dict(apply_allowed=True,digest='a'*64,
        planner_version='v',source_fingerprint='s',target_fingerprint='t',items=items))
    with pytest.raises(ApplyWorkerError,match='PLAN_BLOCKED'):
        supervisor.prepare(config.source_instance,'a'*64)


def test_used_plan_is_refused_before_prepare_child(monkeypatch):
    from contextlib import nullcontext
    supervisor = ApplySupervisor('', '', '', '', '', '', '')
    supervisor.operations = SimpleNamespace(review_guard=lambda *args: nullcontext({}),
                                           plan_time=lambda *args: '2026-09-17')
    supervisor._runs = SimpleNamespace(plan_used=lambda *args: True, reconciliation_required=lambda _:False)
    monkeypatch.setattr(supervisor, '_child', lambda *args: pytest.fail('must not re-execute'))
    with pytest.raises(ApplyWorkerError, match='PLAN_STALE') as caught:
        supervisor.prepare('pve-test', 'a'*64, 'operation')
    assert caught.value.reason == 'OPERATION_STATUS'


def test_child_failure_contains_safe_http_details_without_response(monkeypatch):
    import requests
    from pynetbox.core.query import RequestError
    from netbox_sync.apply_worker import _failure
    from netbox_sync.worker_failure import safe_diagnostic
    response = requests.Response()
    response.status_code = 400
    response._content = b'RAW_PASSWORD_AND_INFRASTRUCTURE'
    response.request = requests.Request('POST','https://secret-host/api/ipam/ip-addresses/',
                                       headers={'Authorization':'SECRET'}).prepare()
    response.url = response.request.url
    try:
        raise RequestError(response)
    except RequestError as exc:
        value = safe_diagnostic(_failure(exc, 'apply'), 'OUTCOME_UNCERTAIN')
    assert value['exception_class'] == 'RequestError'
    assert value['phase'] == 'apply'
    assert value['http'] == {'status':400,'method':'POST','endpoint':'ipam.ip_addresses'}
    assert 'SECRET' not in json.dumps(value) and 'secret-host' not in json.dumps(value)


@pytest.mark.skipif(sys.platform != 'linux', reason='real Unix peer credentials require Linux')
@pytest.mark.parametrize('fail', [False, True])
def test_disconnected_recipient_does_not_kill_real_apply_server(tmp_path, fail):
    import multiprocessing
    import os
    import socket
    import time
    from netbox_sync.apply_worker import serve
    path = str(tmp_path / 'apply.sock')
    class Supervisor:
        def apply(self, *args, **kwargs):
            time.sleep(.1)
            if fail: raise RuntimeError('PRIVATE_REMOTE_RESPONSE_MUST_NOT_APPEAR')
            return {'status':'SUCCEEDED','plan_digest':'a'*64}
    process = multiprocessing.get_context('fork').Process(target=serve,args=(path,Supervisor(),os.getuid()))
    process.start()
    try:
        deadline = time.monotonic()+5
        while not os.path.exists(path) and time.monotonic()<deadline: time.sleep(.01)
        with socket.socket(socket.AF_UNIX) as connection:
            connection.connect(path)
            connection.sendall(json.dumps({'operation':'apply','source_instance':'pve-test',
                'confirmation_token':'b'*64}).encode())
            connection.shutdown(socket.SHUT_WR)
        time.sleep(.2)
        if fail:
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(2)
                connection.connect(path)
                connection.sendall(json.dumps({'operation':'apply','source_instance':'pve-test',
                    'confirmation_token':'b'*64}).encode())
                connection.shutdown(socket.SHUT_WR)
                response=json.loads(connection.recv(4096))
                assert response['error']=='WORKER_INTERNAL_ERROR'
                UUID(response['event_id'])
                assert 'PRIVATE_REMOTE_RESPONSE_MUST_NOT_APPEAR' not in json.dumps(response)
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(2)
            connection.connect(path)
            connection.sendall(b'{"operation":"health"}')
            connection.shutdown(socket.SHUT_WR)
            assert json.loads(connection.recv(4096)) == {'ok':True,'result':{'status':'ok'}}
        assert process.is_alive()
    finally:
        process.terminate()
        process.join(5)


def test_previous_uncertain_outcome_blocks_prepare_before_child(monkeypatch):
    supervisor=ApplySupervisor('', '', '', '', '', '', '/unused')
    supervisor._runs=SimpleNamespace(reconciliation_required=lambda _:True)
    supervisor._child=lambda _:pytest.fail('No child or NetBox write allowed')
    with pytest.raises(ApplyWorkerError,match='PLAN_BLOCKED'):
        supervisor.prepare('pve-test','a'*64)


def test_uncertain_outcome_arriving_after_prepare_blocks_apply_under_lock(monkeypatch):
    supervisor, token, recorder = _manual_supervisor(
        monkeypatch, lambda _: pytest.fail('No child or NetBox write allowed'))
    acquired=[]
    sys.modules['fcntl'].flock=lambda *args: acquired.append(args)
    def blocked(_):
        assert acquired, 'History must be checked under the shared apply lock'
        return True
    recorder.reconciliation_required=blocked
    with pytest.raises(ApplyWorkerError, match='PLAN_BLOCKED'):
        supervisor.apply('pve-infra-test', token)
    assert recorder.finished[0]['status'] is RunStatus.BLOCKED
    assert recorder.finished[0]['error_code']=='PLAN_BLOCKED'
    with pytest.raises(ApplyWorkerError, match='CONFIRMATION_INVALID'):
        supervisor.apply('pve-infra-test', token)
