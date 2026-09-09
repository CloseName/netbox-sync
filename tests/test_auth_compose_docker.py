"""Opt-in real production Compose probe runtime; all resources scoped to this test."""
import os
from pathlib import Path
import subprocess
import uuid
import pytest
ROOT=Path(__file__).resolve().parents[1]
pytestmark=pytest.mark.skipif(os.environ.get('NETBOX_SYNC_AUTH_DOCKER_TEST')!='1',reason='opt-in isolated production probe smoke')
def docker(*args,check=True):
    return subprocess.run(['docker',*args],capture_output=True,text=True,check=check)
@pytest.mark.parametrize('mode',['bundled','external'])
def test_production_auth_policy(mode):
    project='netbox-sync-probe-test-'+uuid.uuid4().hex[:10]
    volume=project+'-files';host=project+'-host'
    docker('volume','create',volume)
    mount=docker('volume','inspect',volume,'--format','{{.Mountpoint}}').stdout.strip()
    try:
        docker('run','--rm','--network','none','--user','0','--mount','type=volume,source='+volume+',target=/fixture',
               'netbox-sync-auth:review','python','-c',
               "from pathlib import Path; Path('/fixture/runtime').mkdir(mode=0o750)")
        docker('run','-d','--name',host,'--mount','type=bind,source='+mount+'/runtime,target=/run/netbox-sync','--mount','type=volume,source='+volume+',target='+mount,
               '--mount','type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock',
               '--mount','type=bind,source='+str(ROOT)+',target=/review,readonly',
               'netbox-sync-probe-host:review')
        result=docker('exec',host,'python3','/review/tests/auth_compose_scenario.py',mount+'/netbox-sync-test',project,mode,check=False)
        assert result.returncode==0,result.stdout[-1500:]+result.stderr[-2500:]
        print(result.stdout[-700:])
    finally:
        for kind,listing in [('container',('ps','-aq')),('network',('network','ls','-q')),('volume',('volume','ls','-q'))]:
            for scoped_project in (project,project+'-restore'):
                for identifier in docker(*listing,'--filter','label=com.docker.compose.project='+scoped_project).stdout.split():
                    docker(*(('rm','-f',identifier) if kind=='container' else (kind,'rm',identifier)),check=False)
        docker('rm','-f',host,check=False)
        for name in (project+'-db',project+'-external-db',project+'-restore-db',volume):docker('volume','rm',name,check=False)
