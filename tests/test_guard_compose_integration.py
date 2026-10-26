"""Opt-in disposable Docker regression; never uses a NetBox installation."""
import json
import os
import subprocess
import uuid

import pytest

from deploy.guard_config_hash import resolved_hashes

pytestmark = pytest.mark.skipif(os.environ.get('GUARD_COMPOSE_TEST') != '1', reason='Disposable Docker opt-in')


def test_resolved_hash_matches_created_container_and_detects_drift(tmp_path):
    project = 'guard-hash-' + uuid.uuid4().hex[:12]
    env = tmp_path / 'service.env'
    env.write_text("PRIVATE='literal$a$$b'\nEMPTY=\n", encoding='utf-8')
    model = {'services': {'probe': {
        'image': 'alpine:3.21', 'command': ['sleep', '60'],
        'env_file': [str(env)], 'environment': {'INLINE': 'inline$$literal'},
        'restart': 'unless-stopped',
    }}}
    path = tmp_path / 'compose.json'
    path.write_text(json.dumps(model), encoding='utf-8')
    command = ['docker', 'compose', '--project-directory', str(tmp_path), '-p', project, '-f', str(path)]
    def run(*args):
        return subprocess.run(args, text=True, stdin=subprocess.DEVNULL, capture_output=True,
                              check=True, timeout=120).stdout.strip()
    def hashes():
        return resolved_hashes(tmp_path, project, run(*command, 'config', '--format', 'json'))
    try:
        run(*command, 'create', 'probe')
        cid = run(*command, 'ps', '--all', '-q', 'probe')
        container = json.loads(run('docker', 'inspect', cid))[0]
        expected = container['Config']['Labels']['com.docker.compose.config-hash']
        assert hashes()['probe'] == expected
        assert 'PRIVATE=literal$a$$b' in container['Config']['Env']
        env.write_text("PRIVATE='changed'\nEMPTY=\n", encoding='utf-8')
        assert hashes()['probe'] != expected
        env.write_text("PRIVATE='literal$a$$b'\nEMPTY=\n", encoding='utf-8')
        model['services']['probe']['command'] = ['sleep', '61']
        path.write_text(json.dumps(model), encoding='utf-8')
        assert hashes()['probe'] != expected
    finally:
        run(*command, 'down')
