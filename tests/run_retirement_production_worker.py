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
assert info['Config']['Labels'].get('netbox-sync.task')==os.environ.get('NETBOX_SYNC_GUARD_PG_LABEL','host-claims-20260923')
assert info['HostConfig']['NetworkMode']=='none'
project='netbox-sync-retirement-'+uuid4().hex[:12]
label='netbox-sync.task='+project
network=project+'-network';volume=project+'-fixture'
fixture=project+'-netbox';proxy=project+'-relay';worker=project+'-bootstrap-worker'
created=[];fixture_ready=False
full=os.environ.get('NETBOX_SYNC_FULL_LIFECYCLE')=='1'
product_project=project+'-product'

def clean_product():
    if not full:return
    for kind,listing in [('container',('ps','-aq')),('network',('network','ls','-q')),('volume',('volume','ls','-q'))]:
        for identifier in docker(*listing,'--filter','label=com.docker.compose.project='+product_project).stdout.decode().split():
            found=json.loads(docker(*(('inspect',identifier) if kind=='container' else (kind,'inspect',identifier))).stdout)[0]
            labels=found['Config']['Labels'] if kind=='container' else found['Labels']
            assert labels.get('com.docker.compose.project')==product_project
            docker(*(('rm','-f',identifier) if kind=='container' else (kind,'rm',identifier)))
    for identifier in docker('ps','-aq','--filter','label=netbox-sync.task='+product_project).stdout.decode().split():
        found=json.loads(docker('inspect',identifier).stdout)[0]
        assert found['Config']['Labels']['netbox-sync.task']==product_project
        docker('rm','-f',identifier)


def owned_remove(kind,name):
    found=docker(*(('inspect',name) if kind=='container' else (kind,'inspect',name)),check=False)
    if found.returncode:return
    data=json.loads(found.stdout)[0]
    labels=data['Config']['Labels'] if kind=='container' else data['Labels']
    assert labels.get('netbox-sync.task')==project
    docker(*(('rm','-f',name) if kind=='container' else (kind,'rm',name)))

