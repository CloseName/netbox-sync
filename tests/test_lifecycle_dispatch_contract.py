"""Exact lifecycle envelopes and error boundaries, without storage or remote calls."""

from types import SimpleNamespace
import importlib

import pytest

from netbox_sync.lifecycle_protocol import handle_lifecycle
from netbox_sync.source_lifecycle import LifecycleError


BASE = {'source_instance': 'source-a'}
OP = {'operation_id': 'op', 'actor_id': 'admin'}
REV = 'a' * 64
CASES = [
    ('source_evidence', {'after': ''}, 'evidence'),
    ('source_lifecycle', BASE, 'read'),
    ('source_generations', BASE, 'generations'),
    ('registration_credentials', {**BASE, **OP}, 'verify_staged'),
    ('legacy_describe', BASE, 'describe'),
    ('legacy_status', {**BASE, 'actor': 'admin', 'operation': 'op'}, 'status'),
    ('legacy_confirm', {**BASE, 'actor': 'admin', 'operation': 'op', 'revision': 1,
                        'decision': 'isolate', 'reason': 'test', 'anchor': {}}, 'confirm'),
    ('run_reconciliation_review', {**BASE, 'operation_id': 'op'}, 'review'),
    ('run_reconciliation_confirm', {**BASE, **OP, 'digest': 'd', 'acknowledgements': []}, 'confirm'),
    ('removal_request', {**BASE, **OP, 'revision': REV, 'confirmed': True}, 'enqueue'),
    ('removal_status', {**BASE, **OP}, 'status'),
    ('retirement_archive_check', {**BASE, 'actor_id': 'admin'}, 'recheck'),
    ('retirement_context', {**BASE, 'actor_id': 'admin'}, 'retained_context'),
    ('retirement_review', {**BASE, **OP, 'revision': REV}, 'review'),
    ('retirement_archive_review', {**BASE, **OP, 'revision': REV}, 'review'),
    ('retirement_status', {**BASE, **OP}, 'status'),
    ('retirement_execute', {**BASE, **OP, 'digest': 'd', 'confirmed_source': 'source-a',
                            'remove_credentials': False}, 'execute'),
    ('retirement_resume', {**BASE, **OP, 'digest': 'd', 'confirmed_source': 'source-a',
                           'remove_credentials': False}, 'execute'),
    ('identity_describe', BASE, 'describe'),
    ('identity_confirm', {**BASE, 'actor_id': 'admin', 'revision': REV,
                          'discovery_id': 'd', 'proof': {}}, 'confirm'),
    ('recovery_inventory', {**BASE, 'operation_id': 'op'}, 'inventory'),
    ('recovery_records', BASE, 'records'),
    ('recovery_retired_evidence', {**BASE, 'operation_id': 'op'}, 'retired_evidence'),
    ('recovery_describe', {**BASE, 'actor_id': 'admin'}, 'describe'),
    ('recovery_prepare', {**BASE, **OP, 'revision': REV, 'proof': {}}, 'prepare'),
    ('recovery_credentials', {**BASE, **OP}, 'begin_credentials'),
    ('recovery_complete', {**BASE, **OP, 'proof': {}, 'metadata': {}}, 'complete'),
    ('recovery_abandon', {**BASE, **OP}, 'abandon_prepared'),
    ('recovery_status', {**BASE, **OP}, 'status'),
    ('read_placement', BASE, 'read_placement'),
    ('save_placement', {**BASE, 'revision': REV, 'discovery_id': '00000000-0000-0000-0000-000000000001',
                        'mapping': {}}, 'save_placement'),
    ('rename_source', {**BASE, 'revision': REV, 'name': 'new'}, 'rename'),
    ('remove_source', {**BASE, 'revision': REV, 'confirmed_source': 'source-a',
                       'remove_credentials': False}, 'remove'),
]


@pytest.fixture
def boundary(monkeypatch):
    calls = []

    def record(name):
        def invoke(*args, **kwargs):
            calls.append((name, args, kwargs))
            return {'method': name}
        return invoke

    service = SimpleNamespace(**{name: record(name) for _, _, name in CASES})
    service.remote = object()
    secrets = SimpleNamespace(verify_owned=record('verify_owned'), remove_owned=record('remove_owned'))
    for module, name in [
        ('legacy_admission', 'LegacyAdmission'), ('run_reconciliation', 'RunReconciliation'),
        ('removal_queue', 'RemovalQueue'), ('source_identity_verification', 'IdentityVerification'),
        ('source_recovery', 'Recovery'),
    ]:
        monkeypatch.setattr(importlib.import_module('netbox_sync.' + module), name, lambda *args: service)
    for module, name, label in [
        ('source_archive', 'generations', 'generations'), ('source_archive', 'recheck', 'recheck'),
        ('registration_jobs', 'verify_staged', 'verify_staged'),
        ('placement_control', 'read', 'read_placement'), ('placement_control', 'save', 'save_placement'),
    ]:
        monkeypatch.setattr(importlib.import_module('netbox_sync.' + module), name, record(label))
    return service, secrets, calls


@pytest.mark.parametrize('action,fields,method', CASES, ids=[row[0] for row in CASES])
def test_exact_envelope_routes_once(boundary, action, fields, method):
    service, secrets, calls = boundary
    result = handle_lifecycle(service, secrets, {'action': action, **fields},
                              None if action == 'remove_source' else service)
    assert result == {'method': method}
    assert len(calls) == 1 and calls[0][0] == method
    if action in ('retirement_archive_review', 'retirement_review'):
        assert calls[0][2] == {'archive': action == 'retirement_archive_review'}
    if action in ('retirement_execute', 'retirement_resume'):
        assert calls[0][2] == {'resume': action == 'retirement_resume'}
    if action == 'recovery_complete':
        assert calls[0][1][-1] is secrets.verify_owned
    if action == 'remove_source':
        assert calls[0][1][-1] is secrets.remove_owned


@pytest.mark.parametrize('action,fields,method', CASES, ids=[row[0] for row in CASES])
def test_extra_field_never_reaches_operation(boundary, action, fields, method):
    service, secrets, calls = boundary
    with pytest.raises(LifecycleError, match='^REQUEST_INVALID$'):
        handle_lifecycle(service, secrets, {'action': action, **fields, 'extra': True}, service)
    assert calls == []


@pytest.mark.parametrize('failure', [ValueError('private'), TypeError('private'), KeyError('private')])
def test_operation_value_errors_are_closed(boundary, failure):
    service, secrets, _ = boundary
    def fail(*args):
        raise failure
    service.read = fail
    with pytest.raises(LifecycleError) as caught:
        handle_lifecycle(service, secrets, {'action': 'source_lifecycle', **BASE})
    assert str(caught.value) == 'REQUEST_INVALID'
    assert caught.value.__suppress_context__


def test_retirement_requirement_precedes_actor_and_envelope_validation(boundary):
    service, secrets, calls = boundary
    with pytest.raises(LifecycleError, match='^RETIREMENT_UNAVAILABLE$'):
        handle_lifecycle(service, secrets, {'action': 'retirement_execute', **BASE})
    assert calls == []
