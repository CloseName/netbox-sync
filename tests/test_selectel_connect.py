"""First collection is explicit, replayable and isolated between connections."""
from copy import deepcopy
from uuid import uuid4
from unittest.mock import patch
import pytest
from netbox_sync import selectel_control as control
from netbox_sync import selectel_lifecycle_control as lifecycle
from tests.test_selectel_lifecycle_control import env, data


def request(generation=None):
    return dict(account='29916', name='Test', username='reader', password='PRIVATE',
                request_id=str(uuid4()), connection_generation=generation)


def connect(env, value):
    store, path, saved, _, _ = env
    store.root = path.parent
    return control._handle_account(store, 'lock', path.parent, 'connect', value)


def test_connect_runs_once_even_after_completion_and_lost_response(env):
    store, path, saved, _, _ = env
    saved[path] = {}
    value = request()
    with patch.object(control.subprocess, 'Popen') as start:
        start.return_value.pid = 123
        result = connect(env, value)
        assert result['status'] == 'running' and result['schedule'] == {'kind':'off'}
        assert result['next_run'] is None and result['enabled'] is True
        assert 'PRIVATE' not in str(result)
        assert connect(env, value)['run_id'] == result['run_id']
        saved[path].update(status='completed')
        assert connect(env, value)['run_id'] == result['run_id']
        assert start.call_count == 1
        assert connect(env, request())['error'] == 'ACCOUNT_ALREADY_CONNECTED'


def test_delete_reactivate_connect_can_repeat_without_old_form_replay(env):
    store, path, saved, calls, answers = env
    stale = request()
    for _ in range(3):
        saved[path]['enabled'] = False
        answers.append({'writes_performed':True})
        lifecycle.handle(store, 'lock', 'lifecycle-execute', data())
        assert 'password' not in saved[path]
        assert connect(env, stale)['error'] == 'ACCOUNT_DELETED'
        answers.append({'writes_performed':True})
        activation = {**data(), 'operation':'activate'}
        lifecycle.handle(store, 'lock', 'lifecycle-execute', activation)
        generation = saved[path]['connection_generation']
        assert connect(env, stale)['error'] == 'CONNECTION_REVIEW_STALE'
        stale = request(generation)
        with patch.object(control.subprocess, 'Popen') as start:
            start.return_value.pid = 123
            assert connect(env, stale)['status'] == 'running'
        saved[path].update(status='completed')


@pytest.mark.parametrize('error', ['IMPORT_UNCONFIRMED','RUN_INTERRUPTED'])
def test_uncertainty_cannot_be_cleared_by_delete_or_connect(env, error):
    store, path, saved, calls, _ = env
    saved[path].update(error=error)
    before = deepcopy(saved)
    assert connect(env, request())['error'] == 'IMPORT_UNCONFIRMED'
    assert lifecycle.handle(store, 'lock', 'lifecycle-execute', data())['error'] == 'IMPORT_UNCONFIRMED'
    assert saved == before and not calls


def test_first_collection_busy_does_not_save_credentials(env, monkeypatch):
    _, path, saved, _, _ = env
    saved[path] = {}
    other = path.parent / '435835.json'; other.touch()
    saved[other] = {'status':'running'}
    monkeypatch.setattr(control, 'running', lambda state: state.get('status') == 'running')
    assert connect(env, request())['error'] == 'COLLECTION_BUSY'
    assert saved[path] == {}
