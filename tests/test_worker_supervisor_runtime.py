"""Real fixed worker bundles and cross-UID process-group termination in Docker."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import pytest
from netbox_sync.worker_supervisor import child_environment


def test_child_database_roles_do_not_leak():
    values = {key:'test-only' for key in ('NETBOX_SYNC_DISCOVERY_REGISTRY_DSN',
        'NETBOX_SYNC_OPERATION_WRITER_DSN','NETBOX_SYNC_APPLY_REGISTRY_DSN',
        'NETBOX_SYNC_RUN_WRITER_DSN','UNRELATED_SECRET')}
    assert set(child_environment('discovery_worker', values)) == {'NETBOX_SYNC_DISCOVERY_REGISTRY_DSN','NETBOX_SYNC_OPERATION_WRITER_DSN'}
    assert set(child_environment('apply_worker', values)) == {'NETBOX_SYNC_APPLY_REGISTRY_DSN','NETBOX_SYNC_RUN_WRITER_DSN'}
    assert child_environment('bootstrap_worker', values) == {}
    assert child_environment('retirement_worker', values) == {}


ISOLATED = os.name == 'posix' and Path('/.dockerenv').exists() and os.environ.get('NETBOX_SYNC_BUNDLE_TEST') == '1'


@pytest.mark.skipif(not ISOLATED, reason='requires isolated Docker with explicit bundle test flag')
@pytest.mark.parametrize('bundle', ['netbox','sync'])
def test_real_bundle_health_and_shutdown(bundle, tmp_path):
    if bundle=='sync':
        # Docker named-volume roots exist as root:root 0755 before workers start.
        # A bare pytest container must recreate that production mount boundary.
        for name in ('discovery','apply'):
            directory=Path('/run/netbox-sync-'+name)
            directory.mkdir(mode=0o755,exist_ok=True)
            directory.chmod(0o755)
    root = tmp_path/'netbox'
    root.mkdir(mode=0o700)
    environment = dict(os.environ, NETBOX_SYNC_NETBOX_STATE_DIR=str(root),
        NETBOX_SYNC_REGISTRY_SCHEMA='netbox_sync',
        NETBOX_SYNC_DISCOVERY_REGISTRY_DSN='host=127.0.0.1 dbname=test user=test',
        NETBOX_SYNC_APPLY_REGISTRY_DSN='host=127.0.0.1 dbname=test user=test',
        NETBOX_SYNC_OPERATION_WRITER_DSN='host=127.0.0.1 dbname=test user=test',
        NETBOX_SYNC_RUN_WRITER_DSN='host=127.0.0.1 dbname=test user=test')
    command = [sys.executable,'-m','netbox_sync.worker_supervisor',bundle]
    with (tmp_path/'worker.log').open('w+') as log, subprocess.Popen(command, env=environment, stdout=subprocess.DEVNULL, stderr=log) as process:
        try:
            for _ in range(40):
                assert process.poll() is None, (tmp_path/'worker.log').read_text()
                probe = subprocess.run(command+['--health'], env=environment, capture_output=True, timeout=8)
                if probe.returncode == 0:break
                time.sleep(0.1)
            else:pytest.fail('Both production worker interfaces must respond: '+(tmp_path/'worker.log').read_text()[-2500:])
        finally:
            process.terminate()
            process.wait(timeout=9)
        assert process.returncode == 0


@pytest.mark.skipif(not ISOLATED, reason='requires isolated Docker with explicit bundle test flag')
@pytest.mark.parametrize('failure', [False, True])
def test_cross_uid_descendant_and_sibling_are_stopped(tmp_path, failure):
    marker = tmp_path/'descendant.pid'
    child = tmp_path/'member.py'
    child.write_text("""import os,signal,time,sys
pid=os.fork()
if pid==0:
 os.setgid(10001);os.setuid(10001)
 signal.signal(signal.SIGTERM,signal.SIG_IGN)
 while True:time.sleep(1)
open(sys.argv[1],'w').write(str(pid))
if sys.argv[2]=='fail':time.sleep(.5);sys.exit(7)
while True:time.sleep(1)
""")
    script = tmp_path/'supervise.py'
    script.write_text("""import os,sys
from netbox_sync.worker_supervisor import supervise
sys.exit(supervise([([sys.executable,sys.argv[1],sys.argv[2],sys.argv[3]],dict(os.environ)),
 ([sys.executable,'-c','import time;time.sleep(60)'],dict(os.environ))],grace=.2))
""")
    process = subprocess.Popen([sys.executable,str(script),str(child),str(marker),'fail' if failure else 'wait'], env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1])))
    try:
        for _ in range(50):
            if marker.exists():break
            time.sleep(.05)
        assert marker.exists()
        pid = int(marker.read_text())
        if not failure:process.terminate()
        assert process.wait(timeout=5) == (1 if failure else 0)
        for _ in range(50):
            if not Path('/proc/'+str(pid)).exists():break
            time.sleep(.05)
        assert not Path('/proc/'+str(pid)).exists(), 'cross-UID grandchild must be reaped by container init'
    finally:
        if process.poll() is None:process.kill();process.wait()
