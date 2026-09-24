"""Real old -> new installation, pre-upgrade backup, root enrollment."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
sys.path.insert(0,'/old-source')
from deploy import install
OLD='5acd4c12d62c62072049b22f98e22d19a980a5af'
root,project=Path(sys.argv[1]),sys.argv[2]
assert project.startswith('netbox-sync-ldap-upgrade-')
assert importlib.util.find_spec('psycopg') is None

def run(args,**kwargs):
    r=subprocess.run(args,capture_output=True,text=True,**kwargs)
    if r.returncode:raise RuntimeError('Fixture command failed: '+args[0]+'\n'+r.stderr[-2000:])
    return r.stdout.strip()

install.initialize_tls_layout(root)
p=install.prepare_layout(root,Path('/old-source'),OLD,project+':old')
install.configure_tls(p,'https://sync.example.test');install.configure_ingress(p,'external')
install.initialize_ingress_directory(root)
install._atomic_write(p.config/'compose.env',install._merged_config(p.config/'compose.env',{},
    {'NETBOX_SYNC_COMPOSE_PROJECT':project,'NETBOX_SYNC_POSTGRES_VOLUME':project+'-db',
     'NETBOX_SYNC_APPLY_LOCK_DIR':str(root.parent/'runtime')}))
inherited_policy={'NETBOX_SYNC_ONBOARDING_ALLOWED_CIDRS':'10.77.0.0/16','NETBOX_SYNC_ONBOARDING_ALLOWED_HOSTS':'retained.example.test','NETBOX_SYNC_ONBOARDING_DENIED_CIDRS':'10.77.3.0/24'}
install._atomic_write(p.config/'api.env',install._merged_config(p.config/'api.env',inherited_policy))
install.prepare_stack(p);install.publish_configuration(p);install.activate_release(root,p.release)
install.start_runtime(p)
command=install.compose_command(root)
def db(query):return run([*command,'exec','-T','postgres','psql','-U','netbox_sync_bootstrap','-d','netbox_sync','-At','--set','ON_ERROR_STOP=1'],input=query)
assert db('SELECT version_num FROM netbox_sync.alembic_version')=='0006_auth_policy'
db("""INSERT INTO netbox_sync.sources(id,source_instance,name,source_type,address,enabled,sync_enabled,
sync_interval_seconds,verify_ssl,site_slug,device_role_slug,platform_slug,device_type_slug,cluster_type_slug,
cluster_name,username,token_id_provider,token_id_key,token_secret_provider,token_secret_key,legacy_identity_owner,settings)
VALUES('retained','retained','Retained','esxi','provider.invalid',false,false,600,true,'test','server','esxi','server','esxi','Test','netbox-sync','file','retained','file','retained',false,'{}');
INSERT INTO netbox_sync.sync_runs(run_id,source_instance,source_type,trigger,started_at,finished_at,duration_ms,status,created_by)
VALUES('00000000-0000-0000-0000-000000000001','retained','esxi','manual',now(),now(),1,'SUCCEEDED','operator');""")
(root/'secrets/sources/retained').write_text(secrets.token_urlsafe(32));(root/'secrets/sources/retained').chmod(0o600)
state=dict(format=1,revision=2,status='READY',completed=True,url='https://netbox.example.test',read_token='read-token',apply_token='apply-token',validated_at=time.time(),safe_code=None,checks=[])
for name,value in [('bootstrap.json',json.dumps(state)),('read-token',secrets.token_urlsafe(32)),('apply-token',secrets.token_urlsafe(32))]:
    path=root/'secrets/netbox'/name;path.write_text(value);path.chmod(0o600)
def snapshot():return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).digest() for d in ('config','secrets') for p in (root/d).rglob('*') if p.is_file()}

CLIENT="import http.client,json,socket,sys\nclass UnixHTTP(http.client.HTTPConnection):\n def connect(self):\n  self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(25);self.sock.connect('/run/netbox-sync-http/api.sock')\npayload=json.load(sys.stdin); c=UnixHTTP('sync.example.test',timeout=25)\nc.request(payload.get('method','POST'),payload['path'],json.dumps(payload['body']) if payload['body'] is not None else None,headers={'Content-Type':'application/json','Host':'sync.example.test','Origin':'https://sync.example.test','X-Forwarded-Proto':'https','X-NetBox-Sync-CSRF':'same-origin','Cookie':payload.get('cookie','')})\nr=c.getresponse();print(json.dumps({'status':r.status,'body':json.loads(r.read()),'cookie':r.getheader('Set-Cookie')}))\n"
session_cookie=''
def compose(*args): return run([*command,*args])
def request(body,path='/api/v1/sources/test-connection',method='POST'):
    return json.loads(run([*command,'exec','-T','--user','10001','netbox-sync-api','python','-c',CLIENT],
        input=json.dumps({'path':path,'body':body,'cookie':session_cookie,'method':method})))
for _ in range(60):
    check=subprocess.run([*command,'exec','-T','netbox-sync-api','python','-m','netbox_sync.web_runtime','health'],capture_output=True)
    if check.returncode==0: break
    time.sleep(.5)
else: raise RuntimeError('Old API not ready')
invitation=json.loads(compose('exec','-T','netbox-sync-auth-worker','python','-m','netbox_sync.auth_worker','invite'))['invitation']
password=secrets.token_urlsafe(32)
response=request(dict(username='admin',password=password,invitation=invitation),'/api/v1/auth/enroll')
assert response['status']==200
session_cookie=response['cookie'].split(';')[0]
old_identity=request(None,'/api/v1/auth/me','GET')['body']['principal_id']
auth_before=json.loads(db('SELECT value FROM netbox_sync.auth_state'))

before=snapshot();pg=run([*command,'ps','-q','postgres']);mounts=sorted(json.loads(run(['docker','inspect',pg,'--format','{{json .Mounts}}'])),key=lambda item:item['Destination'])
rows=db('SELECT row_to_json(s) FROM netbox_sync.sources s');history=db('SELECT row_to_json(s) FROM netbox_sync.sync_runs s')
run(['python3',str(root/'current/deploy/backup.py'),'--root',str(root),'--no-systemd','create'])
bundle=next((root/'backups').glob('netbox-sync-backup-*'))
for action in ('verify','inspect'):
    run(['python3',str(root/'current/deploy/backup.py'),'--root',str(root),'--no-systemd',action,str(bundle)])
assert snapshot()==before and (root/'current').resolve().name==OLD

upgrade=['python3','/review/deploy/install.py','--root',str(root),'--source','/new-source',
    '--release-id','ldap-upgrade','--image',os.environ.get('NETBOX_SYNC_REVIEW_IMAGE','netbox-sync-auth:review'),'--no-systemd']
run(upgrade)
assert (root/'current').resolve().name=='ldap-upgrade'
assert db('SELECT version_num FROM netbox_sync.alembic_version')=='0012_run_reconciliation'
assert db('SELECT row_to_json(s) FROM netbox_sync.sources s')==rows
assert db('SELECT row_to_json(s) FROM netbox_sync.sync_runs s')==history
assert run([*command,'ps','-q','postgres'])==pg
assert sorted(json.loads(run(['docker','inspect',pg,'--format','{{json .Mounts}}'])),key=lambda item:item['Destination'])==mounts
for path,digest in before.items():
    if path.startswith('secrets/'):
        assert hashlib.sha256((root/path).read_bytes()).digest()==digest
assert json.loads(db('SELECT value FROM netbox_sync.auth_state'))['principal']==auth_before['principal']
for _ in range(60):
    try:
        if request(None,'/api/v1/auth/me','GET')['status']==200: break
    except RuntimeError: pass
    time.sleep(.5)
else: raise RuntimeError('Session lost on upgrade')
assert request(None,'/api/v1/auth/me','GET')['body']['principal_id']==old_identity
exec(compile(Path('/review/tests/ldap_compose_scenario.py').read_text(),'ldap_compose_scenario.py','exec'))
ldap_state=json.loads(db('SELECT value FROM netbox_sync.auth_state'))['ldap']
ldap_files={p.name:hashlib.sha256(p.read_bytes()).digest() for p in (root/'secrets/auth').iterdir()}
second=list(upgrade);second[second.index('ldap-upgrade')]='ldap-upgrade-2'
run(second)
assert json.loads(db('SELECT value FROM netbox_sync.auth_state'))['ldap']==ldap_state
assert {p.name:hashlib.sha256(p.read_bytes()).digest() for p in (root/'secrets/auth').iterdir()}==ldap_files
for _ in range(60):
    try:
        if request(None,'/api/v1/auth/me','GET')['status']==200: break
    except RuntimeError: pass
    time.sleep(.5)
else: raise RuntimeError('Emergency login session lost')
assert request(None,'/api/v1/settings/ldap','GET')['body']==ldap_saved
assert db('SELECT row_to_json(s) FROM netbox_sync.sources s')==rows
assert db('SELECT row_to_json(s) FROM netbox_sync.sync_runs s')==history
assert run([*command,'ps','-q','postgres'])==pg
print('PASS upgrade 5acd4c12 -> prepared release: existing administrator/session, source/schedule/history, READY, credentials, DB volume retained; LDAP settings/bind files retained across second upgrade',flush=True)
