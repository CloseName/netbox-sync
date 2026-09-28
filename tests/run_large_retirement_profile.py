"""Run only on the local disposable Docker Engine; never accepts a DB address."""
import subprocess,json,time,uuid
project='netbox-sync-large-'+uuid.uuid4().hex[:10]
label='netbox-sync.task='+project
created=[]
def d(*args,**kw):return subprocess.run(['docker',*args],check=True,capture_output=True,**kw)
try:
    pg=project+'-pg'
    d('run','-d','--name',pg,'--label',label,'--network','none','--tmpfs','/var/lib/postgresql/data:size=768m','-e','POSTGRES_HOST_AUTH_METHOD=trust','postgres:16-bookworm');created.append(pg)
    for _ in range(100):
        if subprocess.run(['docker','exec',pg,'pg_isready','-U','postgres'],capture_output=True).returncode==0:break
        time.sleep(.2)
    redis=project+'-redis'
    d('run','-d','--name',redis,'--label',label,'--network','container:'+pg,'redis:7-alpine','redis-server','--save','','--appendonly','no');created.append(redis)
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    name=project+'-netbox';created.append(name)
    d('run','-d','--name',name,'--label',label,'--network','container:'+pg,'--mount',f'type=bind,source={root},target=/app,readonly','--mount',f'type=bind,source={root}/tests/netbox_guard_plugins.py,target=/etc/netbox/config/plugins.py,readonly','-e','PYTHONPATH=/app/deploy','-e','PYTHONDONTWRITEBYTECODE=1','-e','NETBOX_SYNC_ISOLATED_MODEL_TEST=1','-e','NETBOX_SYNC_MODEL_DB=netbox_sync_guard_test','--entrypoint','/opt/netbox/venv/bin/python','netboxcommunity/netbox:v4.7.0','/app/tests/netbox_large_retirement_scenario.py')
    print('Isolated fixture '+project,flush=True)
    result=d('wait',name,timeout=1000)
    logs=d('logs',name)
    print(logs.stdout.decode(errors='replace')[-5000:],flush=True)
    print(logs.stderr.decode(errors='replace')[-3500:],flush=True)
    assert result.stdout.strip()==b'0', 'Large fixture failed'
finally:
    for name in reversed(created):
        found=subprocess.run(['docker','inspect',name],capture_output=True)
        if found.returncode==0:
            assert json.loads(found.stdout)[0]['Config']['Labels']['netbox-sync.task']==project
            d('rm','-f',name)
