"""Run inside a disposable clean Debian operator host with REAL systemd + Docker CLI.
No pytest/application dependencies are installed in this interpreter.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tarfile
import time

OLD = '6639c38b7b9fcf535624e06ecf91fa0ac7db3d6b'
root, project, image = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
assert project.startswith('netbox-sync-backup-host-')
assert importlib.util.find_spec('psycopg') is None
assert importlib.util.find_spec('pytest') is None
assert importlib.util.find_spec('pynetbox') is None
sys.path.insert(0, '/old-source')
from deploy import install


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode:
        # Backup diagnostics are sanitized; fixture setup errors contain no secrets.
        raise RuntimeError('Command failed: ' + args[0] + '\n' + result.stderr[-3000:])
    return result.stdout


def cli(*args):
    return run(['python3', '/review/deploy/backup.py', '--root', str(root), *args])


# A full installed old release, built from its immutable Git archive.
install.initialize_tls_layout(root)
p = install.prepare_layout(root, Path('/old-source'), OLD, image)
install.configure_tls(p, 'https://netbox-sync-test.indeed-id.hq')
install.configure_ingress(p, 'external')
install.initialize_ingress_directory(root)
install._atomic_write(p.config / 'compose.env', install._merged_config(
    p.config / 'compose.env', {}, {'NETBOX_SYNC_COMPOSE_PROJECT': project,
                                  'NETBOX_SYNC_POSTGRES_VOLUME': project + '-db'}))
install.prepare_stack(p)
install.publish_configuration(p)
install.activate_release(root, p.release)
install.install_systemd(root, start=False)
# Real timer and real unit; postpone automatic fixture writes during assertions.
dropin = Path('/etc/systemd/system/netbox-sync.timer.d')
dropin.mkdir()
(dropin / 'test.conf').write_text('[Timer]\nOnBootSec=\nOnBootSec=24h\nOnUnitActiveSec=\nOnUnitActiveSec=24h\n')
run(['systemctl', 'daemon-reload'])
install.start_runtime(p)
run(['systemctl', 'start', 'netbox-sync.timer'])
command = install.compose_command(root)

# Reproduce the installed CLI failure before using the reviewed host fix.
broken = subprocess.run(['python3', str(root / 'current/deploy/backup.py'),
    '--root', str(root), 'create'], capture_output=True, text=True)
assert broken.returncode != 0 and "No module named 'psycopg'" in broken.stderr
print('REPRODUCED: installed 6639c38 CLI lacks psycopg', flush=True)

# Actual source/history control rows and protected onboarding/credential files.
seed = """
INSERT INTO netbox_sync.sources (id,source_instance,name,source_type,address,
 enabled,sync_enabled,sync_interval_seconds,verify_ssl,site_slug,device_role_slug,
 platform_slug,device_type_slug,cluster_type_slug,cluster_name,username,
 token_id_provider,token_id_key,token_secret_provider,token_secret_key,legacy_identity_owner,settings)
VALUES ('backup-row','backup-instance','Backup fixture','proxmox','provider.invalid',
 false,false,300,true,'test','server','proxmox','generic','virtualization','Test','test',
 'file','backup-token','file','backup-token',false,'{}');
INSERT INTO netbox_sync.sync_runs (run_id,source_instance,source_type,trigger,started_at,
 finished_at,duration_ms,status,created_by)
