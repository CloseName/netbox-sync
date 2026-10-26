"""Existing-run diagnosis must not expose logs or repeat writes."""
import json
import pytest
from deploy import selectel_run_evidence as evidence


def test_log_projection_never_returns_private_text():
    report = evidence.project_logs('POST /api/plugins/netbox-sync-guard/providers/account-import/ HTTP/1.1" 500 123\n'
        'django.db.utils.IntegrityError: password=PRIVATE\n[CRITICAL] WORKER TIMEOUT pid=123\n')
    assert report['import_http_statuses'] == {'500': 1}
    assert report['exception_classes'] == ['IntegrityError']
    assert report['worker_timeout_seen'] is True
    assert 'PRIVATE' not in json.dumps(report)


def test_report_uses_existing_run_only(tmp_path, monkeypatch):
    folder = tmp_path / 'secrets/netbox/selectel'
    folder.mkdir(parents=True)
    nonce = '08cd3347-a976-4dd9-a043-f4d591796e30'
    path = folder / '29916.json'
    original = json.dumps({'run_id': nonce, 'started_at': 1793032200, 'finished_at': 1793032864,
                          'error': 'IMPORT_UNCONFIRMED', 'password': 'PRIVATE', 'import_digest': 'a'*64})
    path.write_text(original)
    calls = []
    monkeypatch.setattr(evidence, 'read_logs', lambda name, since, until: calls.append((name, since, until)) or {})
    result = evidence.report(tmp_path, '29916', nonce)
    assert result['import_intent_present'] is True
    assert len(calls) == 3
    assert path.read_text() == original
    assert 'PRIVATE' not in json.dumps(result)


@pytest.mark.parametrize('account,nonce', [('../private', 'bad'), ('29916', 'bad')])
def test_invalid_selection_cannot_read_paths(tmp_path, account, nonce):
    with pytest.raises(ValueError):
        evidence.report(tmp_path, account, nonce)


def test_unrelated_logs_do_not_claim_import_error():
    result = evidence.project_logs('GET /other HTTP/1.1" 500\npassword=private\n')
    assert result['import_http_statuses'] == {}
    assert result['exception_classes'] == []


def test_logs_are_read_only_private_and_bounded(monkeypatch):
    from types import SimpleNamespace
    import subprocess
    def run(command, **kwargs):
        assert command == ['docker', 'logs', '--since', 'start', '--until', 'end', '--tail', '500', 'netbox']
        assert kwargs['stdin'] == subprocess.DEVNULL
        assert kwargs['stdout'] is kwargs['stderr']
        kwargs['stdout'].write(b'IntegrityError: PRIVATE\n')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, 'run', run)
    result = evidence.read_logs('netbox', 'start', 'end')
    assert result['exception_classes'] == ['IntegrityError']
    assert 'PRIVATE' not in json.dumps(result)
