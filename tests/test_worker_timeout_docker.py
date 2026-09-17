"""Opt-in unique networkless test containers using supported Compose capabilities."""
import os
from pathlib import Path
import subprocess
import uuid
import pytest
import json
import re
ROOT=Path(__file__).resolve().parents[1]
pytestmark=pytest.mark.skipif(os.environ.get('NETBOX_SYNC_TIMEOUT_DOCKER_TEST')!='1',reason='isolated Linux timeout runtime')

@pytest.mark.parametrize('profile',['compose.production.yml','compose.web.yml'])
@pytest.mark.parametrize('missing',[False,True])
def test_production_child_timeout(profile,missing):
    files=['compose.yml',profile] if profile=='compose.web.yml' else [profile]
    env=os.environ.copy()
    for file in files:
        for key in re.findall(r'\$\{([A-Z_]+):\?',(ROOT/file).read_text()): env[key]='fixture'
    command=['docker','compose','--profile','*']
    for file in files: command+=['-f',str(ROOT/file)]
    rendered=subprocess.run(command+['config','--format','json','--no-env-resolution'],env=env,capture_output=True,text=True,check=True)
    services=json.loads(rendered.stdout)['services']
    caps=[cap.removeprefix('CAP_') for cap in services['netbox-sync-discovery-worker']['cap_add']]
    assert set(caps)=={cap.removeprefix('CAP_') for cap in services['netbox-sync-apply-worker']['cap_add']}=={'CHOWN','SETUID','SETGID','KILL'}
    name='netbox-sync-timeout-'+uuid.uuid4().hex[:12]
    args=['docker','run','--rm','--name',name,'--label','netbox-sync.timeout-test='+name,'--network','none','--user','0:0','--read-only','--tmpfs','/tmp:rw,size=64m,mode=1777','--security-opt','no-new-privileges:true','--cap-drop','ALL','-e','PYTHONDONTWRITEBYTECODE=1','-e','NETBOX_SYNC_TIMEOUT_TEST=1','-e','NETBOX_SYNC_TEST_NO_KILL='+('1' if missing else '0'),'--mount','type=bind,source='+str(ROOT)+',target=/app,readonly','-w','/app']
    for cap in caps:
        if not(missing and cap=='KILL'): args+=['--cap-add',cap]
    args+=['netbox-sync-ldap-tests:review','python','-m','pytest','tests/test_worker_timeout_linux.py','-q','-p','no:cacheprovider','--tb=short']
    result=subprocess.run(args,capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stdout+result.stderr
