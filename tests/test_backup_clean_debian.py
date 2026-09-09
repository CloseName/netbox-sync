"""Opt-in clean Debian host rehearsal, including actual systemd (not a test double).
Requires local Docker Linux Engine and the tests/Dockerfile.backup-host image.
Only the disposable OPERATOR HOST harness gets Docker access/privileges for systemd;
production app containers use unchanged 6639c38 production Compose boundaries.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
OLD = '6639c38b7b9fcf535624e06ecf91fa0ac7db3d6b'


def docker(*args, check=True):
    return subprocess.run(['docker', *args], capture_output=True, text=True, check=check)


@pytest.mark.skipif(os.environ.get('NETBOX_SYNC_CLEAN_BACKUP_TEST') != '1',
                    reason='explicit disposable privileged Debian host test opt-in required')
def test_clean_debian_old_release_backup():
    project = 'netbox-sync-backup-host-' + uuid.uuid4().hex[:10]
    host, volume, image = project + '-host', project + '-files', project + ':old'
    label = 'netbox-sync.test=' + project
    created_host = False
    docker('volume', 'create', '--label', label, volume)
    mountpoint = docker('volume', 'inspect', volume, '--format', '{{.Mountpoint}}').stdout.strip()
    root = mountpoint + '/netbox-sync-test'
    try:
        docker('run', '-d', '--name', host, '--label', label, '--privileged',
               '--cgroupns', 'private', '--tmpfs', '/run', '--tmpfs', '/run/lock',
               '--mount', 'type=volume,source=' + volume + ',target=' + mountpoint,
               '--mount', 'type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock',
               '--mount', 'type=bind,source=' + str(ROOT) + ',target=/review,readonly',
               'netbox-sync-backup-host:review', '/lib/systemd/systemd')
        created_host = True
        for _ in range(60):
            status = docker('exec', host, 'systemctl', 'is-system-running', check=False)
            if status.stdout.strip() in ('running', 'degraded'):
                break
            time.sleep(1)
        else:
            pytest.fail('Disposable Debian systemd did not boot')
        with tempfile.TemporaryDirectory(prefix='netbox-sync-old-archive-') as directory:
            archive = Path(directory) / 'old.tar'
            subprocess.run(['git', 'archive', '--format=tar', '-o', str(archive), OLD],
                           cwd=ROOT, check=True)
            docker('cp', str(archive), host + ':/old.tar')
        docker('exec', host, 'mkdir', '/old-source')
        docker('exec', host, 'tar', '-xf', '/old.tar', '-C', '/old-source')
        result = docker('exec', host, 'python3', '/review/tests/backup_clean_host_scenario.py',
                        root, project, image, check=False)
        assert result.returncode == 0, result.stdout[-6000:] + result.stderr[-6000:]
        print(result.stdout[-1500:])
    finally:
        # Bound cleanup by the unique project/host labels created by this test.
        for kind, listing in [('container', ('ps', '-aq')), ('network', ('network', 'ls', '-q')),
                              ('volume', ('volume', 'ls', '-q'))]:
            ids = docker(*listing, '--filter', 'label=com.docker.compose.project=' + project).stdout.split()
            for identifier in ids:
                if kind == 'container':
                    docker('rm', '-f', identifier, check=False)
                else:
                    docker(kind, 'rm', identifier, check=False)
        if created_host:
            docker('rm', '-f', host)
        docker('volume', 'rm', project + '-db', check=False)
        docker('volume', 'rm', volume)
        docker('image', 'rm', image, check=False)


@pytest.mark.skipif(os.environ.get('NETBOX_SYNC_CLEAN_BACKUP_TEST') != '1',
                    reason='explicit clean Debian host test opt-in required')
def test_clean_debian_optional_libpq_venv():
    result = docker('run', '--rm', '--mount',
                    'type=bind,source=' + str(ROOT) + ',target=/review,readonly',
                    'netbox-sync-backup-host:review', 'python3',
                    '/review/tests/backup_optional_host_scenario.py', check=False)
    assert result.returncode == 0, result.stderr
    assert 'PASS: isolated optional libpq' in result.stdout
