"""Opt-in local operator gate. Product containers never receive Docker socket."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from uuid import uuid4

assert os.environ.get('NETBOX_SYNC_GUARD_WORKER_TEST')=='1'
pg=os.environ['NETBOX_SYNC_GUARD_PG']
root=Path(__file__).resolve().parents[1]

def docker(*args,check=True,**kwargs):
    return subprocess.run(['docker',*args],check=check,capture_output=True,**kwargs)
info=json.loads(docker('inspect',pg).stdout)[0]
assert info['Config']['Labels'].get('netbox-sync.task')=='host-claims-20260923'
assert info['HostConfig']['NetworkMode']=='none'
project='netbox-sync-retirement-'+uuid4().hex[:12]
label='netbox-sync.task='+project
network=project+'-network';volume=project+'-fixture'
fixture=project+'-netbox';proxy=project+'-relay';worker=project+'-retirement-worker'
created=[];fixture_ready=False

def owned_remove(kind,name):
    found=docker(*(('inspect',name) if kind=='container' else (kind,'inspect',name)),check=False)
    if found.returncode:return
    data=json.loads(found.stdout)[0]
    labels=data['Config']['Labels'] if kind=='container' else data['Labels']
    assert labels.get('netbox-sync.task')==project
    docker(*(('rm','-f',name) if kind=='container' else (kind,'rm',name)))

try:
    docker('network','create','--internal','--label',label,network);created.append(('network',network))
    docker('volume','create','--label',label,volume);created.append(('volume',volume))
    docker('run','-d','--name',fixture,'--label',label,'--user','0:0','--network','container:'+pg,
        '--mount','type=bind,source='+str(root)+',target=/app,readonly',
        '--mount','type=bind,source='+str(root/'tests/netbox_guard_plugins.py')+',target=/etc/netbox/config/plugins.py,readonly',
        '--mount','type=volume,source='+volume+',target=/fixture',
        '-e','PYTHONPATH=/app/deploy','-e','NETBOX_SYNC_ISOLATED_MODEL_TEST=1',
        '-e','NETBOX_SYNC_MODEL_DB=netbox_sync_guard_test','-e','NETBOX_SYNC_GUARD_WORKER_TEST=1',
        '--entrypoint','/opt/netbox/venv/bin/python','netboxcommunity/netbox:v4.7.0','/app/tests/netbox_guard_http_scenario.py')
    created.append(('container',fixture))
    print('Preparing isolated real NetBox fixture',flush=True)
    deadline=time.monotonic()+180
    while True:
        value=docker('exec',fixture,'cat','/fixture/bridge/ready.json',check=False)
        if value.returncode==0:
            meta=json.loads(value.stdout);fixture_ready=True;break
        state=json.loads(docker('inspect',fixture).stdout)[0]['State']
        if not state['Running']:raise AssertionError('NetBox fixture exited: '+docker('logs',fixture).stdout.decode(errors='replace')[-1800:])
        if time.monotonic()>deadline:raise AssertionError('NetBox fixture preparation deadline')
        time.sleep(1)
    assert set(meta)=={'guard_instance','source','cluster'}
    docker('run','-d','--name',proxy,'--label',label,'--user','10001:10001','--read-only',
        '--cap-drop','ALL','--security-opt','no-new-privileges:true','--network',network,'--network-alias','guard-netbox.test',
        '--mount','type=volume,source='+volume+',target=/bridge,volume-subpath=bridge,readonly',
        '--mount','type=bind,source='+str(root/'tests/retirement_bridge.py')+',target=/relay.py,readonly',
        '--entrypoint','python','netbox-sync-retirement:20260923','-B','/relay.py')
    created.append(('container',proxy))
    mounts=[{'type':'volume','source':'retirement-fixture','target':target,'read_only':readonly,'volume':{'subpath':subpath}}
            for subpath,target,readonly in [('worker','/run/netbox-sync-retirement',False),('config','/run/secrets/netbox',True),('ca','/run/netbox-sync-ca',True)]]
    # JSON is valid YAML; the explicit !override is necessary to replace only
    # fixture paths, while retaining the actual production security/command.
    override='services:\n  netbox-sync-retirement-worker:\n    labels: '+json.dumps({'netbox-sync.task':project})+'\n    volumes: !override '+json.dumps(mounts)+'\n'
    override+='networks:\n  netbox-sync-egress: '+json.dumps({'external':True,'name':network})+'\n'
    override+='volumes:\n  retirement-fixture: '+json.dumps({'external':True,'name':volume})+'\n'
    with tempfile.TemporaryDirectory(prefix=project) as directory:
        path=Path(directory)/'fixture.yml';path.write_text(override)
        env=dict(os.environ,NETBOX_SYNC_COMPOSE_PROJECT=project,NETBOX_SYNC_IMAGE='netbox-sync-retirement:20260923',
                 NETBOX_SYNC_GUARD_INSTANCE=meta['guard_instance'])
        compose=['compose','--project-name',project,'-f',str(root/'compose.production.yml'),'-f',str(path)]
        model=json.loads(docker(*compose,'config','--format','json',env=env).stdout)['services']['netbox-sync-retirement-worker']
        assert model['command']==['python','-m','netbox_sync.retirement_worker']
        assert model['read_only'] and model['cap_drop']==['ALL'] and model['cap_add']==['CHOWN']
        assert not model.get('ports') and set(model['networks'])=={'netbox-sync-egress'}
        created.append(('container',worker))
        docker(*compose,'up','-d','--no-deps','netbox-sync-retirement-worker',env=env)
    deadline=time.monotonic()+15
    while docker('exec',fixture,'test','-S','/fixture/worker/worker.sock',check=False).returncode:
        if time.monotonic()>deadline:raise AssertionError('Worker socket unavailable')
        time.sleep(.1)
    actual=json.loads(docker('inspect',worker).stdout)[0]
    assert actual['HostConfig']['ReadonlyRootfs'] and not actual['HostConfig']['PortBindings']
    assert set(actual['NetworkSettings']['Networks'])=={network}
    assert not any('docker.sock' in m['Destination'] or 'sources' in m['Destination'] for m in actual['Mounts'])
    checked=docker('run','--rm','--network','container:'+pg,'--label',label,
        '--mount','type=bind,source='+str(root)+',target=/app,readonly',
        '--mount','type=volume,source='+volume+',target=/bridge,volume-subpath=bridge',
        '--mount','type=volume,source='+volume+',target=/worker,volume-subpath=worker,readonly',
        '-e','PYTHONDONTWRITEBYTECODE=1','-e','NETBOX_SYNC_GUARD_WORKER_TEST=1',
        '-e','NETBOX_SYNC_TEST_POSTGRES_DSN=host=127.0.0.1 dbname=netbox_sync_test user=postgres',
        '-w','/app','--entrypoint','python','netbox-sync-retirement-tests:20260923','-m','pytest',
        'tests/test_retirement_production_worker.py','-q','--tb=short','--show-capture=no','-p','no:cacheprovider',check=False,timeout=100)
    print(checked.stdout.decode(errors='replace'),flush=True)
    if checked.returncode:
        print(docker('logs',worker).stderr.decode(errors='replace')[-2000:],flush=True)
    assert checked.returncode==0,'Real production worker gate failed'
    result=docker('wait',fixture,timeout=20)
    assert result.stdout.strip()==b'0','NetBox ownership verification failed'
    print('PASS actual production Compose worker + real NetBox TLS + PostgreSQL lifecycle + retained Run History',flush=True)
finally:
    if fixture_ready:
        docker('exec',fixture,'/opt/netbox/venv/bin/python','-c',
            "from pathlib import Path;p=Path('/fixture/bridge/done.json');p.exists() or p.write_text('{\"passed\": false}')",check=False)
        try: docker('wait',fixture,check=False,timeout=20)
        except subprocess.TimeoutExpired: pass
    for kind,name in reversed(created):owned_remove(kind,name)