VALUES ('00000000-0000-0000-0000-000000000001','backup-instance','proxmox','manual',now(),now(),1,'SUCCEEDED','operator');
"""
run([*command, 'exec', '-T', 'postgres', 'psql', '-U', 'netbox_sync_bootstrap',
     '-d', 'netbox_sync', '--set', 'ON_ERROR_STOP=1'], input=seed)
state = {'format': 1, 'revision': 7, 'status': 'CONFIGURED',
         'url': 'https://netbox-test.indeed-id.hq', 'read_token': 'read-token',
         'apply_token': 'apply-token', 'completed': False, 'checks': [],
         'validated_at': None, 'safe_code': None}
for relative, payload in [('netbox/bootstrap.json', json.dumps(state)),
                          ('netbox/read-token', secrets.token_urlsafe(30)),
                          ('netbox/apply-token', secrets.token_urlsafe(30)),
                          ('sources/backup-token', secrets.token_urlsafe(30))]:
    path = root / 'secrets' / relative
    path.write_text(payload)
    path.chmod(0o600)
for key, value in {'operation': b'backup-fixture', 'receipt': secrets.token_bytes(24).hex().encode(),
                   'complete': b'1'}.items():
    os.setxattr(root / 'secrets/sources/backup-token', 'user.netbox_sync.' + key, value)


def snapshot():
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).digest(),
              path.stat().st_mode, path.stat().st_uid, path.stat().st_gid)
            for directory in ('config', 'secrets')
            for path in (root / directory).rglob('*') if path.is_file()}


def running():
    return set(run([*command, 'ps', '--status', 'running', '--services']).split())


before, release, services = snapshot(), (root / 'current').resolve(), running()
pgid = run([*command, 'ps', '-q', 'postgres']).strip()
pgmount = run(['docker', 'inspect', pgid, '--format', '{{json .Mounts}}'])
assert 'postgres' in services and 'netbox-sync-api' in services
assert run(['systemctl', 'is-active', 'netbox-sync.timer']).strip() == 'active'
assert 'succeeded' in cli('preflight')
created = cli('create')
bundles = list((root / 'backups').glob('netbox-sync-backup-*'))
assert len(bundles) == 1
bundle = bundles[0]
assert 'verification succeeded' in cli('verify', str(bundle))
summary_text = cli('inspect', str(bundle))
summary = json.loads(summary_text)
assert summary['release_id'] == OLD
assert summary['alembic_revision'] == '0005_source_tombstones'
assert (summary['source_count'], summary['run_count']) == (1, 1)
assert snapshot() == before
assert (root / 'current').resolve() == release
assert run([*command, 'ps', '-q', 'postgres']).strip() == pgid
assert run(['docker', 'inspect', pgid, '--format', '{{json .Mounts}}']) == pgmount
assert running() == services
assert run(['systemctl', 'is-active', 'netbox-sync.timer']).strip() == 'active'
manifest = json.loads((bundle / 'manifest.json').read_text())
assert manifest['active_release_id'] == OLD
assert manifest['deployment_identity']['root'] == str(root)
with tarfile.open(bundle / 'state.tar') as archive:
    for relative, metadata in before.items():
        member = archive.getmember(relative)
        assert hashlib.sha256(archive.extractfile(member).read()).digest() == metadata[0]
        assert (member.mode, member.uid, member.gid) == (metadata[1] & 0o7777, metadata[2], metadata[3])
    assert json.load(archive.extractfile('secrets/netbox/bootstrap.json')) == state
    assert 'SCHILY.xattr.user.netbox_sync.receipt' in archive.getmember('secrets/sources/backup-token').pax_headers
for path in (root / 'secrets').rglob('*'):
    if path.is_file() and path.name != 'bootstrap.lock':
        value = path.read_text().strip()
        if value:
            assert value not in created + summary_text
print('PASS: standard CLI create/verify/inspect; DB/history, onboarding, credentials, metadata, xattrs; current/volume unchanged; actual services and timer restored', flush=True)
# Missing DB transport: fail before changing a running timer/API.
run([*command, 'stop', 'postgres'])
failed = subprocess.run(['python3', '/review/deploy/backup.py', '--root', str(root), 'create'], capture_output=True, text=True)
assert failed.returncode == 1 and 'BACKUP_PREFLIGHT_FAILED' in failed.stderr
assert run(['systemctl', 'is-active', 'netbox-sync.timer']).strip() == 'active'
assert 'netbox-sync-api' in running()
run([*command, 'up', '-d', 'postgres'])
install._wait_for_postgres(root, p.release, root / 'config')
# Initially inactive services/timer must remain inactive after a second backup.
run(['systemctl', 'stop', 'netbox-sync.timer'])
run([*command, 'stop', 'netbox-sync-discovery-worker'])
time.sleep(1)
services = running()
cli('create')
assert running() == services
assert subprocess.run(['systemctl', 'is-active', '--quiet', 'netbox-sync.timer']).returncode == 3
print('PASS: early transport failure; prior inactive timer/service preserved', flush=True)
