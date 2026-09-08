"""Real Linux Unix sockets and process restart, without provider/network calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import pytest
from netbox_sync.local_control import request
from netbox_sync.api.onboarding_adapters import BrokerSecretStore
from netbox_sync.lifecycle_worker import BrokerCleanup
from tests.test_secret_broker_transport import start_broker

pytestmark=pytest.mark.skipif(getattr(os,'geteuid',lambda:-1)()!=0,reason='Disposable Linux root required')


def peer_request(path,payload):
    script="import os,json,sys; from netbox_sync.local_control import request; os.setgroups([]); os.setgid(10001); os.setuid(10001); print(json.dumps(request(sys.argv[1],json.load(sys.stdin))))"
    return subprocess.run([sys.executable,'-c',script,str(path)],input=json.dumps(payload),
                          capture_output=True,text=True,timeout=10)


def wait_socket(process,path):
    for _ in range(100):
        assert process.poll() is None
        if path.exists():return
        time.sleep(.02)
    raise AssertionError('Control socket did not start')


def test_cleanup_socket_is_reserved_to_lifecycle_root_peer():
    with tempfile.TemporaryDirectory(prefix='netbox-sync-control-test-') as directory:
        root=Path(directory);root.chmod(0o755)
        secrets=root/'secrets';secrets.mkdir(mode=0o700)
        path=root/'broker.sock'
        process=start_broker(secrets,path)
        try:BrokerSecretStore(str(path)).create('src-control-0123456789abcdef','TEST-ONLY-CREDENTIAL')
        finally:process.terminate();process.wait(timeout=5)
        keys=[p.name for p in secrets.iterdir()]
        assert len(keys)==1
        process=start_broker(secrets,path,uid=10001)
        try:
            denied=peer_request(path,dict(action='remove_owned',keys=keys))
            assert denied.returncode!=0 and 'PEER_NOT_AUTHORIZED' in denied.stderr
            assert all((secrets/key).exists() for key in keys)
            cleanup=BrokerCleanup(str(path))
            assert cleanup.remove_owned(keys) is True
            assert cleanup.remove_owned(keys) is True
            assert list(secrets.iterdir())==[]
        finally:process.terminate();process.wait(timeout=5)


def test_first_run_control_process_restart_and_peer_isolation():
    with tempfile.TemporaryDirectory(prefix='netbox-sync-bootstrap-test-') as directory:
        root=Path(directory);root.chmod(0o755)
        secrets=root/'secrets';secrets.mkdir(mode=0o700)
        sockets=root/'socket';sockets.mkdir(mode=0o755)
        path=sockets/'worker.sock'
        script="""import sys
from netbox_sync.local_control import serve
from netbox_sync.bootstrap_state import BootstrapStore
from netbox_sync.bootstrap_worker import BootstrapControl
from netbox_sync.bootstrap_probe import FIELDS
def probe(_):
 return dict(safe_code=None,checks=[dict(name=n,type=k,models=list(m),ok=True) for n,(k,m) in FIELDS.items()])
serve(sys.argv[1], BootstrapControl(BootstrapStore(sys.argv[2]),sys.argv[3],probe),concurrent=True)
"""
        def start():
            if path.exists():path.unlink()
            process=subprocess.Popen([sys.executable,'-c',script,str(path),str(secrets),str(root/'apply.lock')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            wait_socket(process,path);return process
        def call(payload):
            result=peer_request(path,payload)
            assert result.returncode==0,result.stderr
            return json.loads(result.stdout)['result']
        process=start()
        try:
            with pytest.raises(Exception):request(str(path),dict(action='status'))
            assert call(dict(action='status'))['status']=='FRESH'
            value=call(dict(action='configure',revision=0,url='https://netbox.example.test',read_token='TEST-READ-TOKEN',apply_token='TEST-APPLY-TOKEN',replace_credentials=False))
            assert value['status']=='CONFIGURED' and 'TEST-READ-TOKEN' not in json.dumps(value)
        finally:process.terminate();process.wait(timeout=5)
        process=start()
        try:
            assert call(dict(action='status'))['status']=='CONFIGURED'
            assert call(dict(action='validate',revision=1))['status']=='VALIDATED'
            assert call(dict(action='finish',revision=1))==call(dict(action='finish',revision=1))
        finally:process.terminate();process.wait(timeout=5)
        process=start()
        try:assert call(dict(action='status'))['status']=='READY'
        finally:process.terminate();process.wait(timeout=5)
