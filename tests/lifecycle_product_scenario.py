"""Full isolated production Compose lifecycle; never a live-host entrypoint.

Invoked by run_retirement_production_worker with exact owned fixture metadata.
No backup, dump, restore, SQL repair or runtime journal edits.
"""
import hashlib,json,os,secrets,shutil,socket,http.client,subprocess,sys,time
from pathlib import Path
from uuid import uuid4
sys.path.insert(0,'/review')
from deploy import install,reinstall_inventory
root,project,relay=Path(sys.argv[1]),sys.argv[2],sys.argv[3]
assert project.startswith('netbox-sync-retirement-') and root.name=='product'
assert root.parent==Path(os.environ['FIXTURE_MOUNT'])
image=os.environ['NETBOX_SYNC_REVIEW_IMAGE']
meta=json.loads(Path('/fixture/bridge/ready.json').read_text())
fixture=root.parent/'provider';fixture.mkdir(mode=0o755,exist_ok=True)
def run(args,**kwargs):
 result=subprocess.run(args,capture_output=True,text=True,**kwargs)
 if result.returncode:raise RuntimeError('Isolated command failed '+args[0]+': '+result.stderr[-1800:])
 return result.stdout.strip()
run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(fixture/'server.key'),'-out',str(fixture/'server.crt'),'-subj','/CN=esxi.probe.test','-addext','subjectAltName=DNS:esxi.probe.test'])
(fixture/'server.key').chmod(0o600);(fixture/'server.crt').chmod(0o644)
peer=project+'-provider'
review_bind=next(m['Source'] for m in json.loads(run(['docker','inspect',project+'-operator']))[0]['Mounts'] if m['Destination']=='/review')
cookie='';password=secrets.token_urlsafe(32);provider_secret=secrets.token_urlsafe(32)
class UnixHTTP(http.client.HTTPConnection):
 def connect(self):
  self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(220);self.sock.connect(str(root/'ingress/upstream.sock'))
def request(path,body=None,method=None,timeout=None):
 c=UnixHTTP('sync.example.test',timeout=220)
 if timeout is not None:
  c.connect();c.sock.settimeout(timeout)
 c.request(method or ('GET' if body is None else 'POST'),path,None if body is None else json.dumps(body),headers={'Host':'sync.example.test','Origin':'https://sync.example.test','X-Forwarded-Proto':'https','X-NetBox-Sync-CSRF':'same-origin','Content-Type':'application/json','Cookie':cookie})
 r=c.getresponse();data=r.read();result={'status':r.status,'body':json.loads(data),'cookie':r.getheader('Set-Cookie')};c.close();return result

def ok(path,body=None,method=None):
 value=request(path,body,method)
 assert value['status'] in (200,201),(path,value['status'],value['body'].get('error',{}))
 return value['body']
def wait_ready():
 for _ in range(80):
  try:
   if request('/api/v1/health')['status']==200:return
  except (OSError,ValueError):pass
  time.sleep(.5)
 raise AssertionError('Product ingress health unavailable')

def prepare(release,source=Path('/review'),selected_image=image):
 install.initialize_tls_layout(root)
 p=install.prepare_layout(root,source,release,selected_image)
 install.configure_tls(p,'https://sync.example.test');install.configure_ingress(p,'external');install.initialize_ingress_directory(root)
 install._atomic_write(p.config/'compose.env',install._merged_config(p.config/'compose.env',{},dict(NETBOX_SYNC_COMPOSE_PROJECT=project,NETBOX_SYNC_POSTGRES_VOLUME=project+'-db',NETBOX_SYNC_APPLY_LOCK_DIR=str(root.parent/'runtime'),NETBOX_SYNC_GUARD_INSTANCE=meta['guard_instance'])))
 (root/'secrets/ca/netbox-ca.pem').write_bytes(Path('/fixture/ca/netbox-ca.pem').read_bytes());(root/'secrets/ca/netbox-ca.pem').chmod(0o644)
 # Trust only the synthetic provider CA in the real probe/sync processes.
 overlay=root.parent/'product-fixture.yml'
 overlay.write_text(json.dumps({'services':{s:{'volumes':[{'type':'bind','source':str(fixture/'server.crt'),'target':target,'read_only':True} for target in ('/etc/ssl/certs/ca-certificates.crt','/usr/local/lib/python3.12/site-packages/certifi/cacert.pem')]} for s in ('netbox-sync-probe-worker','netbox-sync-apply-worker','netbox-sync-scheduler')}}))
 return p,overlay

