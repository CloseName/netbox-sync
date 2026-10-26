"""Resolved Compose hashes must include env files without exposing their values."""
import subprocess

import pytest

from deploy import guard_config_hash as hashes


def test_resolved_model_is_private_explicit_stdin(monkeypatch):
    document = '{"services":{"netbox":{"environment":{"PRIVATE":"a$$b"}}}}'
    def run(command, **kwargs):
        assert command == ['docker', 'compose', '--project-directory', '/netbox-test',
                           '-p', 'netbox-test', '-f', '-', 'config', '--hash', '*']
        assert kwargs['input'] == document
        assert kwargs['stdout'] == subprocess.PIPE and kwargs['stderr'] == subprocess.PIPE
        return subprocess.CompletedProcess(command, 0, 'netbox ' + 'a'*64 + '\n')
    monkeypatch.setattr(subprocess, 'run', run)
    assert hashes.resolved_hashes('/netbox-test', 'netbox-test', document) == {'netbox': 'a'*64}


@pytest.mark.parametrize('output', ['private-output', 'netbox invalid',
                                  'netbox ' + 'a'*64 + '\nnetbox ' + 'b'*64])
def test_invalid_output_is_closed(monkeypatch, output):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, output))
    with pytest.raises(ValueError, match='Invalid Compose hash output'):
        hashes.resolved_hashes('/netbox-test', 'netbox-test', '{}')
