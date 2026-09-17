"""Run inside a production-capability container, including the missing-KILL case."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from dataclasses import replace
import pytest

pytestmark = pytest.mark.skipif(os.name != 'posix' or os.getuid() != 0 or os.environ.get('NETBOX_SYNC_TIMEOUT_TEST') != '1', reason='isolated Linux cross-UID capability container')


def child(code, **kwargs):
    return subprocess.Popen([sys.executable, '-c', code], **kwargs)


@pytest.mark.parametrize('worker', ['discovery', 'apply'])
def test_supervisor_timeout_and_next_job(worker, tmp_path, monkeypatch):
    from netbox_sync import discovery_worker as discovery, apply_worker as apply
    from netbox_sync import child_process as cleanup
    from tests.sample_data import sample_source_config
    from netbox_sync.source_config import SourceCredentials, SecretReference
    monkeypatch.setattr(cleanup, 'REAP_TIMEOUT', .1)
    monkeypatch.setattr(discovery, 'DISCOVERY_TIMEOUT', .8)
    monkeypatch.setattr(apply, 'CHILD_TIMEOUT', .8)
    processes=[]
    def spawn(_args, **kw):
        code = "import os,time,json; from pathlib import Path; from netbox_sync.child_process import phase_progress; assert os.getuid()==10001; assert int(next(x.split()[1] for x in Path('/proc/self/status').read_text().splitlines() if x.startswith('CapEff:')),16)==0; phase_progress('provider'); "
        code += 'time.sleep(2)' if not processes else "print(json.dumps({'result':{'items':[]}}))"
        process=child(code, **kw); processes.append(process); return process
    if worker=='apply':
        supervisor=apply.ApplySupervisor('', '', '', '', '', '', '', popen=spawn)
        call=lambda:supervisor._child({'operation':'apply'})
        expected='OUTCOME_UNCERTAIN'
    else:
        for name in ('token-id','token-secret','netbox-token'): (tmp_path/name).write_text('fixture')
        config=replace(sample_source_config(),credentials=SourceCredentials('user',SecretReference('file','token-id'),SecretReference('file','token-secret')))
        supervisor=discovery.DiscoverySupervisor('reader','netbox_sync',tmp_path,tmp_path,'https://fixture',tmp_path/'netbox-token',10001,10001,popen=spawn)
        monkeypatch.setattr(supervisor,'_source',lambda _:config)
        call=lambda:supervisor.run(config.source_instance)
        expected='DISCOVERY_TIMEOUT'
    started=time.monotonic()
    with pytest.raises((discovery.WorkerError,apply.ApplyWorkerError)) as caught: call()
    assert caught.value.code==expected
    detail=caught.value.diagnostic
    assert detail['exception_class']=='TimeoutExpired'
    assert detail['phases']==[{'phase':'provider','state':'started'}]
    missing=os.environ.get('NETBOX_SYNC_TEST_NO_KILL')=='1'
    assert detail['child_reaped'] is not missing
    if missing:
        assert detail['cleanup_error']=='PermissionError'
        assert time.monotonic()-started<1.8
        time.sleep(2.1) # only a test fixture, natural finite exit
    else:
        assert processes[0].returncode==-9
    with pytest.raises(ChildProcessError): os.waitpid(processes[0].pid,os.WNOHANG)
    assert call()=={'items':[]}
    assert processes[1].returncode==0


def test_race_and_shared_lock_retention(tmp_path, monkeypatch):
    import fcntl
    from netbox_sync.child_process import stop_child
    import netbox_sync.child_process as cleanup
    from netbox_sync.discovery_worker import _drop_privileges
    monkeypatch.setattr(cleanup,'REAP_TIMEOUT',.1)
    with subprocess.Popen([sys.executable,'-c','pass'],preexec_fn=_drop_privileges(10001,10001)) as ended:
        ended.wait()
        assert stop_child(ended)['child_reaped']
    if os.environ.get('NETBOX_SYNC_TEST_NO_KILL')!='1': return
    lock=os.open(tmp_path/'lock',os.O_CREAT|os.O_RDWR,0o600)
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    process=child('import time; time.sleep(1)',preexec_fn=_drop_privileges(10001,10001))
    detail=stop_child(process,lock)
    assert detail['cleanup_error']=='PermissionError' and not detail['child_reaped']
    os.close(lock)
    other=os.open(tmp_path/'lock',os.O_RDWR)
    try:
        with pytest.raises(BlockingIOError): fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
        time.sleep(1.2)
        fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(ChildProcessError): os.waitpid(process.pid,os.WNOHANG)
    finally: os.close(other)