def grant_once():
 namespace=(root/'state/installation-id').read_text().strip()
 Path('/fixture/bridge/installation.json').write_text(json.dumps({'namespace':namespace}))
 for _ in range(100):
  ack=Path('/fixture/bridge/installation-ready.json')
  if ack.exists() and json.loads(ack.read_text())['namespace']==namespace:return namespace
  time.sleep(.1)
 raise AssertionError('Isolated NetBox operator grant unavailable')

def launch(p,overlay):
 global command
 install.publish_configuration(p);install.activate_release(root,p.release)
 command=install.compose_command(root,overrides=(overlay,))
 run([*command,'up','-d','postgres']);install._wait_for_postgres(root,p.release,root/'config')
 for service in ('netbox-sync-db-roles','netbox-sync-migrate','netbox-sync-db-grants','netbox-sync-http-init'):
  run([*command,'--profile','tools','run','--rm','--no-deps',service])
 run([*command,'create','--no-build',*install._runtime_services()])
 run(['docker','network','connect','--alias','guard-netbox.test',project+'_netbox-sync-egress',relay])
 run(['docker','run','-d','--name',peer,'--user','0:0','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true','--label','netbox-sync.task='+project,'--network',project+'_netbox-sync-probe-egress','--network-alias','esxi.probe.test','--mount','type=bind,source='+str(fixture)+',target=/fixture,readonly','--mount','type=bind,source='+review_bind+',target=/review,readonly','-e','PYTHONPATH=/review',image,'python','/review/tests/lifecycle_provider_fixture.py'])
 run(['docker','network','connect','--alias','esxi.probe.test',project+'_netbox-sync-egress',peer])
 time.sleep(.5)
 peer_state=json.loads(run(['docker','inspect',peer]))[0]['State']
 assert peer_state['Running'], ('Synthetic provider startup',peer_state['ExitCode'],run(['docker','logs',peer])[-1000:])
 install.start_runtime(p,overrides=(overlay,));wait_ready()

def setup():
 global cookie
 assert request('/api/v1/sources')['status']==401
 invitation=json.loads(run([*command,'exec','-T','--user','0','netbox-sync-auth-worker','python','-m','netbox_sync.auth_worker','invite']))['invitation']
 enrolled=request('/api/v1/auth/enroll',dict(username='admin',password=password,invitation=invitation));assert enrolled['status']==200
 cookie=enrolled['cookie'].split(';')[0]
 state=ok('/api/v1/bootstrap');assert state['status']=='FRESH'
 tokens=json.loads(Path('/fixture/tokens.json').read_text())
 state=ok('/api/v1/bootstrap/configuration',dict(revision=state['revision'],url='https://guard-netbox.test:8443',read_token=tokens['read'],apply_token=tokens['apply']))
 state=ok('/api/v1/bootstrap/validate',dict(revision=state['revision']));assert state['safe_code'] is None,('bootstrap',state['safe_code'],state['access_checks'])
 state=ok('/api/v1/bootstrap/finish',dict(revision=state['revision']));assert state['status']=='READY'
 assert ok('/api/v1/sources')['sources']==[]
 policy=ok('/api/v1/policy')
 assert policy['mode']=='legacy'  # unchanged default permits private RFC1918 destinations
 print('PASS fresh production ingress -> enrollment -> NetBox setup -> zero sources',flush=True)

