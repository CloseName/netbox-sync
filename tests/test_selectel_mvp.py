import json
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from netbox_sync.api.selectel import Account, routes
from netbox_sync.api.auth import permission
from netbox_sync.selectel_control import public
from netbox_sync.selectel_collect import summary
from tests.selectel_inventory_fixture import fixture
import os


def test_admin_boundary_and_secret_projection():
    for method, path in [('GET', '/api/v1/selectel'), ('POST', '/api/v1/selectel'),
                         ('POST', '/api/v1/selectel/29916/collect'),
                         ('POST', '/api/v1/selectel/29916/schedule'),
                         ('POST', '/api/v1/selectel/29916/lifecycle-review'),
                         ('POST', '/api/v1/selectel/29916/lifecycle-execute'),
                         ('POST', '/api/v1/selectel/29916/enabled')]:
        assert permission(method, path) == 'bootstrap.manage'
    assert permission('POST', '/api/v1/selectel/../../collect') == 'unmapped.deny'
    state = dict(account='29916', password='SECRET', token='SECRET', pid=123, name='test', status='configured')
    assert 'SECRET' not in json.dumps(public(state)) and 'pid' not in public(state)
    assert 'SECRET' not in repr(Account(account='29916', name='test', username='reader', password='SECRET'))
    with pytest.raises(ValueError): Account(account='../bad', name='test', username='reader', password='SECRET')


def test_api_forwards_secret_once_and_returns_only_control_result():
    app = FastAPI(); app.include_router(routes(SimpleNamespace(bootstrap_socket='/unused')))
    with patch('netbox_sync.api.selectel.control', return_value={'result': {'account': '29916', 'status': 'configured'}}) as rpc:
        response = TestClient(app).post('/api/v1/selectel', json=dict(account='29916', name='test', username='reader', password='SECRET'))
        assert response.status_code == 200 and 'SECRET' not in response.text
        assert rpc.call_args.args[1]['data']['password'] == 'SECRET'
        assert response.headers['cache-control'] == 'no-store'


def test_summary_does_not_expose_raw_resource_payloads():
    document = fixture('29916'); document['coverage'] = []; document['projects'] = []
    result = summary(document)
    assert len(result['products']) > 4
    assert 'never-export' not in json.dumps(result)
    assert all('scopes' not in p for p in result['products'])


def test_schedule_and_disable_forward_only_admin_operation():
    app = FastAPI(); app.include_router(routes(SimpleNamespace(bootstrap_socket='/unused')))
    client = TestClient(app)
    with patch('netbox_sync.api.selectel.control', return_value={'result': {'account':'29916'}}) as rpc:
        assert client.post('/api/v1/selectel/29916/enabled', json={'enabled':False}).status_code == 200
        assert rpc.call_args.args[1]['operation'] == 'enabled'
        assert rpc.call_args.args[1]['data'] == {'account':'29916','enabled':False}
        assert client.post('/api/v1/selectel/29916/enabled', json={'enabled':'false'}).status_code == 422
        assert client.post('/api/v1/selectel/29916/schedule', json={'schedule':{'kind':'off'}}).status_code == 200
        assert rpc.call_args.args[1]['operation'] == 'schedule'


def test_control_checks_admin_before_touching_storage():
    from netbox_sync.selectel_control import handle
    from netbox_sync.auth_policy import AuthError
    with patch('netbox_sync.api.auth.AuthClient.call', side_effect=AuthError('AUTH_DENIED')):
        with pytest.raises(AuthError):
            handle(None, '/unused', dict(action='selectel', operation='list', session='bad', data={}))


def test_lifecycle_transport_rejects_unreviewed_payload():
    app = FastAPI(); app.include_router(routes(SimpleNamespace(bootstrap_socket='/unused')))
    client = TestClient(app)
    with patch('netbox_sync.api.selectel.control', return_value={'result': {'writes_performed':True}}) as rpc:
        assert client.post('/api/v1/selectel/29916/lifecycle-execute',json={'operation':'delete'}).status_code==422
        assert not rpc.called
        assert client.post('/api/v1/selectel/29916/lifecycle-execute',json={
            'operation':'delete','key':None,'fingerprint':'a'*64,'confirmed':True}).status_code==200
        assert rpc.call_args.args[1]['operation']=='lifecycle-execute'
        assert rpc.call_args.kwargs['timeout']==100