try:
    if full:
        # Each full clean-install rehearsal requires an actually empty NetBox DB.
        # Failed older rehearsals may retain protected objects in their own DB.
        pg=project+'-postgres'
        docker('run','-d','--name',pg,'--label',label,'--network','none',
            '--tmpfs','/var/lib/postgresql/data:size=512m',
            '-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_DB=netbox_sync_test','postgres:16-bookworm')
        created.append(('container',pg))
        deadline=time.monotonic()+40
        while docker('exec',pg,'pg_isready','-U','postgres',check=False).returncode:
            if time.monotonic()>deadline:raise AssertionError('Isolated PostgreSQL not ready')
            time.sleep(.2)
    docker('network','create','--internal','--label',label,network);created.append(('network',network))
    docker('volume','create','--label',label,volume);created.append(('volume',volume))
    redis=project+'-redis'
    docker('run','-d','--name',redis,'--label',label,'--network','container:'+pg,
        '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true',
        '--user','999:999','--tmpfs','/data:size=32m,mode=1777',
        'redis:7-alpine','redis-server','--save','','--appendonly','no')
    created.append(('container',redis))
    docker('run','-d','--name',fixture,'--label',label,'--user','0:0','--network','container:'+pg,
        '--mount','type=bind,source='+str(root)+',target=/app,readonly',
        '--mount','type=bind,source='+str(root/'tests/netbox_guard_plugins.py')+',target=/etc/netbox/config/plugins.py,readonly',
        '--mount','type=volume,source='+volume+',target=/fixture',
        '-e','PYTHONPATH=/app/deploy','-e','NETBOX_SYNC_ISOLATED_MODEL_TEST=1',
        '-e','NETBOX_SYNC_FULL_LIFECYCLE='+('1' if full else '0'),
        '-e','NETBOX_SYNC_LARGE_RETIREMENT='+os.environ.get('NETBOX_SYNC_LARGE_RETIREMENT','0'),
        '-e','NETBOX_SYNC_MODEL_DB=netbox_sync_guard_test','-e','NETBOX_SYNC_GUARD_WORKER_TEST=1',
        '--entrypoint','/opt/netbox/venv/bin/python','netboxcommunity/netbox:v4.7.0','/app/tests/netbox_guard_http_scenario.py')
    created.append(('container',fixture))
    print('Preparing isolated real NetBox fixture',flush=True)
    deadline=time.monotonic()+900 # cold NetBox migration budget; worker timeouts stay unchanged
    while True:
        value=docker('exec',fixture,'cat','/fixture/bridge/ready.json',check=False)
        if value.returncode==0:
            meta=json.loads(value.stdout);fixture_ready=True;break
        state=json.loads(docker('inspect',fixture).stdout)[0]['State']
        if not state['Running']:
            logs=docker('logs',fixture)
            raise AssertionError('NetBox fixture exited '+str({key:state[key] for key in ('ExitCode','OOMKilled')})+': '+(logs.stdout+logs.stderr).decode(errors='replace')[-2400:])
        if time.monotonic()>deadline:raise AssertionError('NetBox fixture preparation deadline')
        time.sleep(1)
    assert set(meta)=={'guard_instance','source','cluster','direct_url','catalog_slug','vrfs'}
    docker('run','-d','--name',proxy,'--label',label,'--user','10001:10001','--read-only',
        '--cap-drop','ALL','--security-opt','no-new-privileges:true','--network',network,'--network-alias','guard-netbox.test',
        '--mount','type=volume,source='+volume+',target=/bridge,volume-subpath=bridge,readonly',
        '--mount','type=bind,source='+str(root/'tests/retirement_bridge.py')+',target=/relay.py,readonly',
        '--entrypoint','python',os.environ.get('NETBOX_SYNC_REVIEW_IMAGE','netbox-sync-retirement:20260923'),'-B','/relay.py')
    created.append(('container',proxy))
    if full:
        # Operator-only Docker socket, never part of product Compose. Exact
        # project-scoped mounts and cleanup; no privileged container or live host.
        mount=json.loads(docker('volume','inspect',volume).stdout)[0]['Mountpoint']
        operator=product_project+'-operator'
        docker('run','--rm','--user','0:0','--network','none','--label',label,'--mount','type=volume,source='+volume+',target=/fixture',
            '--entrypoint','python',os.environ['NETBOX_SYNC_REVIEW_IMAGE'],'-c',"from pathlib import Path;Path('/fixture/runtime').mkdir(mode=0o750)")
        docker('run','-d','--name',operator,'--label',label,'--network','none',
            '--mount','type=volume,source='+volume+',target='+mount,
            '--mount','type=volume,source='+volume+',target=/fixture',
            '--mount','type=bind,source='+mount+'/runtime,target=/run/netbox-sync',
            '--mount','type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock',
            '--mount','type=bind,source='+str(root)+',target=/review,readonly','netbox-sync-probe-host:review')
        created.append(('container',operator))
        baseline=subprocess.run(['git','archive','f6d297f6a6610a8fb7390faa6a7827f4cb4f4539'],cwd=root,capture_output=True,check=True).stdout
        docker('exec',operator,'mkdir','/baseline')
        docker('exec','-i',operator,'tar','-xf','-','-C','/baseline',input=baseline)
        print('Running isolated full product lifecycle / upgrade / reinstall',flush=True)
        result=docker('exec','-e','NETBOX_SYNC_PAM_IDENTITIES='+os.environ.get('NETBOX_SYNC_PAM_IDENTITIES','0'),'-e','NETBOX_SYNC_LARGE_RETIREMENT='+os.environ.get('NETBOX_SYNC_LARGE_RETIREMENT','0'),'-e','FIXTURE_MOUNT='+mount,'-e','NETBOX_SYNC_REVIEW_IMAGE='+os.environ['NETBOX_SYNC_REVIEW_IMAGE'],
            '-e','NETBOX_SYNC_BASELINE_IMAGE=netbox-sync-lifecycle:f6d297f-baseline',operator,'python3','/review/tests/lifecycle_product_scenario.py',mount+'/product',product_project,proxy,check=False,timeout=1400)
        print(result.stdout.decode(errors='replace'),flush=True)
        if result.returncode:print(result.stderr.decode(errors='replace')[-3500:],flush=True)
        # Detach the separately managed NetBox relay before deleting own networks.
        attached=json.loads(docker('inspect',proxy).stdout)[0]['NetworkSettings']['Networks']
        for name in attached:
            if name.startswith(product_project+'_'):docker('network','disconnect',name,proxy)
        # Provider peer has test-task ownership, not a product Compose service.
        for identifier in docker('ps','-aq','--filter','label=netbox-sync.task='+product_project).stdout.decode().split():docker('rm','-f',identifier)
        clean_product()
        assert result.returncode==0,'Full product lifecycle gate failed'
    mounts=[{'type':'volume','source':'retirement-fixture','target':target,'read_only':readonly,'volume':{'subpath':subpath}}
            for subpath,target,readonly in [('worker','/run/netbox-sync-retirement',False),('bootstrap','/run/netbox-sync-bootstrap',False),('lock','/run/netbox-sync-lock',False),('config','/var/lib/netbox-sync/netbox',False),('ca','/run/netbox-sync-ca',True)]]
    # JSON is valid YAML; the explicit !override is necessary to replace only
    # fixture paths, while retaining the actual production security/command.
    override='services:\n  netbox-sync-bootstrap-worker:\n    labels: '+json.dumps({'netbox-sync.task':project})+'\n    volumes: !override '+json.dumps(mounts)+'\n'
    broker_mounts=[{'type':'volume','source':'retirement-fixture','target':target,'volume':{'subpath':subpath}}
        for subpath,target in [('broker','/run/netbox-sync-broker'),('auth-socket','/run/netbox-sync-auth-secrets'),
                              ('source-secrets','/var/lib/netbox-sync/source-secrets'),('auth-secrets','/var/lib/netbox-sync/auth-secrets')]]
    override+='  netbox-sync-secret-broker:\n    labels: '+json.dumps({'netbox-sync.task':project})+'\n    volumes: !override '+json.dumps(broker_mounts)+'\n'
    override+='networks:\n  netbox-sync-egress: '+json.dumps({'external':True,'name':network})+'\n'
    override+='volumes:\n  retirement-fixture: '+json.dumps({'external':True,'name':volume})+'\n'
    with tempfile.TemporaryDirectory(prefix=project) as directory:
        path=Path(directory)/'fixture.yml';path.write_text(override)
        env=dict(os.environ,NETBOX_SYNC_COMPOSE_PROJECT=project,NETBOX_SYNC_IMAGE=os.environ.get('NETBOX_SYNC_REVIEW_IMAGE','netbox-sync-retirement:20260923'),
                 NETBOX_SYNC_GUARD_INSTANCE=meta['guard_instance'])
        compose=['compose','--project-name',project,'-f',str(root/'compose.production.yml'),'-f',str(path)]
        model=json.loads(docker(*compose,'config','--format','json',env=env).stdout)['services']['netbox-sync-bootstrap-worker']
        assert model['command']==['python','-m','netbox_sync.worker_supervisor','netbox']
        assert model['read_only'] and model['cap_drop']==['ALL'] and set(model['cap_add'])=={'CHOWN','SETUID','SETGID','KILL'}
        assert not model.get('ports') and set(model['networks'])=={'netbox-sync-egress'}
        created.append(('container',worker))
        created.append(('container',project+'-secret-broker'))
        docker(*compose,'up','-d','--no-deps','netbox-sync-bootstrap-worker','netbox-sync-secret-broker',env=env)
        broker_info=json.loads(docker('inspect',project+'-secret-broker').stdout)[0]
        assert broker_info['HostConfig']['NetworkMode']=='none' and not broker_info['HostConfig']['PortBindings']
    deadline=time.monotonic()+15
    while (docker('exec',fixture,'test','-S','/fixture/worker/worker.sock',check=False).returncode or docker('exec',fixture,'test','-S','/fixture/broker/broker.sock',check=False).returncode):
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
        '--mount','type=volume,source='+volume+',target=/broker,volume-subpath=broker,readonly',
        '--mount','type=volume,source='+volume+',target=/fixture-sources,volume-subpath=source-secrets,readonly',
        '--mount','type=volume,source='+volume+',target=/fixture-config,volume-subpath=config,readonly',
        '--mount','type=volume,source='+volume+',target=/fixture-ca,volume-subpath=ca,readonly',
        '-e','PYTHONDONTWRITEBYTECODE=1','-e','NETBOX_SYNC_GUARD_WORKER_TEST=1',
        '-e','NETBOX_SYNC_TEST_POSTGRES_DSN=host=127.0.0.1 dbname=netbox_sync_test user=postgres',
        '-w','/app','--entrypoint','python','netbox-sync-retirement-tests:20260923','-m','pytest',
        'tests/test_retirement_production_worker.py','-q','--tb=short','--show-capture=no','-p','no:cacheprovider',check=False,timeout=220)
    print(checked.stdout.decode(errors='replace'),flush=True)
    if checked.returncode:
        print(docker('logs',worker).stderr.decode(errors='replace')[-2000:],flush=True)
    assert checked.returncode==0,'Real production worker gate failed'
    result=docker('wait',fixture,timeout=20)
    assert result.stdout.strip()==b'0','NetBox ownership verification failed'
    print('PASS actual production Compose worker + real NetBox TLS + PostgreSQL lifecycle + complete source purge',flush=True)
finally:
    if full:
        found=docker('inspect',proxy,check=False)
        if found.returncode==0:
            for name in json.loads(found.stdout)[0]['NetworkSettings']['Networks']:
                if name.startswith(product_project+'_'):docker('network','disconnect',name,proxy)
        # End only this fixture's provider before its network.
        for identifier in docker('ps','-aq','--filter','label=netbox-sync.task='+product_project).stdout.decode().split():docker('rm','-f',identifier)
        clean_product()
    if fixture_ready:
        docker('exec',fixture,'/opt/netbox/venv/bin/python','-c',
            "from pathlib import Path;p=Path('/fixture/bridge/done.json');p.exists() or p.write_text('{\"passed\": false}')",check=False)
        try: docker('wait',fixture,check=False,timeout=20)
        except subprocess.TimeoutExpired: pass
    for kind,name in reversed(created):owned_remove(kind,name)