def add(provider,name,restart=False):
 name=name+' '+project
 checked=ok('/api/v1/sources/test-connection',dict(source_type=provider,address='esxi.probe.test',port=8443,verify_ssl=True,username='netbox-sync@pve' if provider=='proxmox' else 'netbox-sync',secret=provider_secret,preview=True,**({'token_id':'independent-token-name'} if provider=='proxmox' else {})))
 sid=checked['suggested_source_instance']
 refs={kind:next(r for r in ok('/api/v1/catalog/'+kind)['items'] if r.get('slug')==meta['catalog_slug']) for kind in ('site','platform','device_role','cluster_type')}
 dtype=next(r for r in ok('/api/v1/catalog/device_type')['items'] if r.get('slug')==meta['catalog_slug'])
 host_types={h['id']:dtype for h in checked['preview']['hosts']}
 payload=dict(registration_id=str(uuid4()),source_type=provider,source_instance=sid,name=name,address='esxi.probe.test',port=8443,verify_ssl=True,sync_interval_seconds=60,confirm_sync_disabled=True,onboarding_token=checked['onboarding_token'],references=refs,host_types=host_types,create_cluster=True,site_slug=meta['catalog_slug'],cluster_name=name,platform_slug=meta['catalog_slug'],device_role_slug=meta['catalog_slug'],device_type_slug=meta['catalog_slug'],cluster_type_slug=meta['catalog_slug'])
 if restart:
  Path('/fixture/bridge/refuse-creation').touch()
 result=request('/api/v1/sources',payload)
 if restart:
  assert result['status']!=201 and Path('/fixture/bridge/creation-refused').exists()
  run([*command,'stop','netbox-sync-api'])
  Path('/fixture/bridge/refuse-creation').unlink()
  run([*command,'start','netbox-sync-api']);wait_ready()
 if result['status']!=201:
  for _ in range(60):
   state=ok('/api/v1/sources/registration-status',dict(source_instance=sid,registration_id=payload['registration_id']))
   if state['status']=='REGISTERED':break
   time.sleep(.5)
  else:raise AssertionError(('Registration did not continue',result['status'],state))
 assert len([s for s in ok('/api/v1/sources')['sources'] if s['source_instance']==sid])==1
 if restart:
  clusters=ok('/api/v1/catalog/cluster?search='+__import__('urllib.parse',fromlist=['quote']).quote(name))['items']
  assert len([c for c in clusters if c['name']==name])==1
  print('PASS staged registration completes after transient cluster refusal and API restart, exactly one cluster',flush=True)
 # Exact repeated final request resolves the same source without another cluster.
 if (root/'current').resolve().name!='product-fresh':
  assert request('/api/v1/sources',payload)['status']==201
 return sid

def plan(sid):
 result=request('/api/v1/sources/'+sid+'/sync-plan',{})
 if result['status']!=200:
  logs=subprocess.run(['docker','logs',project+'-apply-worker'],capture_output=True,text=True)
  for line in (logs.stdout+logs.stderr).splitlines():
   try:event=json.loads(line[line.index('{'):])
   except (ValueError,TypeError):continue
   if isinstance(event,dict) and 'frames' in event:
    import re
    safe={k:v for k,v in event.items() if k in ('code','exception_class') and isinstance(v,str) and re.fullmatch('[A-Za-z_]{1,100}',v)}
    safe['frames']=[{k:v for k,v in f.items() if k in ('module','function') and isinstance(v,str) and re.fullmatch('[A-Za-z_]{1,100}',v) or k=='line' and type(v)is int} for f in event['frames'][:8] if isinstance(f,dict)]
    print('SAFE WORKER FAILURE',json.dumps(safe),flush=True)
  raise AssertionError(('plan',result['status'],result['body']))
 return result['body']
def apply(sid,planned):
 base='/api/v1/sources/'+sid
 operation=next(o for o in ok(base+'/operations')['operations'] if o['operation_kind']=='PLAN' and o['status']=='READY')
 confirmation=ok(base+'/sync-confirmations',dict(plan_digest=planned['digest'],operation_id=operation['operation_id'],confirmed=True))
 response=request(base+'/sync',dict(confirmation_token=confirmation['confirmation_token'],operation_id=operation['operation_id'],run_id=str(uuid4())))
 if response['status']!=200:
  logs=subprocess.run(['docker','logs',project+'-apply-worker'],capture_output=True,text=True)
  import re
  for line in (logs.stdout+logs.stderr).splitlines():
   try:event=json.loads(line[line.index('{'):])
   except (ValueError,TypeError):continue
   if isinstance(event,dict) and 'frames' in event:
    safe={k:v for k,v in event.items() if k in ('code','exception_class','phase') and isinstance(v,str) and re.fullmatch('[A-Za-z_]{1,100}',v)}
    safe['frames']=[{k:v for k,v in frame.items() if k in ('module','function') and isinstance(v,str) and re.fullmatch('[A-Za-z_]{1,100}',v) or k=='line' and type(v)is int} for frame in event['frames'][:8] if isinstance(frame,dict)]
    print('SAFE APPLY FAILURE',json.dumps(safe),flush=True)
  raise AssertionError(('apply',response['status'],response['body'].get('error',{})))
 result=response['body']
 assert result['status']=='SUCCEEDED',('apply',result['status'])

