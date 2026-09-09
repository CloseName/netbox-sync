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
OLD='897de2a79a6781129f84cbbdcaef9b250795deb7'
root,project=Path(sys.argv[1]),sys.argv[2]
assert project.startswith('netbox-sync-auth-upgrade-')
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
assert db('SELECT version_num FROM netbox_sync.alembic_version')=='0005_source_tombstones'
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
before=snapshot();pg=run([*command,'ps','-q','postgres']);mounts=run(['docker','inspect',pg,'--format','{{json .Mounts}}'])
rows=db('SELECT row_to_json(s) FROM netbox_sync.sources s');history=db('SELECT row_to_json(s) FROM netbox_sync.sync_runs s')
run(['python3',str(root/'current/deploy/backup.py'),'--root',str(root),'--no-systemd','create'])
bundle=next((root/'backups').glob('netbox-sync-backup-*'))
for action in ('verify','inspect'):
    run(['python3',str(root/'current/deploy/backup.py'),'--root',str(root),'--no-systemd',action,str(bundle)])
assert snapshot()==before and (root/'current').resolve().name==OLD
upgrade=['python3','/review/deploy/install.py','--root',str(root),'--source','/review','--release-id','auth-upgrade','--image','netbox-sync-auth:review','--no-systemd']
refused=subprocess.run(upgrade,capture_output=True,text=True)
assert refused.returncode==1 and '--acknowledge-admin-enrollment' in refused.stderr
assert snapshot()==before and (root/'current').resolve().name==OLD
run([*upgrade,'--acknowledge-admin-enrollment'])
assert (root/'current').resolve().name=='auth-upgrade'
assert db('SELECT version_num FROM netbox_sync.alembic_version')=='0006_auth_policy'
assert rows==db('SELECT row_to_json(s) FROM netbox_sync.sources s') and history==db('SELECT row_to_json(s) FROM netbox_sync.sync_runs s')
assert run([*command,'ps','-q','postgres'])==pg and run(['docker','inspect',pg,'--format','{{json .Mounts}}'])==mounts
for path,value in before.items():
    if path!='config/compose.env':assert hashlib.sha256((root/path).read_bytes()).digest()==value,path
auth_environment=dict(line.split('=',1) for line in (root/'config/auth.env').read_text().splitlines() if '=' in line)
assert all(auth_environment.get(key)==value for key,value in inherited_policy.items())
# Unit generation is tested separately; this harness cannot prove timer/reboot behavior.
invite_dir=root/'state/admin';invite_dir.mkdir(mode=0o700)
file=invite_dir/'invitation'
out=run(['python3','/review/deploy/auth.py','--root',str(root),'--invitation-file',str(file),'invite'])
invitation=file.read_text().strip();assert invitation not in out and file.stat().st_mode & 0o777 == 0o600
client="""import sys,json,http.client,socket
p=json.load(sys.stdin)
class C(http.client.HTTPConnection):
 def connect(self):
  self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.connect('/run/netbox-sync-http/api.sock')
c=C('sync.example.test');c.request(p['method'],p['path'],json.dumps(p['body']),headers={'Host':'sync.example.test','Origin':'https://sync.example.test','X-Forwarded-Proto':'https','X-NetBox-Sync-CSRF':'same-origin','Content-Type':'application/json'})
r=c.getresponse();print(r.status)
"""
def http(method,path,body=None):return run([*command,'exec','-T','--user','10001','netbox-sync-api','python','-c',client],input=json.dumps(dict(method=method,path=path,body=body)))
assert http('GET','/api/v1/sources')=='401'
assert http('POST','/api/v1/auth/enroll',dict(username='admin',password=secrets.token_urlsafe(32),invitation=invitation))=='200'
assert json.loads(db('SELECT value FROM netbox_sync.auth_state'))['mode']=='legacy'
run(['python3','/review/deploy/auth.py','--root',str(root),'--ceiling','public-ipv4','managed'])
assert json.loads(db('SELECT value FROM netbox_sync.auth_state'))['ceiling']=='public-ipv4'
print('PASS pre-auth 897de2a -> auth: real installer, DB volume/credentials/READY/source/history/schedule retained; no-systemd harness; explicit enrollment guard/root CLI/HTTP enrollment; no anonymous administrator',flush=True)
