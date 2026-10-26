"""Point provider reads must not expose identifiers or invoke import."""
import json
import pytest
from deploy import selectel_hardware_probe as probe
from tools.selectel_audit.client import AuditError

RESOURCE = 'b35f4e5e-9f52-4377-8ed9-79c35979169f'


@pytest.mark.parametrize('value,reason', [
    (None, 'null'), (123, 'wrong_type'), (' ', 'empty'), ('unknown', 'placeholder'),
    ('000-000', 'placeholder_pattern'), ('x' * 257, 'too_long'),
    ('ab\x00cd', 'nonprintable'), ('PRIVATE-SERIAL', 'valid_format'),
])
def test_reason_without_value(value, reason):
    assert probe.field_state('service_tag', value) == reason


def test_shapes_and_sanitization_do_not_leak_values_or_arbitrary_keys():
    raw = {'service_tag': 123456, 'serial': 'PRIVATE-SERIAL',
           'system': {'serial_number': 'PRIVATE-ALIAS'},
           'config': {'disk': [{'serial': 'PRIVATE-DISK'}]},
           'PRIVATE-KEY': 'PRIVATE-VALUE', 'password': 'PRIVATE-PASSWORD'}
    evidence = probe.project(raw, ['PRIVATE-SERIAL'])
    text = json.dumps(evidence)
    assert 'PRIVATE' not in text
    assert evidence['root_fields']['service_tag']['raw'] == 'wrong_type'
    assert evidence['root_fields']['serial']['sanitization_changed'] is True
    assert evidence['candidate_paths']['system.serial_number'] == ['valid_format']
    assert evidence['candidate_paths']['config.disk[].serial'] == ['valid_format']


class FakeClient:
    def __init__(self, bad_scope=False):
        self.urls = []
        self.bad_scope = bad_scope
    def request(self, url, token='', **kwargs):
        self.urls.append(url)
        if url.endswith('/auth/tokens'):
            assert kwargs['payload']['auth']['scope'] == {'domain': {'name': '29916'}}
            return {'token': {'domain': {'name': 'other' if self.bad_scope else '29916', 'id': 'domain'}}}, 'PRIVATE-TOKEN'
        assert not kwargs
        if '/resource?' in url:
            return {'result': [{'uuid': RESOURCE, 'service_type': 'server'}]}, ''
        if url.endswith('/info/server'):
            return {'result': {'service_tag': 'unknown'}}, ''
        assert url.endswith('/resource/' + RESOURCE)
        return {'result': {'serial': 'PRIVATE-SERIAL'}}, ''


def test_only_auth_listing_and_selected_metadata_are_requested():
    client = FakeClient()
    result = probe.collect('29916', RESOURCE, 'user', 'PRIVATE-PASSWORD', client)
    assert result['writes_performed'] is False
    assert len(client.urls) == 4
    assert 'PRIVATE' not in json.dumps(result)
    assert result['sections']['hardware']['root_fields']['service_tag']['raw'] == 'placeholder'


def test_wrong_scope_stops_before_resource_reads():
    client = FakeClient(bad_scope=True)
    with pytest.raises(AuditError):
        probe.collect('29916', RESOURCE, 'user', 'pw', client)
    assert len(client.urls) == 1


def test_invalid_selection_never_executes_container():
    with pytest.raises(ValueError):
        probe.report(lambda *args: pytest.fail('No execution'), '../29916', RESOURCE)


@pytest.mark.parametrize('active', [False, True])
def test_private_state_read_then_privilege_drop_and_no_writes(monkeypatch, capsys, active):
    import stat
    from types import SimpleNamespace
    from netbox_sync import selectel_control, discovery_worker
    calls = []
    class PrivatePath:
        def __init__(self, *args):
            pass
        def __truediv__(self, value):
            return self
        def lstat(self):
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=0)
    monkeypatch.setattr(probe, 'Path', PrivatePath)
    state = {'account': '29916', 'username': 'PRIVATE-USER', 'password': 'PRIVATE-PASSWORD',
             'status': 'running' if active else 'attention'}
    before = dict(state)
    monkeypatch.setattr(selectel_control, 'read', lambda path: calls.append('read') or state)
    monkeypatch.setattr(selectel_control, 'write', lambda *args: pytest.fail('No state writes'))
    monkeypatch.setattr(selectel_control, 'root', lambda *args: pytest.fail('No directory creation'))
    monkeypatch.setattr(discovery_worker, '_drop_privileges',
                        lambda uid, gid: lambda: calls.append(('drop', uid, gid)))
    def collect(*args):
        assert calls == ['read', ('drop', 10001, 10001)]
        calls.append('network')
        raise RuntimeError('PRIVATE-EXCEPTION WITH TOKEN')
    monkeypatch.setattr(probe, 'collect', collect)
    probe.container_main('29916', RESOURCE)
    output = capsys.readouterr().out
    assert 'PRIVATE' not in output
    assert 'PROBE_FAILED' in output
    assert state == before
    assert calls == (['read'] if active else ['read', ('drop', 10001, 10001), 'network'])


def test_reviewed_source_execution_uses_explicit_argument_without_secrets():
    def run(*args):
        assert args[:7] == ('docker', 'exec', 'netbox-sync-bootstrap-worker', 'python', '-B', '-c', args[6])
        assert args[6].endswith("container_main('29916', '" + RESOURCE + "')\n")
        return probe.MARKER + json.dumps({'account': '29916', 'resource': RESOURCE, 'writes_performed': False})
    assert probe.report(run, '29916', RESOURCE)['writes_performed'] is False