def remove(sid,wait_for_plan=False):
 base='/api/v1/sources/'+sid
 if wait_for_plan:
  run(['docker','exec',peer,'python','-c',"import requests;requests.post('https://127.0.0.1:8443/fixture/hold-next-inventory',verify='/fixture/server.crt',timeout=5).raise_for_status()".replace('127.0.0.1','esxi.probe.test')])
  pending=request(base+'/operations/plan',{})
  assert pending['status']==202 and pending['body']['status']=='RUNNING'
 life=ok(base+'/lifecycle');operation=str(uuid4())
 ok(base+'/removal-request',dict(operation_id=operation,revision=life['revision'],confirmed=True))
 if wait_for_plan:
  blocked=request(base+'/operations/plan',{})
  assert blocked['status']==409,(blocked['status'],blocked['body'])
  assert blocked['body']['error']['code']=='SOURCE_RETIREMENT_PENDING'
  run([*command,'restart','netbox-sync-lifecycle-worker'])
 # Server owns all continuation. Browser/fixture performs status-only reads.
 for _ in range(160):
  result=request(base+'/removal-status',dict(operation_id=operation))
  if result['status']==503 and result['body'].get('error',{}).get('code') in ('BOOTSTRAP_BUSY','BOOTSTRAP_UNAVAILABLE','LIFECYCLE_UNAVAILABLE','RETIREMENT_UNAVAILABLE'):
   time.sleep(.5);continue # retry only a read; never replay removal consent
  assert result['status']==200,('removal status',result['status'],result['body'])
  state=result['body']
  assert state['state']!='BLOCKED',('removal',state.get('safe_code'))
  if state['state']=='FINALIZED' and state.get('purged'):break
  time.sleep(.5)
 else:raise AssertionError('Removal deadline')
 assert all(s['source_instance']!=sid for s in ok('/api/v1/sources')['sources'])
 assert not ok('/api/v1/runs?source_instance='+sid)['runs']

p,overlay=prepare('product-fresh',Path('/baseline'),os.environ['NETBOX_SYNC_BASELINE_IMAGE']);namespace=grant_once();launch(p,overlay);setup()
first=add('esxi','AM isolated')
planned=plan(first);assert any(i['action']=='CREATE' for i in planned['items']) and planned['apply_allowed']
assert any(i['reason_code']=='IP_OBSERVATION_ONLY' for i in planned['items'])
apply(first,planned)
repeat=plan(first);assert not any(i['action'] in ('CREATE','UPDATE') for i in repeat['items'])
print('PASS AM production SOAP 8443 -> plan -> prepare/apply -> unchanged replan, conflicting IP observations',flush=True)
# Upgrade through supported installer component path; same persistent root/DB.
before={str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (root/'secrets').rglob('*') if f.is_file()}
db=run([*command,'ps','-q','postgres']);mounts=json.loads(run(['docker','inspect',db]))[0]['Mounts']
policy=ok('/api/v1/policy');runs=ok('/api/v1/runs');sources=ok('/api/v1/sources')
p,overlay=prepare('product-upgrade')
staged=install.compose_command(root,release=p.release,config=p.config,overrides=(overlay,))
for service in ('netbox-sync-db-roles','netbox-sync-migrate','netbox-sync-db-grants'):
 run([*staged,'--profile','tools','run','--rm','--no-deps',service])
