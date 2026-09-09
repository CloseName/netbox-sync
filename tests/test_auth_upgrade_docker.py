"""Opt-in Debian upgrade from the accepted pre-auth release, never a VM."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
import pytest
from tests.test_auth_compose_docker import docker, ROOT
OLD='897de2a79a6781129f84cbbdcaef9b250795deb7'
@pytest.mark.skipif(os.environ.get('NETBOX_SYNC_AUTH_UPGRADE_TEST')!='1',reason='opt-in isolated Debian operator host; Docker socket requires explicit approval')
def test_pre_auth_upgrade_without_systemd():
    project='netbox-sync-auth-upgrade-'+uuid.uuid4().hex[:10]
    host,volume=project+'-host',project+'-files'
    docker('volume','create',volume)
    mount=docker('volume','inspect',volume,'--format','{{.Mountpoint}}').stdout.strip()
    try:
        docker('run','--rm','--network','none','--user','0','--mount','type=volume,source='+volume+',target=/fixture',
               'netbox-sync-auth:review','python','-c',"from pathlib import Path; Path('/fixture/runtime').mkdir(mode=0o750)")
        docker('run','-d','--name',host,
               '--mount','type=bind,source='+mount+'/runtime,target=/run/netbox-sync',
               '--mount','type=volume,source='+volume+',target='+mount,
               '--mount','type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock',
               '--mount','type=bind,source='+str(ROOT)+',target=/review,readonly',
               'netbox-sync-backup-host:review')
        with tempfile.TemporaryDirectory() as directory:
            archive=Path(directory)/'old.tar'
            subprocess.run(['git','archive','--format=tar','-o',str(archive),OLD],cwd=ROOT,check=True)
            docker('cp',str(archive),host+':/old.tar')
        docker('exec',host,'mkdir','/old-source')
        docker('exec',host,'tar','-xf','/old.tar','-C','/old-source')
        result=docker('exec',host,'python3','/review/tests/auth_upgrade_scenario.py',mount+'/netbox-sync-test',project,check=False)
        assert result.returncode==0,result.stdout[-1500:]+result.stderr[-2500:]
        print(result.stdout[-1200:])
    finally:
        for kind,listing in [('container',('ps','-aq')),('network',('network','ls','-q')),('volume',('volume','ls','-q'))]:
            for identifier in docker(*listing,'--filter','label=com.docker.compose.project='+project).stdout.split():
                docker(*(('rm','-f',identifier) if kind=='container' else (kind,'rm',identifier)),check=False)
        docker('rm','-f',host,check=False)
        for name in (project+'-db',volume):docker('volume','rm',name,check=False)
        docker('image','rm',project+':old',check=False)
