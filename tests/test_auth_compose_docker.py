"""Opt-in real production Compose probe runtime; all resources scoped to this test."""
import os
from pathlib import Path
import subprocess
import uuid
import json
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
ROOT=Path(__file__).resolve().parents[1]
pytestmark=pytest.mark.skipif(os.environ.get('NETBOX_SYNC_AUTH_DOCKER_TEST')!='1',reason='opt-in isolated production probe smoke')
def docker(*args,check=True):
    return subprocess.run(['docker',*args],capture_output=True,text=True,check=check)
@pytest.mark.parametrize('mode',['bundled','external'])
def test_production_auth_policy(mode):
    project='netbox-sync-probe-test-'+uuid.uuid4().hex[:10]
    volume=project+'-files';host=project+'-host'
    assert docker('volume','inspect',volume,check=False).returncode != 0
    assert docker('container','inspect',host,check=False).returncode != 0
    docker('volume','create','--label','com.docker.compose.project='+project,volume)
    mount=docker('volume','inspect',volume,'--format','{{.Mountpoint}}').stdout.strip()
    try:
        docker('run','--rm','--label','com.docker.compose.project='+project,'--network','none','--user','0','--mount','type=volume,source='+volume+',target=/fixture',
               'netbox-sync-auth:review','python','-c',
               "from pathlib import Path; Path('/fixture/runtime').mkdir(mode=0o750)")
        docker('run','-d','--name',host,'--label','com.docker.compose.project='+project,'--mount','type=bind,source='+mount+'/runtime,target=/run/netbox-sync','--mount','type=volume,source='+volume+',target='+mount,
               '--mount','type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock',
               '--mount','type=bind,source='+str(ROOT)+',target=/review,readonly',
               'netbox-sync-probe-host:review')
        arguments=['exec',*(['-e','NETBOX_SYNC_REVIEW_IMAGE='+os.environ['NETBOX_SYNC_REVIEW_IMAGE']] if os.environ.get('NETBOX_SYNC_REVIEW_IMAGE') else []),*(['-e','NETBOX_SYNC_LDAP_COMPOSE_TEST=1'] if os.environ.get('NETBOX_SYNC_LDAP_COMPOSE_TEST')=='1' else []),*(['-e','NETBOX_SYNC_WORKER_FULL_SYNC_TEST=1'] if os.environ.get('NETBOX_SYNC_WORKER_FULL_SYNC_TEST')=='1' else []),
                   *(['-e','NETBOX_SYNC_BROWSER_FULL_SYNC_TEST=1'] if os.environ.get('NETBOX_SYNC_BROWSER_FULL_SYNC_TEST')=='1' else []),
                   *(['-e','NETBOX_SYNC_SCHEDULER_BASELINE=1'] if os.environ.get('NETBOX_SYNC_SCHEDULER_BASELINE')=='1' else []),
                   host,'python3','/review/tests/auth_compose_scenario.py',mount+'/netbox-sync-test',project,mode]
        if os.environ.get('NETBOX_SYNC_BROWSER_FULL_SYNC_TEST')!='1' and os.environ.get('NETBOX_SYNC_LDAP_COMPOSE_TEST')!='1':
            result=docker(*arguments,check=False)
        else:
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending=executor.submit(docker,*arguments,check=False)
                while not pending.done():
                    # Metadata/session stays in subprocess memory, never printed.
                    ready=docker('exec',host,'python3','-c',
                        "from pathlib import Path; import sys; p=Path(sys.argv[1]); print(p.read_text() if p.exists() else '')",mount+'/browser-request.json',check=False)
                    if ready.returncode==0 and ready.stdout.strip():
                        data=json.loads(ready.stdout)
                        assert data['project']==project
                        assert docker('inspect',data['api'],'--format','{{index .Config.Labels "com.docker.compose.project"}}').stdout.strip()==project
                        browser=subprocess.run(['node',str(ROOT/('frontend/scripts/production-ldap-browser.mjs' if data.get('kind')=='ldap' else 'frontend/scripts/production-sync-browser.mjs'))],
                            input=json.dumps(data),capture_output=True,text=True,encoding='utf-8',errors='replace',cwd=ROOT,timeout=240)
                        success=browser.returncode==0
                        docker('exec',host,'python3','-c',
                            "from pathlib import Path; import sys; Path(sys.argv[1]).unlink(); Path(sys.argv[2]).write_text(sys.argv[3])",mount+'/browser-request.json',mount+'/browser-done.json',json.dumps({'ok':success}))
                        if not success: print((browser.stderr or '')[-4000:])
                    time.sleep(.5)
                result=pending.result()

        assert result.returncode==0,result.stdout[-1500:]+result.stderr[-2500:]
        print(result.stdout[-700:])
    finally:
        for kind,listing in [('container',('ps','-aq')),('network',('network','ls','-q')),('volume',('volume','ls','-q'))]:
            for scoped_project in (project,project+'-restore'):
                for identifier in docker(*listing,'--filter','label=com.docker.compose.project='+scoped_project).stdout.split():
                    docker(*(('rm','-f',identifier) if kind=='container' else (kind,'rm',identifier)),check=False)
        # Every resource, including the operator host and external DB volume,
        # is removed only through its exact project ownership label.