install.activate_prepared(p,install_units=False,start_services=False);install.start_runtime(p,overrides=(overlay,));wait_ready()
assert run([*command,'ps','-q','postgres'])==db, 'PostgreSQL container changed'
assert {m['Destination']:m for m in json.loads(run(['docker','inspect',db]))[0]['Mounts']}=={m['Destination']:m for m in mounts}, 'PostgreSQL mount definition changed'
assert before=={str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (root/'secrets').rglob('*') if f.is_file()}
assert ok('/api/v1/policy')==policy and ok('/api/v1/runs')==runs and ok('/api/v1/sources')==sources
assert (root/'state/installation-id').read_text().strip()==namespace
print('PASS installer component upgrade retains volume, credentials, onboarding, policy, sources and history',flush=True)
def scheduled(sid):
 base='/api/v1/sources/'+sid
 current=ok(base+'/schedule')
 ok(base+'/schedule',dict(sync_enabled=True,sync_interval_seconds=60,expected_sync_enabled=current['sync_enabled'],expected_sync_interval_seconds=current['sync_interval_seconds']),'PATCH')
 result=subprocess.run(['flock','-n','/run/netbox-sync/apply.lock',*command,'--profile','scheduled','run','--rm','--no-deps','netbox-sync-scheduler'],capture_output=True,text=True,timeout=180)
 assert provider_secret not in result.stdout+result.stderr
 assert result.returncode==0,('scheduler',result.stderr[-1000:])
 records=ok('/api/v1/runs?source_instance='+sid+'&trigger=scheduled')['runs'];assert len(records)==1
 assert records[0]['status']=='SUCCEEDED' and records[0]['plan_digest'] and records[0]['planner_version']
 assert records[0]['actions']['create']==records[0]['actions']['update']==0
 current=ok(base+'/schedule')
 ok(base+'/schedule',dict(sync_enabled=False,sync_interval_seconds=60,expected_sync_enabled=current['sync_enabled'],expected_sync_interval_seconds=current['sync_interval_seconds']),'PATCH')
 print('PASS real scheduler after manual sync: no-op, digest and definite result',flush=True)
scheduled(first)
if os.environ.get('NETBOX_SYNC_LARGE_RETIREMENT')=='1':
 Path('/fixture/bridge/grow-retirement.json').write_text(json.dumps({'source':first}))
 for _ in range(1200):
  if Path('/fixture/bridge/grew-retirement.json').exists():break
  time.sleep(.1)
 else:raise AssertionError('Large fixture inventory not ready')
 size=json.loads(Path('/fixture/bridge/grew-retirement.json').read_text())
 assert size['vms']>=276 and size['objects']>=1099
 base='/api/v1/sources/'+first;life=ok(base+'/lifecycle');nonce=str(uuid4())
 reviewed=ok(base+'/retirement-review',dict(operation_id=nonce,revision=life['revision']))
 assert len(reviewed['manifest']['objects'])==size['objects']
 Path('/fixture/bridge/capture-retirement').touch();Path('/fixture/bridge/hold-retirement').touch()
 payload=dict(operation_id=nonce,digest=reviewed['digest'],confirmed=True,confirmed_source=life['display_name'],remove_credentials=True)
 try:request(base+'/retire',payload,timeout=.1)
 except (TimeoutError,socket.timeout):pass
 else:raise AssertionError('Client interruption did not occur')
 for _ in range(300):
  if Path('/fixture/bridge/retirement-in-transaction').exists():break
  time.sleep(.1)
 else:raise AssertionError('Guard did not enter the real delete transaction')
 # Disconnect/restart the production HTTP worker while NetBox still owns its
 # atomic transaction. No altered timeout or capabilities in product Compose.
 run([*command,'restart','netbox-sync-bootstrap-worker'])
 Path('/fixture/bridge/hold-retirement').unlink(missing_ok=True)
 run([*command,'restart','netbox-sync-lifecycle-worker'])
 for _ in range(240):
  result=request(base+'/retirement-status',dict(operation_id=nonce))
  if result['status']==503:time.sleep(.5);continue
  assert result['status']==200,result['status']
  state=result['body'];assert state['state']!='BLOCKED',state.get('safe_code')
  if state['state']=='FINALIZED' and state.get('purged'):break
  time.sleep(.5)
 else:raise AssertionError('Large retirement did not reconcile after restart')
 assert set(Path('/fixture/bridge/retirement-calls').read_text().splitlines())=={nonce}
 assert all(s['source_instance']!=first for s in ok('/api/v1/sources')['sources'])
 assert not ok('/api/v1/runs?source_instance='+first)['runs']
 assert ok(base+'/retire',payload)['state']=='FINALIZED'  # repeat original click
 Path('/fixture/bridge/capture-retirement').unlink()
 print('PASS production large removal '+json.dumps(size)+': timed-out client, NetBox transaction, worker/lifecycle restart, same nonce receipt, complete purge',flush=True)
