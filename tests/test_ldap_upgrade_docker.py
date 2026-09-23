"""Opt-in Debian upgrade from the accepted local-admin release, never a VM."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
import pytest
from tests.test_auth_compose_docker import docker, ROOT
OLD='5acd4c12d62c62072049b22f98e22d19a980a5af'
@pytest.mark.skipif(os.environ.get('NETBOX_SYNC_LDAP_UPGRADE_TEST')!='1',reason='opt-in isolated Debian operator host; Docker socket requires explicit approval')
def test_existing_admin_ldap_upgrade_without_systemd():
    project='netbox-sync-ldap-upgrade-'+uuid.uuid4().hex[:10]
    host,volume=project+'-host',project+'-files'
    assert docker('volume','inspect',volume,check=False).returncode != 0
    assert docker('container','inspect',host,check=False).returncode != 0
    assert docker('image','inspect',project+':old',check=False).returncode != 0
    docker('volume','create','--label','com.docker.compose.project='+project,volume)
    mount=docker('volume','inspect',volume,'--format','{{.Mountpoint}}').stdout.strip()
    try:
        docker('run','--rm','--label','com.docker.compose.project='+project,'--network','none','--user','0','--mount','type=volume,source='+volume+',target=/fixture',
               'netbox-sync-auth:review','python','-c',"from pathlib import Path; Path('/fixture/runtime').mkdir(mode=0o750)")
        docker('run','-d','--name',host,'--label','com.docker.compose.project='+project,
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
        # Freeze release input: browser screenshots may change while other gates run.
        docker('exec',host,'python3','-c',
            "import shutil,sys; sys.path.insert(0,'/review'); from deploy.install import _ignore; shutil.copytree('/review','/new-source',ignore=lambda d,n: _ignore(d,n)+[v for v in n if v in ('test-results','playwright-report')])")
        result=docker('exec',*(['-e','NETBOX_SYNC_REVIEW_IMAGE='+os.environ['NETBOX_SYNC_REVIEW_IMAGE']] if os.environ.get('NETBOX_SYNC_REVIEW_IMAGE') else []),host,'python3','/review/tests/ldap_upgrade_scenario.py',mount+'/netbox-sync-test',project,check=False)
        assert result.returncode==0,result.stdout[-1500:]+result.stderr[-2500:]
        print(result.stdout[-1200:])
    finally:
        for kind,listing in [('container',('ps','-aq')),('network',('network','ls','-q')),('volume',('volume','ls','-q'))]:
            for identifier in docker(*listing,'--filter','label=com.docker.compose.project='+project).stdout.split():
                docker(*(('rm','-f',identifier) if kind=='container' else (kind,'rm',identifier)),check=False)
        docker('image','rm',project+':old',check=False)
