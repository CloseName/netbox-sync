"""Engine-level regression using production Compose plus the real external override."""
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.skipif(os.environ.get('NETBOX_SYNC_PROXY_COMPOSE_SMOKE') != '1',
                    reason='opt-in disposable production Compose proxy smoke')
def test_external_proxy_production_compose_starts_with_real_tmpfs(tmp_path):
    project = 'netbox-sync-proxy-smoke-' + uuid.uuid4().hex[:10]
    volume = project + '-ingress'
    environment = os.environ.copy()
    environment.update(NETBOX_SYNC_COMPOSE_PROJECT=project,
                       NETBOX_SYNC_POSTGRES_VOLUME=project + '-postgres',
                       NETBOX_SYNC_INGRESS_DIR='smoke-ingress',
                       NETBOX_SYNC_PUBLIC_HOST='sync.example.test')
    # Only supply a disposable Linux filesystem for the operator ingress directory.
    # No service property (especially tmpfs) is replaced by this fixture.
    fixture = tmp_path / 'volume.yml'
    fixture.write_text(json.dumps({'volumes': {'smoke-ingress': {'external': True, 'name': volume}}}))
    compose = ['docker', 'compose', '-p', project, '-f', str(ROOT / 'compose.production.yml'),
               '-f', str(ROOT / 'compose.external-ingress.yml'), '-f', str(fixture)]
    def run(command):
        result = subprocess.run(command, env=environment, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()
    run(['docker', 'volume', 'create', '--label', 'netbox-sync.proxy-smoke=' + project, volume])
    try:
        run(['docker', 'run', '--rm', '--network', 'none', '--volume', volume + ':/ingress',
             '--entrypoint', '/bin/sh', 'nginx:stable-alpine', '-ec',
             'chown 10001:10001 /ingress; chmod 0750 /ingress'])
        run(compose + ['up', '-d', '--no-deps', '--no-build', 'netbox-sync-proxy'])
        container = run(compose + ['ps', '-q', 'netbox-sync-proxy'])
        info = json.loads(run(['docker', 'inspect', container]))[0]
        host = info['HostConfig']
        assert host['Tmpfs'] == {'/tmp': 'size=64m,mode=1777'}
        assert host['ReadonlyRootfs'] and host['CapDrop'] == ['ALL']
        assert host['NetworkMode'] == 'none' and not host['PortBindings']
        for attempt in range(30):
            probe = subprocess.run(compose + ['exec', '-T', 'netbox-sync-proxy',
                'wget', '-q', '--spider', 'http://127.0.0.1:8081/health'], env=environment, capture_output=True)
            if probe.returncode == 0:break
            time.sleep(0.2)
        else:pytest.fail('production proxy did not reach its real health endpoint')
        assert run(compose + ['exec', '-T', 'netbox-sync-proxy', 'stat', '-c', '%a', '/tmp']) == '1777'
        run(compose + ['exec', '-T', 'netbox-sync-proxy', 'test', '-S', '/run/netbox-sync-ingress/upstream.sock'])
    finally:
        run(compose + ['down', '--volumes'])
        run(['docker', 'volume', 'rm', volume])