else:remove(first,wait_for_plan=True)
second=add('esxi','AM isolated',restart=True);assert second!=first
apply(second,plan(second));assert not any(i['action'] in ('CREATE','UPDATE') for i in plan(second)['items']);remove(second,wait_for_plan=True)
missing=add('esxi','Missing cluster isolated')
base='/api/v1/sources/'+missing
life=ok(base+'/lifecycle');nonce=str(uuid4())
review=ok(base+'/retirement-review',dict(operation_id=nonce,revision=life['revision']))
Path('/fixture/bridge/remove-empty-cluster.json').write_text(json.dumps({'source':missing}))
for _ in range(100):
 if Path('/fixture/bridge/removed-empty-cluster.json').exists():break
 time.sleep(.1)
else:raise AssertionError('Isolated manual cluster removal did not finish')
Path('/fixture/bridge/refuse-retirement').touch()
result=ok(base+'/retire',dict(operation_id=nonce,digest=review['digest'],confirmed=True,confirmed_source=life['display_name'],remove_credentials=True))
assert result['state']=='UNCERTAIN'
run([*command,'stop','netbox-sync-lifecycle-worker'])
Path('/fixture/bridge/refuse-retirement').unlink()
run([*command,'start','netbox-sync-lifecycle-worker'])
for _ in range(100):
 if result['state']=='FINALIZED' and result.get('purged'):break
 time.sleep(.5)
 response=request(base+'/retirement-status',dict(operation_id=nonce))
 if response['status']==503:continue
 assert response['status']==200,response['status']
 result=response['body']
else:raise AssertionError(('Missing cluster did not finalize',result['state']))
assert all(s['source_instance']!=missing for s in ok('/api/v1/sources')['sources'])
again=add('esxi','After missing cluster');assert again!=missing
# Also exercise disappearance BEFORE Sync's first removal review.
Path('/fixture/bridge/remove-empty-cluster.json').write_text(json.dumps({'source':again}))
Path('/fixture/bridge/removed-empty-cluster.json').unlink()
for _ in range(100):
 if Path('/fixture/bridge/removed-empty-cluster.json').exists():break
 time.sleep(.1)
else:raise AssertionError('Second isolated external cluster deletion did not finish')
remove(again)
last=add('esxi','After absent review');assert last not in (again,missing);remove(last)
print('PASS public API add -> external empty cluster delete -> original-nonce retirement/full purge -> same-host re-add',flush=True)
pve=add('proxmox','PVE isolated');apply(pve,plan(pve));assert not any(i['action'] in ('CREATE','UPDATE') for i in plan(pve)['items']);scheduled(pve);remove(pve)
print('PASS full server removal and same-host fresh registration; Proxmox VM/LXC manual cycle',flush=True)
# Exact own-project reset only. Preserve separately managed NetBox fixture and TLS.
assert not ok('/api/v1/sources')['sources']
netbox_state=json.loads(run(['docker','inspect',relay]))[0]['Id']
assert json.loads(run(['docker','inspect',peer]))[0]['Config']['Labels']['netbox-sync.task']==project
run(['docker','rm','-f',peer]);run(['docker','network','disconnect',project+'_netbox-sync-egress',relay])
model=json.loads(run([*command,'--profile','legacy-workers','config','--format','json']))
def inspect(kind,ids):return json.loads(run(['docker',kind,'inspect',*ids])) if ids else []
report=reinstall_inventory.report(root,model,inspect('container',run(['docker','ps','-aq']).split()),inspect('volume',run(['docker','volume','ls','-q']).split()),inspect('network',run(['docker','network','ls','-q']).split()))
assert not report['blockers'],report['blockers']
run([*command,'--profile','legacy-workers','down','--volumes'])
assert root.resolve()==root and root.parent==Path(os.environ['FIXTURE_MOUNT']) and not root.is_symlink()
assert not any(m.get('Source','').startswith(str(root)+'/') for c in inspect('container',run(['docker','ps','-aq']).split()) for m in c['Mounts'])
shutil.rmtree(root) # exact isolated product root, never checkout or external fixture
cookie=''
p,overlay=prepare('product-reinstalled');fresh=grant_once();assert fresh!=namespace
launch(p,overlay);setup()
assert json.loads(run(['docker','inspect',relay]))[0]['Id']==netbox_state
assert not ok('/api/v1/registration-attempts')['attempts']
third=add('esxi','AM isolated');assert third not in (first,second)
apply(third,plan(third));assert not any(i['action'] in ('CREATE','UPDATE') for i in plan(third)['items']);scheduled(third);remove(third)
print('PASS Sync-only clean reinstall: new namespace/DB, external NetBox/TLS retained, fresh enrollment and same-host add/remove',flush=True)
