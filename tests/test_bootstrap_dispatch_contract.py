"""Exact bootstrap envelopes and lock/callback ordering without sockets or providers."""
from contextlib import contextmanager
from types import SimpleNamespace
import pytest
from netbox_sync import bootstrap_worker as module
from netbox_sync.local_control import ControlError


@pytest.fixture
def control(monkeypatch):
    calls = []
    def callback(name):
        def invoke(*args, **kwargs):
            calls.append((name, args, kwargs))
            return {'handled': name}
        return invoke
    store = SimpleNamespace(status=callback('status'), configure=callback('configure'),
                            validate=callback('validate'), finish=callback('finish'))
    @contextmanager
    def locked(path):
        calls.append(('lock', (path,), {}))
        try:
            yield
        finally:
            calls.append(('unlock', (path,), {}))
    monkeypatch.setattr(module, 'apply_lock', locked)
    monkeypatch.setattr(module, 'Preparation', lambda selected: SimpleNamespace(
        plan=callback('plan'), cancel=callback('cancel'), apply=callback('apply')))
    probe = object()
    return module.BootstrapControl(store, '/fixture/lock', probe), calls, probe


@pytest.mark.parametrize('action,extra,target,locked', [
    ('status', {}, 'status', False),
    ('prerequisites-plan', {'revision': 4}, 'plan', False),
    ('prerequisites-cancel', {'revision': 4}, 'cancel', False),
    ('prerequisites-apply', {'revision': 4, 'digest': 'd', 'confirm': True, 'setup_token': 'fixture'}, 'apply', True),
    ('configure', {'revision': 4, 'extra': 'forwarded'}, 'configure', True),
    ('validate', {'revision': 4}, 'validate', False),
    ('finish', {'revision': 4}, 'finish', True),
])
def test_bootstrap_dispatch_preserves_arguments_and_lock_scope(control, action, extra, target, locked):
    service, calls, probe = control
    payload = {'action': action, **extra}
    assert service(payload) == {'handled': target}
    assert [name for name, _, _ in calls] == (['lock', target, 'unlock'] if locked else [target])
    selected = calls[1 if locked else 0]
    expected = () if target == 'status' else (payload,) if target in ('apply', 'configure') else (4, probe) if target == 'validate' else (4,)
    assert selected[1] == expected and selected[2] == {}


@pytest.mark.parametrize('payload', [
    {'action': 'health', 'extra': True}, {'action': 'status', 'extra': True},
    {'action': 'validate'}, {'action': 'finish', 'revision': 1, 'extra': True},
    {'action': 'prerequisites-plan'}, {'action': 'prerequisites-cancel', 'revision': 1, 'extra': True},
    {'action': 'prerequisites-apply', 'revision': 1}, {'action': 'namespace-check'},
    {'action': 'catalog', 'query': {}, 'extra': True}, {'action': 'catalog-prepare', 'query': {}, 'extra': True},
    {'action': 'unknown'}, {'action': []},
])
def test_bootstrap_invalid_envelope_never_reaches_store_or_lock(control, payload):
    service, calls, _ = control
    with pytest.raises(ControlError, match='BOOTSTRAP_INVALID'):
        service(payload)
    assert calls == []


def test_bootstrap_health_is_exact_and_does_not_read_store(control):
    service, calls, _ = control
    assert service({'action': 'health'}) == {'status': 'ok'}
    assert calls == []

@pytest.mark.parametrize('busy_slots', [0, 3, 4])
def test_catalog_read_slots_are_independent_and_always_closed(control, monkeypatch, busy_slots):
    import json
    import sys
    from netbox_sync import bootstrap_state
    service, calls, _ = control
    service.store.path = '/fixture/state'
    opened, closed, executed = [], [], []
    def open_slot(path, flags, mode):
        opened.append(path)
        assert mode == 0o600
        return len(opened)
    def flock(fd, flags):
        if fd <= busy_slots:
            raise BlockingIOError()
    monkeypatch.setitem(sys.modules, 'fcntl', SimpleNamespace(flock=flock, LOCK_EX=1, LOCK_NB=2))
    monkeypatch.setattr(module.os, 'O_NOFOLLOW', 0, raising=False)
    monkeypatch.setattr(module.os, 'open', open_slot)
    monkeypatch.setattr(module.os, 'close', closed.append)
    monkeypatch.setattr(bootstrap_state, 'runtime_netbox', lambda *args: ('https://fixture.test', 'read-fixture'))
    monkeypatch.setattr(module, '_safe_environment', lambda: {})
    monkeypatch.setattr(module, '_drop_privileges', lambda *args: None)
    def run(command, **kwargs):
        executed.append((command, kwargs))
        assert kwargs['timeout'] == 30
        assert json.loads(kwargs['input']) == {'url': 'https://fixture.test', 'read_token': 'read-fixture', 'query': {'action': 'scopes'}}
        return SimpleNamespace(stdout=b'{"catalog": true}')
    monkeypatch.setattr(module.subprocess, 'run', run)
    result = service({'action': 'catalog', 'query': {'action': 'scopes'}})
    assert result == ({'error': 'BUSY'} if busy_slots == 4 else {'catalog': True})
    assert len(opened) == min(busy_slots + 1, 4)
    assert closed == list(range(1, len(opened) + 1))
    assert len(executed) == (0 if busy_slots == 4 else 1)
    assert calls == []


@pytest.mark.parametrize('with_source', [False, True])
@pytest.mark.parametrize('outcome', ['own', 'foreign', 'error'])
def test_registration_cluster_preserves_intent_binding_and_lock(control, monkeypatch, with_source, outcome):
    from netbox_sync import catalog_creation
    from netbox_sync.bootstrap_probe import ProbeError
    service, calls, _ = control
    seen = []
    class Catalog:
        def __init__(self, store):
            assert store is service.store
        def execute(self, payload, **kwargs):
            seen.append((payload, kwargs))
            if outcome == 'error':
                raise ProbeError('PERMISSION_DENIED')
            return {'operation_id': 'requested' if outcome == 'own' else 'other', 'item': {'id': 7}}
    monkeypatch.setattr(catalog_creation, 'CatalogCreation', Catalog)
    payload = {'action': 'registration-cluster', 'operation_id': 'requested',
               'name': 'Cluster', 'site_id': 2, 'cluster_type_id': 3}
    if with_source:
        payload['source_instance'] = 'source-a'
    result = service(payload)
    expected = {'error': 'PERMISSION_DENIED'} if outcome == 'error' else (
        {'status': 'EXISTS_REVIEW_REQUIRED', 'item': {'id': 7}} if outcome == 'foreign' else
        {'operation_id': 'requested', 'item': {'id': 7}})
    assert result == expected
    assert [name for name, _, _ in calls] == ['lock', 'unlock']
    assert seen == [({'action': 'catalog-create', 'operation_id': 'requested', 'kind': 'cluster',
                     'object': {'name': 'Cluster', 'type': 3, 'scope_type': 'dcim.site', 'scope_id': 2},
                     'confirm': True}, {'registration': True, 'source_instance': payload.get('source_instance')})]