def test_disabling_running_account_preserves_job_and_schedule_validation(tmp_path):
    from copy import deepcopy
    from contextlib import nullcontext
    from netbox_sync.selectel_control import handle
    path = tmp_path/'29916.json'; path.touch()
    state = dict(account='29916',status='running',run_id='original',password='PRIVATE',
                 schedule={'kind':'off'})
    store = SimpleNamespace(locked=nullcontext, path=tmp_path/'config', root=tmp_path)
    def persist(_, value):
        state.clear(); state.update(deepcopy(value))
    with patch('netbox_sync.api.auth.AuthClient.call', return_value={}), \
         patch('netbox_sync.selectel_control.root', return_value=tmp_path), \
         patch('netbox_sync.selectel_control.runtime_netbox', return_value=('https://test','secret')), \
         patch('netbox_sync.selectel_control.read', side_effect=lambda _:deepcopy(state)), \
         patch('netbox_sync.selectel_control.write', side_effect=persist):
        def call(operation, **data):
            return handle(store,'/unused',dict(action='selectel',operation=operation,session='admin',
                                              data={'account':'29916',**data}))
        response = call('enabled', enabled=False)
        assert response['enabled'] is False and response['run_id'] == 'original'
        assert response['status'] == 'running' and 'PRIVATE' not in json.dumps(response)
        assert state['next_run'] is None
        before = deepcopy(state)
        assert call('schedule', schedule={'kind':'days','days':0})['error'] == 'SCHEDULE_INVALID'
        assert state == before
        assert call('schedule', schedule={'kind':'off'})['schedule'] == {'kind':'off'}


def test_runner_waits_for_launcher_lock_without_repeating_body():
    from contextlib import contextmanager
    from netbox_sync.selectel_runner import locked_store
    from netbox_sync.local_control import ControlError
    attempts = []
    @contextmanager
    def lock():
        attempts.append(1)
        if len(attempts) < 3:
            raise ControlError('BOOTSTRAP_BUSY')
        yield
    store = SimpleNamespace(locked=lock)
    with patch('netbox_sync.selectel_runner.time.sleep'):
        with pytest.raises(ControlError):
            with locked_store(store):
                raise ControlError('BOOTSTRAP_BUSY')
    assert len(attempts) == 3


@pytest.mark.skipif(os.name != 'posix' or getattr(os, 'geteuid', lambda: 1)() != 0, reason='root-owned Linux control')
def test_control_storage_and_double_click(tmp_path):
    from netbox_sync.bootstrap_state import BootstrapStore
    from netbox_sync.selectel_control import handle, write, read
    store = BootstrapStore(tmp_path); tmp_path.chmod(0o700)
    def call(operation, data):
        return handle(store, str(tmp_path/'apply.lock'), dict(action='selectel', operation=operation, session='session', data=data))
    with patch('netbox_sync.api.auth.AuthClient.call', return_value={}), \
         patch('netbox_sync.selectel_control.runtime_netbox', return_value=('https://netbox.test', 'private-token')), \
         patch('netbox_sync.selectel_control.subprocess.Popen', return_value=SimpleNamespace(pid=123)) as start:
        response = call('save', dict(account='29916', name='Example', username='reader', password='SECRET'))
        assert 'SECRET' not in json.dumps(response) and not start.called
        secret = tmp_path/'selectel'/'29916.json'
        assert secret.stat().st_mode & 0o777 == 0o600
        assert read(secret)['password'] == 'SECRET'
        write(tmp_path/'selectel'/'netbox-token.json', {'token': 'PRIVATE'})
        assert call('collect', {'account':'29916'})['status'] == 'running'
        assert call('collect', {'account':'29916'})['error'] == 'RUN_ACTIVE'
        assert start.call_count == 1
        assert 'SECRET' not in repr(start.call_args) and 'PRIVATE' not in repr(start.call_args)
        assert 'SECRET' not in json.dumps(call('list', {}))
