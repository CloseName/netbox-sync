"""Start real API/control processes against a freshly provisioned empty test DB."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import pytest
from netbox_sync import deployment
from tests.test_deployment_postgres import _environment

pytestmark=pytest.mark.skipif(getattr(os,'geteuid',lambda:-1)()!=0,reason='Disposable Linux root required')


def test_zero_source_processes_boot_without_netbox_or_provider_secrets(tmp_path):
    env=_environment(tmp_path)
    deployment.bootstrap_roles(env);deployment.migrate(env);deployment.apply_grants(env)
    with tempfile.TemporaryDirectory(prefix='netbox-sync-zero-test-') as directory:
        root=Path(directory);root.chmod(0o755)
        sources=root/'sources';sources.mkdir(mode=0o700)
        netbox=root/'netbox';netbox.mkdir(mode=0o700)
        sockets={name:root/name/'worker.sock' for name in ('bootstrap','lifecycle','broker','discovery','apply','schedule')}
        for path in sockets.values():path.parent.mkdir(mode=0o755)
        processes=[]
        base={'PATH':os.environ['PATH'],'PYTHONPATH':str(Path.cwd()),'NETBOX_SYNC_REGISTRY_SCHEMA':'netbox_sync','PYTHONDONTWRITEBYTECODE':'1'}
        def start(module,extra,arguments=(),uid=None):
            def drop():os.setgroups([]);os.setgid(uid);os.setuid(uid)
            process=subprocess.Popen([sys.executable,'-m',module,*arguments],env={**base,**extra},
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,preexec_fn=drop if uid is not None else None)
            processes.append(process)
        try:
            start('netbox_sync.secret_broker',{},['--socket',str(sockets['broker']),'--secret-root',str(sources),'--allowed-uid','10001'])
            start('netbox_sync.bootstrap_worker',{'NETBOX_SYNC_BOOTSTRAP_SOCKET':str(sockets['bootstrap']),
                'NETBOX_SYNC_NETBOX_STATE_DIR':str(netbox),'NETBOX_SYNC_APPLY_LOCK_PATH':str(root/'apply.lock')})
            start('netbox_sync.lifecycle_worker',{'NETBOX_SYNC_LIFECYCLE_SOCKET':str(sockets['lifecycle']),
                'NETBOX_SYNC_BROKER_SOCKET':str(sockets['broker']),'NETBOX_SYNC_APPLY_LOCK_PATH':str(root/'apply.lock'),
                'NETBOX_SYNC_LIFECYCLE_WRITER_DSN':deployment.connection_info('lifecycle_writer',env)})
            for name in ('discovery','apply'):
                role='discovery_reader' if name=='discovery' else 'apply_registry_reader'
                extra={f'NETBOX_SYNC_{name.upper()}_REGISTRY_DSN':deployment.connection_info(role,env),
                    'NETBOX_SYNC_NETBOX_CONFIG_FILE':str(netbox/'bootstrap.json'),
                    'NETBOX_SYNC_OPERATION_WRITER_DSN':deployment.connection_info('operation_writer',env)}
                if name=='apply':extra['NETBOX_SYNC_RUN_WRITER_DSN']=deployment.connection_info('run_writer',env)
                args=['--socket',str(sockets[name]),'--secret-root',str(sources),'--source-secret-root',str(sources),
                    '--netbox-token-file',str(netbox/'absent-token')]
                if name=='apply':args+=['--lock-path',str(root/'apply.lock')]
                start('netbox_sync.'+name+'_worker',extra,args)
            start('netbox_sync.schedule_worker',{'NETBOX_SYNC_SCHEDULE_WRITER_DSN':deployment.connection_info('schedule_writer',env)},['--socket',str(sockets['schedule'])])
            for _ in range(150):
                assert all(process.poll() is None for process in processes),'A zero-source worker exited'
                if all(path.exists() for path in sockets.values()):break
                time.sleep(.02)
            assert all(path.exists() for path in sockets.values())
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            api_env={'NETBOX_SYNC_REGISTRY_DSN':deployment.connection_info('web_reader',env),
                     'NETBOX_SYNC_REGISTRATION_DSN':deployment.connection_info('registration_writer',env)}
            api_env.update({'NETBOX_SYNC_'+name.upper()+'_SOCKET':str(path) for name,path in sockets.items()})
            start('uvicorn',api_env,['netbox_sync.api.app:create_app','--factory','--host','127.0.0.1','--port',str(port),'--no-access-log'],uid=10001)
            def get(path):
                with urllib.request.urlopen(f'http://127.0.0.1:{port}'+path,timeout=2) as response:return json.load(response)
            for _ in range(100):
                assert processes[-1].poll() is None,'API exited'
                try:state=get('/api/v1/bootstrap');break
                except OSError:time.sleep(.05)
            else:raise AssertionError('API did not start')
            assert state['status']=='FRESH'
            assert get('/api/v1/sources')['sources']==[]
            assert get('/api/v1/system/health')['status']=='degraded'
            assert list(sources.iterdir())==[] and not (netbox/'bootstrap.json').exists()
            scheduler=subprocess.run(['netbox-sync'],env={**base,
                'SOURCE_CONFIG_MODE':'registry-all','SYNC_MODE':'apply','APPLY_SCOPE':'full','APPLY_CONFIRM':'FULL_WRITE',
                'NETBOX_SYNC_REGISTRY_DSN':deployment.connection_info('registry_reader',env),
                'NETBOX_SYNC_RUN_WRITER_DSN':deployment.connection_info('run_writer',env),
                'NETBOX_SYNC_NETBOX_CONFIG_FILE':str(netbox/'bootstrap.json')},capture_output=True,timeout=15)
            assert scheduler.returncode==0,scheduler.stderr.decode()
        finally:
            for process in reversed(processes):
                if process.poll() is None:process.terminate()
                process.wait(timeout=10)
