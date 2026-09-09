"""Opt-in actual nginx -> Unix API -> Bootstrap -> private-CA NetBox smoke."""
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import pytest
import requests
from netbox_sync.api.egress import pinned_dns

pytestmark=pytest.mark.skipif(os.environ.get('NETBOX_SYNC_TLS_DOCKER_TEST')!='1',reason='Opt-in disposable TLS Docker smoke')
ROOT=Path(__file__).parents[1]


@pytest.mark.parametrize('ingress_mode',['standalone','corporate','external'])
def test_public_https_and_private_ca_bootstrap(tmp_path,ingress_mode):
    prefix='netbox-sync-tls-smoke-'+uuid.uuid4().hex[:10]
    label='netbox-sync.tls-smoke='+prefix
    image=os.environ.get('NETBOX_SYNC_TLS_TEST_IMAGE','netbox-sync-tls-test:20260908')
    runner=os.environ.get('NETBOX_SYNC_TLS_RUNNER_IMAGE','netbox-sync-tls-tests:20260908')
    volumes={name:prefix+'-'+name for name in ('tls','ca','http','bootstrap','state','ingress','lock')}
    containers=[];created_volumes=[];created_network=False
    environment=os.environ.copy()
    environment.update(NETBOX_SYNC_COMPOSE_PROJECT=prefix,NETBOX_SYNC_IMAGE=image,
        NETBOX_SYNC_TLS_DIR='smoke-tls',NETBOX_SYNC_CA_DIR='smoke-ca',
        NETBOX_SYNC_NETBOX_SECRET_DIR='smoke-state',NETBOX_SYNC_APPLY_LOCK_DIR='smoke-lock',
        NETBOX_SYNC_INGRESS_DIR='smoke-ingress',NETBOX_SYNC_PUBLIC_HOST='sync.example.test',
        NETBOX_SYNC_TLS_TEMPLATE=str(ROOT/('deploy/nginx.corporate.conf.template' if ingress_mode=='corporate' else 'deploy/nginx.conf.template')),
        NETBOX_SYNC_POSTGRES_VOLUME=prefix+'-unused-postgres')
    fixture=tmp_path/'compose-fixture.yml'
    fixtures={'volumes':{ 'smoke-'+key:{'external':True,'name':value} for key,value in volumes.items()},
        'networks':{'netbox-sync-egress':{'external':True,'name':prefix}},
        'services':{'netbox-sync-api':{'environment':{'NETBOX_SYNC_PUBLIC_URL':'https://sync.example.test'}}}}
    fixtures['volumes'].update({'netbox-sync-http-socket':{'external':True,'name':volumes['http']},
        'netbox-sync-bootstrap-socket':{'external':True,'name':volumes['bootstrap']}})
    fixture.write_text(json.dumps(fixtures))
    ports=tmp_path/'ports.yml'
    ports.write_text('services:\n  netbox-sync-proxy:\n    ports: !override ["127.0.0.1::8443", "127.0.0.1::8080"]\n')
    compose=['docker','compose','-p',prefix,'-f',str(ROOT/'compose.production.yml')]
    compose+=['-f',str(ROOT/'compose.external-ingress.yml')] if ingress_mode=='external' else ['-f',str(ports)]
    compose+=['-f',str(fixture)]
    composed=[]
    def compose_run(*args):
        result=subprocess.run(compose+list(args),env=environment,text=True,capture_output=True)
        assert result.returncode==0,result.stderr
        return result.stdout.strip()
    def docker(*args):
        result=subprocess.run(['docker',*args],text=True,capture_output=True)
        assert result.returncode==0,result.stderr
        return (result.stdout+result.stderr).strip() if args[0]=='logs' else result.stdout.strip()
    def mount(name,path,ro=False):return ['--mount',f'type=volume,source={volumes[name]},target={path}'+(',readonly' if ro else '')]
    def launch(name,arguments,selected_image,command):
        service={'bootstrap':'netbox-sync-bootstrap-worker','api':'netbox-sync-api','inner':'netbox-sync-proxy'}.get(name)
        if name=='proxy' and ingress_mode!='external':service='netbox-sync-proxy'
        if service:
            compose_run('up','-d','--no-deps','--no-build',service)
            composed.append(service)
            container=compose_run('ps','-q',service)
            info=json.loads(docker('inspect',container))[0]
            assert info['HostConfig']['ReadonlyRootfs'] and info['HostConfig']['CapDrop']==['ALL']
            assert info['HostConfig']['Tmpfs']=={'/tmp':'size=64m,mode=1777'}
            if service!='netbox-sync-proxy':assert not info['HostConfig']['PortBindings']
            return container
        full=prefix+'-'+('outer-proxy' if name=='proxy' and ingress_mode=='external' else name)
        docker('run','-d','--name',full,'--label',label,*arguments,selected_image,*command)
        containers.append(full);return full
    try:
        for name in volumes.values():docker('volume','create','--label',label,name);created_volumes.append(name)
        docker('network','create','--label',label,prefix);created_network=True
        docker('run','--rm','--network','none','--label',label,*mount('tls','/tls'),*mount('ca','/ca'),runner,'python','-m','tests.tls_fixture')
        ca=tmp_path/'ca.pem'
        ca.write_text(docker('run','--rm','--network','none','--label',label,*mount('ca','/ca',True),image,'cat','/ca/netbox-ca.pem'))
        docker('run','--rm','--network','none','--user','0:0','--cap-drop','ALL','--cap-add','CHOWN','--label',label,
               *mount('http','/run/netbox-sync-http'),image,'python','-m','netbox_sync.web_runtime','init')
        docker('run','--rm','--network','none','--user','0:0','--label',label,*mount('state','/state'),image,
               'python','-c',"import os; os.chmod('/state',0o700)")
        netbox=launch('netbox',['--network',prefix,'--network-alias','netbox.example.test','-e','TEST_RACE='+({'standalone':'ready','corporate':'conflict','external':'provisioning'}[ingress_mode]),'-e','TEST_PREPARATION=1','-e','TEST_REVOKE_DENIED='+('1' if ingress_mode=='external' else '0'),*mount('tls','/tls',True)],runner,['python','-m','tests.mock_netbox_https'])
        bootstrap=launch('bootstrap',['--network',prefix,'--user','0:0','--read-only','--tmpfs','/tmp',
            '--cap-drop','ALL','--cap-add','CHOWN','--cap-add','SETUID','--cap-add','SETGID',
            *mount('bootstrap','/run/netbox-sync-bootstrap'),*mount('state','/var/lib/netbox-sync/netbox'),
            *mount('ca','/run/netbox-sync-ca',True),'--tmpfs','/run/netbox-sync-lock:mode=0750'],image,['python','-m','netbox_sync.bootstrap_worker'])
        api=launch('api',['--network','none','--read-only','--cap-drop','ALL','--tmpfs','/tmp',
            '-e','NETBOX_SYNC_PUBLIC_URL=https://sync.example.test',*mount('http','/run/netbox-sync-http'),
            *mount('bootstrap','/run/netbox-sync-bootstrap',True)],image,['python','-m','netbox_sync.web_runtime','serve'])
        if ingress_mode=='corporate':
            docker('run','--rm','--network','none','--user','0:0','--label',label,*mount('tls','/tls'),runner,
                'python','-c',"import shutil,os,subprocess; from pathlib import Path; "
                "shutil.copyfile('/tls/fullchain.pem','/tls/ssl.crt'); shutil.copyfile('/tls/privkey.pem','/tls/ssl.key'); "
                "subprocess.run(['openssl','genpkey','-genparam','-algorithm','DH','-pkeyopt','group:ffdhe2048','-out','/tls/dhparam.pem'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
                "[(os.chown('/tls/'+n,0,10001),Path('/tls/'+n).chmod(0o640)) for n in ('ssl.crt','ssl.key','dhparam.pem')]")
        template=ROOT/('deploy/nginx.corporate.conf.template' if ingress_mode=='corporate' else 'deploy/nginx.conf.template')
        upstream_mount=mount('http','/run/netbox-sync-http',True)
        if ingress_mode=='external':
            docker('run','--rm','--network','none','--user','0:0','--label',label,
                   *mount('ingress','/ingress'),image,'python','-c',
                   "import os; os.chmod('/ingress',0o750); os.chown('/ingress',10001,10001)")
            inner=launch('inner',['--network','none','--user','10001:10001','--read-only',
                '--cap-drop','ALL','--tmpfs','/tmp','-e','NETBOX_SYNC_PUBLIC_HOST=sync.example.test',
                *mount('http','/run/netbox-sync-http',True),*mount('ingress','/run/netbox-sync-ingress'),
                '--mount',f'type=bind,source={ROOT / "deploy/nginx.external-ingress.conf.template"},target=/etc/netbox-sync/nginx.conf.template,readonly',
                '--entrypoint','/bin/sh'],'nginx:stable-alpine',
                ['-ec', "envsubst '$NETBOX_SYNC_PUBLIC_HOST' < /etc/netbox-sync/nginx.conf.template > /tmp/nginx.conf; exec nginx -c /tmp/nginx.conf -g 'daemon off;'"])
            inner_info=json.loads(docker('inspect',inner))[0]
            assert inner_info['HostConfig']['NetworkMode']=='none'
            assert not inner_info['HostConfig']['PortBindings']
            assert '/run/netbox-sync-tls' not in {m['Destination'] for m in inner_info['Mounts']}
            # Ephemeral test-only outer TLS fixture; no deployable shared ingress is shipped.
            template=tmp_path/'outer-test.conf.template'
            template.write_text((ROOT/'deploy/nginx.conf.template').read_text().replace(
                '/run/netbox-sync-http/api.sock','/run/netbox-sync-ingress/upstream.sock'))
            upstream_mount=mount('ingress','/run/netbox-sync-ingress',True)
        proxy=launch('proxy',['--network',prefix,'--user','10001:10001','--read-only','--cap-drop','ALL','--tmpfs','/tmp',
            '-p','127.0.0.1::8443','-p','127.0.0.1::8080',
            '-e','NETBOX_SYNC_PUBLIC_HOST=sync.example.test',*upstream_mount,*mount('tls','/run/netbox-sync-tls',True),
            '--mount',f'type=bind,source={template},target=/etc/netbox-sync/nginx.conf.template,readonly',
            '--entrypoint','/bin/sh'], 'nginx:stable-alpine', ['-ec', "envsubst '$NETBOX_SYNC_PUBLIC_HOST' < /etc/netbox-sync/nginx.conf.template > /tmp/nginx.conf; exec nginx -c /tmp/nginx.conf -g 'daemon off;'"])
        info=json.loads(docker('inspect',proxy))[0]
        tls_port=int(info['NetworkSettings']['Ports']['8443/tcp'][0]['HostPort'])
        http_port=int(info['NetworkSettings']['Ports']['8080/tcp'][0]['HostPort'])
        session=requests.Session();session.trust_env=False;session.verify=str(ca)
        def request(method,path,**kwargs):
            with pinned_dns('sync.example.test','127.0.0.1',tls_port):
                return session.request(method,f'https://sync.example.test:{tls_port}'+path,
                    headers={'Host':'sync.example.test',**kwargs.pop('headers',{})},timeout=55,allow_redirects=False,**kwargs)
        for _ in range(60):
            try:
                response=request('GET','/api/v1/bootstrap')
                if response.status_code==200:break
                last='HTTP '+str(response.status_code)+' '+response.text[:100]
            except requests.RequestException as error:last=str(error)
            time.sleep(.25)
        else:raise AssertionError('Public HTTPS/Bootstrap did not start: '+last+' '+docker('logs',proxy)+docker('logs',api))
        assert response.json()['status']=='FRESH'
        redirect=session.get(f'http://127.0.0.1:{http_port}/setup',headers={'Host':'sync.example.test'},allow_redirects=False)
        assert redirect.status_code==308 and redirect.headers['Location']=='https://sync.example.test/setup'
        for path in ('/','/setup','/sources','/sources/test-source','/sources/add','/runs','/runs/test-run-id','/diagnostics','/system'):
            result=request('GET',path);assert result.status_code==200 and '<div id="root">' in result.text
        for path in ('/api/nonexistent','/assets/missing.js','/unknown-frontend-route'):assert request('GET',path).status_code==404
        import re
        assets=re.findall(r'(?:src|href)="(/assets/[^"]+)"',request('GET','/').text)
        assert len(assets)>=2
        for path in assets:
            asset=request('GET',path);assert asset.status_code==200
            assert 'text/html' not in asset.headers.get('Content-Type','')
            assert len(asset.content)>(1000 if path.endswith(('.js','.css')) else 100)
        html=request('GET','/');assert 'no-store' in html.headers['Cache-Control']
        assert re.search(r'name="netbox-sync-ui-build" content="ui-[a-f0-9]{16}"',html.text)
        for path in ('/assets/brand/mark.svg','/assets/brand/logo-light.svg','/assets/brand/logo-dark.svg','/assets/brand/icon-16.png','/assets/brand/icon-32.png','/assets/InterVariable.woff2'):
            asset=request('GET',path);assert asset.status_code==200 and 'text/html' not in asset.headers.get('Content-Type','')
        assert request('GET','/',headers={'Host':'evil.example.test'}).status_code==421
        headers={'Origin':'https://sync.example.test','X-NetBox-Sync-CSRF':'same-origin'}
        payload=dict(revision=0,url='https://netbox.example.test:8443',read_token='TEST-READ-TOKEN',apply_token='TEST-APPLY-TOKEN',replace_credentials=False)
        assert request('POST','/api/v1/bootstrap/configuration',headers={**headers,'Origin':'https://evil.example.test'},json=payload).status_code==403
        saved=request('POST','/api/v1/bootstrap/configuration',headers={**headers,'X-Forwarded-Proto':'http','Forwarded':'host=evil.example.test;proto=http'},json=payload)
        assert saved.status_code==200 and saved.json()['status']=='CONFIGURED'
        validated=request('POST','/api/v1/bootstrap/validate',headers=headers,json={'revision':1})
        assert validated.status_code==200 and validated.json()['safe_code']=='PREREQUISITES_MISSING',validated.text
        plan=request('POST','/api/v1/bootstrap/prerequisites-plan',headers=headers,json={'revision':1}).json()['preparation']
        assert len(plan['fields'])==16 and all(f['status']=='missing' for f in plan['fields'])
        operation={'revision':1,'digest':plan['digest'],'confirm':True,'setup_token':'nbt_ABCDEFGHIJKL.SETUPSECRET'}
        from concurrent.futures import ThreadPoolExecutor
        # Two real HTTP callers, one durable execution fence.
        with ThreadPoolExecutor(max_workers=1) as pool:
            first=pool.submit(request,'POST','/api/v1/bootstrap/prerequisites-apply',headers=headers,json=operation)
            for _ in range(40):
                response=request('GET','/api/v1/bootstrap')
                assert response.status_code in (200,409,423),response.text
                if response.status_code==200 and response.json()['preparation']['status']=='RUNNING':break
                time.sleep(.05)
            else:raise AssertionError('execution never entered RUNNING')
            duplicate=request('POST','/api/v1/bootstrap/prerequisites-apply',headers=headers,json=operation)
            assert duplicate.status_code in (409,423),duplicate.text
            result=first.result().json()['preparation']
        if ingress_mode!='standalone':
            assert result['status']==('CONFLICT' if ingress_mode=='corporate' else 'WAITING')
            assert result['uncertain'] is None
            from netbox_sync.prerequisites import FIELDS
            observed=json.loads(docker('exec',netbox,'cat','/tmp/observed-posts.json'))
            assert observed==list(FIELDS)[:3],observed
            assert result['fields'][3]['status']==('conflict' if ingress_mode=='corporate' else 'provisioning')
            docker('exec',netbox,'python','-c',"from pathlib import Path; Path('/tmp/resolve-race').touch()")
            plan=request('POST','/api/v1/bootstrap/prerequisites-plan',headers=headers,json={'revision':1}).json()['preparation']
            assert sum(f['status']=='ready' for f in plan['fields'])==4
            result=request('POST','/api/v1/bootstrap/prerequisites-apply',headers=headers,json={**operation,'digest':plan['digest']}).json()['preparation']
        assert result['status']=='UNCERTAIN' and result['uncertain']=='cpu_vendor'
        assert result['local_secret']=='NOT_STORED'
        docker('restart',bootstrap)
        for _ in range(60):
            state=request('GET','/api/v1/bootstrap')
            if state.status_code==200:break
            time.sleep(.1)
        plan=request('POST','/api/v1/bootstrap/prerequisites-plan',headers=headers,json={'revision':1}).json()['preparation']
        assert plan['uncertain'] is None and sum(f['status']=='ready' for f in plan['fields'])==5
        result=request('POST','/api/v1/bootstrap/prerequisites-apply',headers=headers,json={**operation,'digest':plan['digest']}).json()['preparation']
        assert result['status']=='PREPARED' and all(f['status']=='ready' for f in result['fields'])
        assert result['revocation']==('UNCONFIRMED' if ingress_mode=='external' else 'CONFIRMED')
        docker('exec',bootstrap,'python','-c',"from pathlib import Path; assert 'SETUPSECRET' not in Path('/var/lib/netbox-sync/netbox/bootstrap.json').read_text()")
        for service in (bootstrap,api,proxy):assert 'SETUPSECRET' not in docker('logs',service)
        validated=request('POST','/api/v1/bootstrap/validate',headers=headers,json={'revision':1})
        assert validated.status_code==200 and validated.json()['status']=='VALIDATED',validated.text
        assert request('POST','/api/v1/bootstrap/finish',headers=headers,json={'revision':1}).json()['status']=='READY'
        assert 'TEST-READ-TOKEN' not in request('GET','/api/v1/bootstrap').text
        assert not json.loads(docker('inspect',api))[0]['HostConfig']['PortBindings']
        docker('exec',api,'python','-m','netbox_sync.web_runtime','health')
        docker('exec',api,'python','-c',"import socket; s=socket.socket(); assert s.connect_ex(('127.0.0.1',8000)) != 0")
        if ingress_mode=='external':
            # An unrelated local UID cannot even connect, regardless of forged headers.
            docker('run','--rm','--network','none','--user','10002:10002','--cap-drop','ALL','--label',label,
                   *mount('ingress','/run/netbox-sync-ingress',True),image,'python','-c',
                   "import socket; s=socket.socket(socket.AF_UNIX); assert s.connect_ex('/run/netbox-sync-ingress/upstream.sock')==13")
            # A trusted socket peer still cannot supply the wrong authority or scheme.
            for host,scheme in (('evil.example.test','https'),('sync.example.test','http')):
                docker('run','--rm','--network','none','--user','10001:10001','--cap-drop','ALL','--label',label,
                       *mount('ingress','/run/netbox-sync-ingress',True),image,'python','-c',
                       "import socket; s=socket.socket(socket.AF_UNIX); s.connect('/run/netbox-sync-ingress/upstream.sock'); "
                       + 's.sendall(' + repr(('GET /api/v1/bootstrap HTTP/1.0\r\nHost: '+host
                       +'\r\nX-Forwarded-Proto: '+scheme+'\r\n\r\n').encode())
                       + "); assert s.recv(4096).split()[1] in (b'403',b'421')")
            docker('restart',inner)
            for _ in range(30):
                if request('GET','/api/v1/bootstrap').status_code==200:break
                time.sleep(.1)
            else:raise AssertionError('external socket did not recover after restart')
        # Invalid operator material must prevent all nginx listeners, including health.
        docker('stop',proxy)
        docker('run','--rm','--network','none','--user','0:0','--label',label,
               *mount('tls','/tls'),image,'python','-c',
               "from pathlib import Path; Path('/tls/"+('ssl.crt' if ingress_mode=='corporate' else 'fullchain.pem')+"').write_text('invalid certificate')")
        docker('start',proxy)
        for _ in range(60):
            logs=docker('logs',proxy)
            if 'cannot load certificate' in logs or 'PEM_read_bio' in logs:break
            time.sleep(.1)
        else:raise AssertionError('missing nginx invalid-certificate rejection')
        health=subprocess.run(['docker','exec',proxy,'wget','-q','--spider','http://127.0.0.1:8081/health'],capture_output=True)
        assert health.returncode!=0
    finally:
        if composed:compose_run("down", "--volumes")
        for name in reversed(containers):
            info=json.loads(docker('inspect',name))[0]
            assert info['Config']['Labels'].get('netbox-sync.tls-smoke')==prefix
            docker('rm','-f',name)
        for name in reversed(created_volumes):
            info=json.loads(docker('volume','inspect',name))[0]
            assert info['Labels'].get('netbox-sync.tls-smoke')==prefix
            docker('volume','rm',name)
        if created_network:docker('network','rm',prefix)
