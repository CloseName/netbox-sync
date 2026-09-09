"""Opt-in real production Compose rename: preserve PostgreSQL volume and credentials."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import uuid
import pytest

ROOT=Path(__file__).parents[1]

@pytest.mark.skipif(os.environ.get('NETBOX_SYNC_NAMING_DOCKER_TEST')!='1', reason='opt-in disposable production Compose naming smoke')
def test_old_auto_name_to_canonical_preserves_database(tmp_path):
    project='netbox-sync-naming-smoke-'+uuid.uuid4().hex[:10]
    environment=os.environ.copy()
    environment.update(NETBOX_SYNC_COMPOSE_PROJECT=project,
        NETBOX_SYNC_POSTGRES_VOLUME=project+'-postgres-data',NETBOX_SYNC_INFRA_SECRET_DIR=str(tmp_path), NETBOX_SYNC_INGRESS_DIR=str(tmp_path/'ingress'))
    password=tmp_path/'postgres_bootstrap_password'
    password.write_text(secrets.token_hex(32));original=password.read_bytes()
    # The only difference in the old model is the absence of explicit names.
    old=tmp_path/'old.yml'
    old.write_text('\n'.join(line for line in (ROOT/'compose.production.yml').read_text().splitlines()
        if not line.lstrip().startswith('container_name:'))+'\n')
    def command(file,*args):
        return ['docker','compose','--project-directory',str(ROOT),'-p',project,'-f',str(file),
            '-f',str(ROOT/'compose.external-ingress.yml'),*args]
    def run(args):
        result=subprocess.run(args,env=environment,text=True,capture_output=True)
        assert result.returncode==0,result.stderr
        return result.stdout.strip()
    def sql(file,query):
        # Password remains in container memory, never interpolated into host command/output.
        return run(command(file,'exec','-T','postgres','sh','-ec',
            'export PGPASSWORD="$(cat /run/secrets/postgres_bootstrap_password)"; exec psql -h 127.0.0.1 -U netbox_sync_bootstrap -d netbox_sync -At -v ON_ERROR_STOP=1 -c "$1"','sh',query))
    current=ROOT/'compose.production.yml'
    def ready(file):
        for _ in range(60):
            result=subprocess.run(command(file,'exec','-T','postgres','pg_isready','-h','127.0.0.1','-U','netbox_sync_bootstrap','-d','netbox_sync'),env=environment,capture_output=True)
            if result.returncode==0:return
            time.sleep(.5)
        pytest.fail('disposable postgres did not become ready')
    try:
        run(command(old,'up','-d','--no-deps','postgres'));ready(old)
        previous=run(command(old,'ps','-q','postgres'))
        info=json.loads(run(['docker','inspect',previous]))[0]
        assert info['Name']=='/'+project+'-postgres-1'
        before=[m['Name'] for m in info['Mounts'] if m['Destination']=='/var/lib/postgresql/data']
        sql(old,"CREATE TABLE rehearsal_marker (value text); INSERT INTO rehearsal_marker VALUES ('retained')")
        run(command(current,'up','-d','--no-deps','postgres'));ready(current)
        after=run(command(current,'ps','-q','postgres'))
        info=json.loads(run(['docker','inspect',after]))[0]
        assert after!=previous and info['Name']=='/'+project+'-postgres'
        assert [m['Name'] for m in info['Mounts'] if m['Destination']=='/var/lib/postgresql/data']==before
        assert not info['HostConfig']['PortBindings']
        assert sql(current,'SELECT value FROM rehearsal_marker')=='retained'
        assert password.read_bytes()==original
        assert len(run(command(current,'ps','-q','postgres')).splitlines())==1
    finally:
        run(command(current,'down','--volumes'))


@pytest.mark.skipif(os.environ.get('NETBOX_SYNC_NAMING_DOCKER_TEST')!='1', reason='opt-in disposable production Compose naming smoke')
def test_fresh_all_services_and_foreign_name_fail_closed(tmp_path):
    from deploy import install
    from types import SimpleNamespace
    project='netbox-sync-fresh-smoke-'+uuid.uuid4().hex[:10]
    image=os.environ.get('NETBOX_SYNC_TLS_TEST_IMAGE','netbox-sync-onboarding-smoke:20260909')
    root=tmp_path/'root';(root/'secrets'/'infrastructure').mkdir(parents=True)
    install.generate_configuration(root,image)
    envfile=root/'config'/'compose.env'
    envfile.write_text(envfile.read_text().replace('NETBOX_SYNC_COMPOSE_PROJECT=netbox-sync','NETBOX_SYNC_COMPOSE_PROJECT='+project))
    environment=os.environ.copy()
    environment.update(NETBOX_SYNC_COMPOSE_PROJECT=project,NETBOX_SYNC_IMAGE=image,
        NETBOX_SYNC_CONFIG_DIR=str(root/'config'),NETBOX_SYNC_POSTGRES_VOLUME=project+'-postgres-data',
        NETBOX_SYNC_INFRA_SECRET_DIR='fixture-infra',NETBOX_SYNC_SOURCE_SECRET_DIR='fixture-sources',
        NETBOX_SYNC_NETBOX_SECRET_DIR='fixture-netbox',NETBOX_SYNC_CA_DIR='fixture-ca',
        NETBOX_SYNC_APPLY_LOCK_DIR='fixture-lock',NETBOX_SYNC_INGRESS_DIR='fixture-ingress',NETBOX_SYNC_PUBLIC_HOST='sync.example.test')
    volumes={key:project+'-'+key for key in ('infra','sources','netbox','ca','lock','ingress')}
    fixture=tmp_path/'fixture.json'
    fixture.write_text(json.dumps({'volumes':{'fixture-'+key:{'external':True,'name':value} for key,value in volumes.items()},
        'secrets':{'postgres_bootstrap_password':{'file':str(root/'secrets/infrastructure/postgres_bootstrap_password')}},
        'services':{'netbox-sync-api':{'environment':{'NETBOX_SYNC_PUBLIC_URL':'https://sync.example.test'}}}}))
    compose=['docker','compose','-p',project,'-f',str(ROOT/'compose.production.yml'),'-f',str(ROOT/'compose.external-ingress.yml'),'-f',str(fixture)]
    def run(args):
        result=subprocess.run(args,env=environment,text=True,capture_output=True)
        assert result.returncode==0,result.stderr
        return result.stdout.strip()
    foreign=project+'-api';foreign_id=None;created=[]
    try:
        foreign_id=run(['docker','run','-d','--network','none','--name',foreign,'--label','netbox-sync.test-owner='+project,image,'sleep','300'])
        before=json.loads(run(['docker','inspect',foreign_id]))[0]
        with pytest.raises(install.ContainerNameConflict,match=foreign):install.validate_container_names(SimpleNamespace(config=root/'config'))
        after=json.loads(run(['docker','inspect',foreign_id]))[0]
        assert after['Id']==before['Id'] and after['State']['Running'] and after['Config']==before['Config']
        run(['docker','rm','-f',foreign_id]);foreign_id=None
        for value in volumes.values():run(['docker','volume','create','--label','netbox-sync.test-owner='+project,value]);created.append(value)
        args=['docker','run','--rm','--network','none','--user','0:0','-v',str(root/'secrets/infrastructure')+':/input:ro']
        for key,value in volumes.items():args+=['-v',value+':/fixture/'+key]
        script="import os,shutil; from pathlib import Path; [Path('/fixture/'+k).chmod(0o700) for k in ('infra','sources','netbox')]; [shutil.copyfile(p,Path('/fixture/infra')/p.name) for p in Path('/input').iterdir()]; [p.chmod(0o600) for p in Path('/fixture/infra').iterdir()]; os.chown('/fixture/ingress',10001,10001); Path('/fixture/ingress').chmod(0o750)"
        run(args+[image,'python','-c',script])
        install.validate_container_names(SimpleNamespace(config=root/'config'))
        run(compose+['up','-d','postgres'])
        for _ in range(60):
            if subprocess.run(compose+['exec','-T','postgres','pg_isready','-h','127.0.0.1','-U','netbox_sync_bootstrap'],env=environment,capture_output=True).returncode==0:break
            time.sleep(.25)
        for service in ('netbox-sync-db-roles','netbox-sync-migrate','netbox-sync-db-grants','netbox-sync-http-init'):
            run(compose+['--profile','tools','run','--rm','--no-deps',service])
        services=list(install._runtime_services())
        run(compose+['up','-d','--no-build',*services])
        for _ in range(60):
            if subprocess.run(compose+['exec','-T','netbox-sync-api','python','-m','netbox_sync.web_runtime','health'],env=environment,capture_output=True).returncode==0:break
            time.sleep(.25)
        else:pytest.fail('fresh production API health unavailable')
        ids=run(compose+['ps','-q']).splitlines()
        assert len(ids)==9
        records=json.loads(run(['docker','inspect',*ids]))
        assert {r['Name'] for r in records}=={'/'+project+'-'+s.removeprefix('netbox-sync-') for s in ['postgres',*services]}
        for record in records:
            assert record['State']['Running'] and not record['HostConfig']['PortBindings']
            assert not any(m['Destination']=='/var/run/docker.sock' for m in record['Mounts'])
        broker=next(r for r in records if r['Name'].endswith('-secret-broker'))
        assert broker['HostConfig']['NetworkMode']=='none'
        assert not any('DSN=' in e for e in broker['Config']['Env'])
        locks=[next(m['Name'] for m in r['Mounts'] if m['Destination']=='/run/netbox-sync-lock') for r in records if any(m['Destination']=='/run/netbox-sync-lock' for m in r['Mounts'])]
        assert len(locks)==3 and set(locks)=={volumes['lock']}
        probe="import socket,json; s=socket.socket(socket.AF_UNIX); s.connect('/run/netbox-sync-http/api.sock'); s.sendall(b'GET /api/v1/bootstrap HTTP/1.0\\r\\nHost: sync.example.test\\r\\nX-Forwarded-Proto: https\\r\\n\\r\\n'); raw=b''; part=s.recv(65536); exec('while part: raw+=part; part=s.recv(65536)'); assert json.loads(raw.split(b'\\r\\n\\r\\n',1)[1])['status']=='FRESH'"
        run(compose+['exec','-T','netbox-sync-api','python','-c',probe])
    finally:
        if foreign_id:run(['docker','rm','-f',foreign_id])
        run(compose+['down','--volumes'])
        for value in reversed(created):
            assert json.loads(run(['docker','volume','inspect',value]))[0]['Labels']['netbox-sync.test-owner']==project
            run(['docker','volume','rm',value])
