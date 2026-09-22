"""Disposable Linux host scenario: real production API -> isolated probe -> HTTPS/SOAP."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from uuid import uuid4
sys.path.insert(0, '/review')
from deploy import install

root, project, pgmode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
assert project.startswith('netbox-sync-probe-test-')
image = os.environ.get('NETBOX_SYNC_REVIEW_IMAGE','netbox-sync-auth:review')

def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError('Fixture command failed: ' + args[0] + '\n' + result.stderr[-1500:])
    return result.stdout.strip()

install.initialize_tls_layout(root)
p = install.prepare_layout(root, Path('/review'), 'probe-review', image)
install.configure_tls(p, 'https://sync.example.test')
install.configure_ingress(p, 'external')
install.initialize_ingress_directory(root)
install._atomic_write(p.config / 'compose.env', install._merged_config(p.config / 'compose.env', {},
    {'NETBOX_SYNC_COMPOSE_PROJECT': project, 'NETBOX_SYNC_POSTGRES_VOLUME': project + '-db', 'NETBOX_SYNC_APPLY_LOCK_DIR':str(root.parent/'runtime')}))
# Start in a deliberately restrictive inherited policy. The controlled HTTPS
# endpoint is outside it; web permission must be a separate, authenticated write.
install._atomic_write(p.config/'auth.env', install._merged_config(p.config/'auth.env', {
    'NETBOX_SYNC_ONBOARDING_ALLOWED_CIDRS':'10.77.0.0/16'}))
install.publish_configuration(p)
install.activate_release(root, p.release)
# A completed, protected onboarding fixture; source-probe tests do not bypass API gating.
value = dict(format=1, revision=2, status='READY', completed=True, url='https://netbox.example.test',
             read_token=secrets.token_urlsafe(32), apply_token=secrets.token_urlsafe(32), validated_at=time.time(),
             safe_code=None, checks=[])
bootstrap = root / 'secrets/netbox/bootstrap.json'
bootstrap.write_text(json.dumps(value))
bootstrap.chmod(0o600)
fixture = root / 'state/fixture'
fixture.mkdir()
catalog_token=secrets.token_urlsafe(32)
(fixture/'catalog-token').write_text(catalog_token)
(fixture/'catalog-token').chmod(0o600)
(fixture/'registration-token').write_text(value['apply_token'])
(fixture/'registration-token').chmod(0o600)
run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
     '-keyout', str(fixture / 'server.key'), '-out', str(fixture / 'server.crt'),
     '-subj', '/CN=esxi.probe.test', '-addext', 'subjectAltName=DNS:esxi.probe.test,DNS:slow.probe.test,DNS:netbox.example.test'])
(fixture / 'server.key').chmod(0o600)
(fixture / 'server.crt').chmod(0o644)
(root/'secrets/ca/netbox-ca.pem').write_bytes((fixture/'server.crt').read_bytes())
(root/'secrets/ca/netbox-ca.pem').chmod(0o644)
overlay = root / 'state/fixture.yml'
overlay.write_text(json.dumps({'networks':{'netbox-sync-probe-egress':{'ipam':{'config':[{'subnet':'93.184.216.0/24'}]}}},'services': {'netbox-sync-probe-worker': {'volumes': [
    {'type':'bind','source':str(fixture / 'server.crt'),'target':'/etc/ssl/certs/ca-certificates.crt','read_only':True}]}}}))
overrides = [root / 'current/compose.external-postgres.yml'] if pgmode == 'external' else []
command = install.compose_command(root, overrides=(*overrides, overlay))
def compose(*args): return run([*command, *args])
compose('config', '--quiet')
if pgmode == 'bundled':
    compose('up', '-d', 'postgres')
    install._wait_for_postgres(root, p.release, root / 'config')
else:
    # Create the production networks, without starting bundled PostgreSQL.
    compose('create', '--no-build', 'netbox-sync-api')
    run(['docker','volume','create','--label','com.docker.compose.project='+project,project+'-external-db'])
    run(['docker', 'run', '-d', '--name', project + '-external-db', '--network', project + '_netbox-sync-egress',
         '--network-alias', 'postgres', '--label', 'com.docker.compose.project=' + project,
         '--mount', 'type=volume,source=' + project + '-external-db,target=/var/lib/postgresql/data',
         '--mount', 'type=bind,source=' + str(root / 'secrets/infrastructure/postgres_bootstrap_password') + ',target=/run/secrets/password,readonly',
         '-e', 'POSTGRES_PASSWORD_FILE=/run/secrets/password', '-e', 'POSTGRES_USER=netbox_sync_bootstrap',
         '-e', 'POSTGRES_DB=netbox_sync', 'postgres:16-bookworm'])
    for _ in range(40):
        ready = subprocess.run(['docker','exec',project+'-external-db','pg_isready','-h','127.0.0.1','-U','netbox_sync_bootstrap','-d','netbox_sync'],capture_output=True)
        if ready.returncode == 0: break
        time.sleep(1)
    else: raise RuntimeError('External fixture DB not ready')
for service in ('netbox-sync-db-roles','netbox-sync-migrate','netbox-sync-db-grants','netbox-sync-http-init'):
    compose('--profile','tools','run','--rm','--no-deps',service)
compose('up','-d','--no-build',*install._runtime_services())
for _ in range(40):
    health = subprocess.run([*command,'exec','-T','netbox-sync-api','python','-m','netbox_sync.web_runtime','health'],capture_output=True)
    if health.returncode == 0: break
    time.sleep(1)
else: raise RuntimeError('API not ready')
worker = compose('ps','-q','netbox-sync-probe-worker')
api = compose('ps','-q','netbox-sync-api')
info = json.loads(run(['docker','inspect',worker]))[0]
assert set(info['NetworkSettings']['Networks']) == {project+'_netbox-sync-probe-egress'}
assert not info['HostConfig']['PortBindings']
auth_info=json.loads(run(['docker','inspect',compose('ps','-q','netbox-sync-auth-worker')]))[0]
assert not auth_info['HostConfig']['PortBindings']
assert auth_info['HostConfig']['Memory']==192*1024*1024
assert not any('/secrets/' in m['Destination'] or 'docker.sock' in m['Destination'] for m in auth_info['Mounts'])
assert set(auth_info['NetworkSettings']['Networks'])=={project+('_netbox-sync-db' if pgmode=='bundled' else '_netbox-sync-egress'),project+'_netbox-sync-ldap-egress'}
assert next(m for m in auth_info['Mounts'] if m['Destination']=='/var/lib/netbox-sync/auth-secrets')['RW'] is False

assert info['HostConfig']['ReadonlyRootfs'] and info['HostConfig']['CapDrop'] == ['ALL']
assert {cap.removeprefix('CAP_') for cap in info['HostConfig']['CapAdd']} == {'SETUID','SETGID','CHOWN','KILL'}, info['HostConfig']['CapAdd']
assert not info['HostConfig']['Privileged'] and not info['HostConfig']['PidMode']
assert info['HostConfig']['Tmpfs'] == {'/tmp':'size=64m,mode=1777'}
assert any(option.startswith('no-new-privileges') for option in info['HostConfig']['SecurityOpt'])
assert not any('DSN=' in entry or 'TOKEN=' in entry for entry in info['Config']['Env'])
assert not any('/secrets/' in mount['Destination'] or 'docker.sock' in mount['Destination'] for mount in info['Mounts'])
# Whole-process timeout must kill/reap a UID-10001 child under actual container caps.
compose('exec','-T','netbox-sync-probe-worker','python','-c', """import subprocess,sys,time,os
import netbox_sync.api.connection_probe as probe
from netbox_sync.application.onboarding import PendingCredentials,OnboardingError
probe.PROBE_DEADLINE=.1
children=[]
def sleeper(args, **kwargs):
 child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(1)'],**kwargs)
 children.append(child);return child
started=time.monotonic()
try: probe.run_connection_test(PendingCredentials('esxi','esxi.example.test',True,'netbox-sync','',''),popen=sleeper,child_uid=10001)
except OnboardingError as error: assert error.code.value=='SOURCE_TIMEOUT',error.code.value
else: raise AssertionError('Missing timeout')
assert time.monotonic()-started < .9
assert children[0].returncode == -9
try: os.waitpid(children[0].pid,os.WNOHANG)
except ChildProcessError: pass
else: raise AssertionError('Child not reaped')
""")
api_info = json.loads(run(['docker','inspect',api]))[0]
assert not api_info['HostConfig']['PortBindings']
if pgmode == 'bundled': assert set(api_info['NetworkSettings']['Networks']) == {project+'_netbox-sync-db'}
broker = json.loads(run(['docker','inspect',compose('ps','-q','netbox-sync-secret-broker')]))[0]
assert broker['HostConfig']['NetworkMode'] == 'none'
run(['docker','run','-d','--name',project+'-endpoint','--label','com.docker.compose.project='+project,
     '--user','0:0','--network',project+'_netbox-sync-probe-egress','--network-alias','esxi.probe.test',
     '--network-alias','slow.probe.test','--network-alias','wrong.probe.test',
     '--mount','type=bind,source='+str(fixture)+',target=/fixture,readonly',
     '--mount','type=bind,source='+str(root / 'current/tests/probe_https_fixture.py')+',target=/server.py,readonly',
     image,'python','/server.py'])
run(['docker','network','connect','--alias','netbox.example.test',project+'_netbox-sync-egress',project+'-endpoint'])
CLIENT = """import http.client,json,socket,sys
class UnixHTTP(http.client.HTTPConnection):
 def connect(self):
  self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(25);self.sock.connect('/run/netbox-sync-http/api.sock')
payload=json.load(sys.stdin); c=UnixHTTP('sync.example.test',timeout=25)
c.request(payload.get('method','POST'),payload['path'],json.dumps(payload['body']) if payload['body'] is not None else None,headers={'Content-Type':'application/json','Host':'sync.example.test','Origin':'https://sync.example.test','X-Forwarded-Proto':'https','X-NetBox-Sync-CSRF':'same-origin','Cookie':payload.get('cookie','')})
r=c.getresponse();print(json.dumps({'status':r.status,'body':json.loads(r.read()),'cookie':r.getheader('Set-Cookie')}))
"""
session_cookie=''
def request(body, path='/api/v1/sources/test-connection', method='POST'):
    return json.loads(run([*command,'exec','-T','--user','10001','netbox-sync-api','python','-c',CLIENT],
                          input=json.dumps({'path':path,'body':body,'cookie':session_cookie,'method':method})))
assert request(None,'/api/v1/sources','GET')['status']==401
assert request({},'/api/v1/sources/test-connection')['status']==401
invitation=json.loads(compose('exec','-T','--user','0','netbox-sync-auth-worker',
                              'python','-m','netbox_sync.auth_worker','invite'))['invitation']
password=secrets.token_urlsafe(32)
enrolled=request(dict(username='admin',password=password,invitation=invitation),'/api/v1/auth/enroll')
assert enrolled['status']==200
session_cookie=enrolled['cookie'].split(';')[0]
assert request(None,'/api/v1/auth/me','GET')['status']==200
assert request(dict(username='admin',password=password,invitation=invitation),'/api/v1/auth/enroll')['status']==409
if os.environ.get('NETBOX_SYNC_LDAP_COMPOSE_TEST')=='1':
    exec(compile(Path('/review/tests/ldap_compose_scenario.py').read_text(),'ldap_compose_scenario.py','exec'))
compose('exec','-T','--user','0','netbox-sync-auth-worker','python','-m','netbox_sync.auth_worker','managed','public-ipv4')
secret = secrets.token_urlsafe(32)
body = dict(source_type='esxi',address='esxi.probe.test',verify_ssl=True,username='netbox-sync',secret=secret,preview=True)

def snapshot():
    return {str(path):hashlib.sha256(path.read_bytes()).digest() for dirname in ('config','secrets')
            for path in (root / dirname).rglob('*') if path.is_file()}
compose('exec','-T','netbox-sync-bootstrap-worker','python','-c',
        "from netbox_sync.bootstrap_state import BootstrapStore; assert BootstrapStore('/var/lib/netbox-sync/netbox').status()['status']=='READY'")
before = snapshot()
container_ids={service:compose('ps','-q',service) for service in install._runtime_services()}
denied=request(body)
assert denied['status']==422 and denied['body']['error']['code']=='SOURCE_DESTINATION_DENIED'
policy=request(None,'/api/v1/policy','GET')['body']
allowed=request(dict(host=body['address'],expected_revision=policy['revision'],request_id='fixture-allow-esxi-1'),'/api/v1/policy')
assert allowed['status']==200
assert request(dict(host=body['address'],expected_revision=policy['revision'],request_id='fixture-allow-esxi-1'),'/api/v1/policy')['status']==200
assert request(dict(host='other.probe.test',expected_revision=policy['revision'],request_id='fixture-allow-stale'),'/api/v1/policy')['status']==409
for host in ('missing.probe.test','wrong.probe.test','slow.probe.test'):
 policy=request(None,'/api/v1/policy','GET')['body']
 assert request(dict(host=host,expected_revision=policy['revision'],request_id='fixture-'+host),'/api/v1/policy')['status']==200
assert {service:compose('ps','-q',service) for service in install._runtime_services()}==container_ids

# Allow newly recreated API and endpoint sockets to become ready.
for _ in range(3):
    try:
        success = request(body)
        if success['status'] == 200: break
    except RuntimeError: pass
    time.sleep(.5)
else: raise RuntimeError('SOAP probe failed: '+json.dumps(success))
assert success['body']['status'] == 'success'
assert request({'onboarding_token':success['body']['onboarding_token']},'/api/v1/sources/cancel-onboarding')['status'] == 200
for change, code in [({'address':'missing.probe.test'},'SOURCE_DNS_FAILED'),
                     ({'address':'https://esxi.probe.test'},'SOURCE_ADDRESS_INVALID'),
                     ({'username':'reject'},'SOURCE_AUTH_FAILED'),
                     ({'address':'wrong.probe.test'},'SOURCE_TLS_FAILED'),
                     ({'address':'slow.probe.test'},'SOURCE_TIMEOUT'),
                     ({'address':'127.0.0.1'},'SOURCE_DESTINATION_DENIED'),
                     ({'source_type':'proxmox','username':'netbox-sync@pve','token_id':'netbox-sync'},'SOURCE_CONNECTION_FAILED')]:
    result = request({**body,**change})
    assert result['body']['error']['code'] == code, result
    assert secret not in json.dumps(result) and 'REMOTE_DETAIL' not in json.dumps(result)
after = snapshot()
assert after == before, 'Changed protected paths: ' + ', '.join(sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key)))
for container in (api,worker):
    assert secret not in run(['docker','inspect',container])
    logs = subprocess.run(['docker','logs',container],capture_output=True,text=True)
    assert secret not in logs.stdout+logs.stderr and 'REMOTE_DETAIL' not in logs.stdout+logs.stderr
assert (root / 'current').resolve() == p.release
print('PASS authenticated '+pgmode+': real API/SOAP, trusted TLS, auth/timeout/TLS/destination/connection codes, unchanged protected state and isolated production networks',flush=True)

teams=request(None,'/api/v1/teams','GET');assert teams['status']==200
teams=request(dict(operation='create',revision=teams['body']['revision'],name='Fixture Compute'),'/api/v1/teams');assert teams['status']==200
team_id=next(iter(teams['body']['teams']))

if pgmode == 'bundled' and os.environ.get('NETBOX_SYNC_WORKER_FULL_SYNC_TEST') != '1':
    # Exercise installer release preparation/activation against the existing DB.
    # No systemd exists in this disposable host; timer/reboot remains a host gate.
    db_id = compose('ps','-q','postgres')
    db_mounts = json.loads(run(['docker','inspect',db_id]))[0]['Mounts']
    prepared = install.prepare_layout(root, Path('/review'), 'probe-upgrade', image)
    install.configure_tls(prepared, install.resolve_public_url(root, None), install.resolve_tls_settings(root, None))
    install.configure_ingress(prepared, install.resolve_ingress_mode(root, None))
    install.validate_container_names(prepared)
    staged = install.compose_command(root, release=prepared.release, config=prepared.config, overrides=(overlay,))
    run([*staged,'config','--quiet'])
    for service in ('netbox-sync-db-roles','netbox-sync-migrate','netbox-sync-db-grants'):
        run([*staged,'--profile','tools','run','--rm','--no-deps',service])
    install.activate_prepared(prepared, install_units=False, start_services=False)
    install.start_runtime(prepared, overrides=(overlay,))
    assert snapshot() == before
    assert (root / 'current').resolve() == prepared.release
    assert compose('ps','-q','postgres') == db_id
    assert sorted(json.loads(run(['docker','inspect',db_id]))[0]['Mounts'], key=lambda m: m['Destination']) == sorted(db_mounts, key=lambda m: m['Destination'])
    assert request(None,'/api/v1/teams','GET')['body']==teams['body']
    result = request(body)
    assert result['status'] == 200
    assert request({'onboarding_token':result['body']['onboarding_token']},'/api/v1/sources/cancel-onboarding')['status'] == 200
    print('PASS installer component upgrade: selected root, completed onboarding, credentials, DB container/volume retained; probe works after activation',flush=True)

# Policy revision invalidates a successful probe before registration.
success=request(body);assert success['status']==200
receipt=success['body']['onboarding_token']
policy=request(None,'/api/v1/policy','GET')['body']
assert request(dict(host='extra.probe.test',expected_revision=policy['revision'],request_id='fixture-extra-host'),'/api/v1/policy')['status']==200
# Catalog write uses the actual API and bootstrap child, independent of read-token.
creation=dict(operation_id=str(uuid4()),object={'name':'Fixture Vendor','slug':'fixture-vendor'},
              write_token=value['read_token'],confirm=True)
refused=request(creation,'/api/v1/catalog/manufacturer')
assert refused['status']==200 and refused['body']['status']=='REFUSED',refused
assert refused['body']['error']=='PERMISSION_DENIED'
creation.update(operation_id=str(uuid4()),write_token=catalog_token)
created=request(creation,'/api/v1/catalog/manufacturer')
assert created['status']==200 and created['body']['status']=='CREATED',created
assert request(creation,'/api/v1/catalog/manufacturer')['body']==created['body']
creation.update(operation_id=str(uuid4()),object={'name':'Lost response','slug':'lost-response'})
unknown=request(creation,'/api/v1/catalog/manufacturer')
assert unknown['status']==200 and unknown['body']['status']=='UNCERTAIN',unknown
compose('restart','netbox-sync-bootstrap-worker')
for _ in range(40):
    checked=request(None,'/api/v1/catalog-operations/'+creation['operation_id'],'GET')
    if checked['status']==200:break
    time.sleep(.25)
assert checked['body']['status']=='EXISTS_REVIEW_REQUIRED',checked
assert catalog_token not in json.dumps([created,unknown,checked])
for journal in (root/'secrets/netbox').glob('catalog-*.json'):
    assert catalog_token not in journal.read_text() and value['read_token'] not in journal.read_text()
print('Catalog: separate token, refusal, durable lost response and restart reconciliation passed')
references={kind:request(None,'/api/v1/catalog/'+kind,'GET')['body']['items'][0] for kind in ('site','cluster','platform','device_role','cluster_type')}
host_type=request(None,'/api/v1/catalog/device_type','GET')['body']['items'][0]
assert success['body']['preview']['hosts'][0]['manufacturer']=='Dell Inc.'
assert success['body']['preview']['hosts'][0]['model']=='PowerEdge R650'
host_types={host['id']:host_type for host in success['body']['preview']['hosts']}
registration=dict(references=references,host_types=host_types,onboarding_token=receipt,source_type='esxi',source_instance='auth-test',
 name='Auth test',address=body['address'],verify_ssl=True,sync_interval_seconds=600,
 site_slug='dc1',cluster_name='Test',platform_slug='vmware-esxi',device_role_slug='server',
 device_type_slug='server',cluster_type_slug='vmware-esxi',confirm_sync_disabled=True)
assert request(registration,'/api/v1/sources')['status']==409
success=request(body);assert success['status']==200
registration['onboarding_token']=success['body']['onboarding_token']
resolved=request(dict(onboarding_token=registration['onboarding_token'],name=registration['name']),'/api/v1/sources/resolve-placement')
assert resolved['status']==200 and not resolved['body']['issues'] and resolved['body']['create_cluster'],resolved
registration.update(automatic_placement=True,create_cluster=True,registration_id=str(uuid4()),cluster_name=registration['name'])
registration['references']={key:item for key,item in references.items() if key!='cluster'}
assert request({key:registration[key] for key in ('onboarding_token','references','host_types','create_cluster')},'/api/v1/sources/review-placement')['status']==200
added=request(registration,'/api/v1/sources')
assert added['status']==201,added
assert request(registration,'/api/v1/sources')['status']!=201
checked=request({key:registration[key] for key in ('source_instance','registration_id')},'/api/v1/sources/registration-status')
assert checked['status']==200 and checked['body']=={'status':'CREATED'},checked
print('Final registration cluster: production API, bootstrap subprocess, HTTPS and durable registration passed')
assert request(None,'/api/v1/sources','GET')['body']['sources'][0]['source_instance']=='auth-test'
team_saved=request(dict(operation='assign',revision=teams['body']['revision'],source_instance='auth-test',team_id=team_id),'/api/v1/teams');assert team_saved['status']==200
team_saved=team_saved['body']
policy_before_restart=request(None,'/api/v1/policy','GET')['body']
compose('stop','netbox-sync-auth-worker')
assert request(None,'/api/v1/sources','GET')['status']==503
compose('up','-d','--no-deps','netbox-sync-auth-worker')
for _ in range(30):
 if request(None,'/api/v1/auth/me','GET')['status']==200:break
 time.sleep(.3)
else:raise RuntimeError('Auth state did not survive restart')
assert request(None,'/api/v1/policy','GET')['body']==policy_before_restart
assert request(None,'/api/v1/teams','GET')['body']==team_saved
if os.environ.get('NETBOX_SYNC_LDAP_COMPOSE_TEST')=='1':
    assert request(None,'/api/v1/settings/ldap','GET')['body']==ldap_saved

if pgmode == 'bundled' and os.environ.get('NETBOX_SYNC_WORKER_FULL_SYNC_TEST') != '1':
    # Supported host CLI, not a manual SQL dump or an app HTTP bypass.
    from deploy import backup
    def backup_cli(target, *args):
        return run(['python3','/review/deploy/backup.py','--root',str(target),'--no-systemd',*args])
    def db_state(cmd):
        return json.loads(run([*cmd,'exec','-T','postgres','psql','-U','netbox_sync_bootstrap','-d','netbox_sync','-At',
                              '-c','SELECT value FROM netbox_sync.auth_state']))
    auth_before=db_state(command)
    protected_before=snapshot()
    services_before=set(compose('ps','--status','running','--services').split())
    db_before=compose('ps','-q','postgres')
    backup_cli(root,'create')
    bundle=next((root/'backups').glob('netbox-sync-backup-*'))
    backup_cli(root,'verify',str(bundle))
    summary=json.loads(backup_cli(root,'inspect',str(bundle)))
    assert summary['source_count']==1 and summary['alembic_revision']=='0006_auth_policy'
    assert snapshot()==protected_before and compose('ps','-q','postgres')==db_before
    assert set(compose('ps','--status','running','--services').split())==services_before
    assert request(None,'/api/v1/auth/me','GET')['status']==200
    target=root.parent/'netbox-sync-restore'
    install.initialize_tls_layout(target)
    rp=install.prepare_layout(target,Path('/review'),'auth-restore',image)
    install.configure_tls(rp,'https://sync.example.test')
    install.configure_ingress(rp,'external')
    install.initialize_ingress_directory(target)
    install._atomic_write(rp.config/'compose.env',install._merged_config(rp.config/'compose.env',{},
        {'NETBOX_SYNC_COMPOSE_PROJECT':project+'-restore','NETBOX_SYNC_POSTGRES_VOLUME':project+'-restore-db','NETBOX_SYNC_APPLY_LOCK_DIR':str(root.parent/'runtime')}))
    install.publish_configuration(rp);install.activate_release(target,rp.release)
    target_cmd=install.compose_command(target)
    run([*target_cmd,'up','-d','postgres'])
    install._wait_for_postgres(target,rp.release,target/'config')
    for service in ('netbox-sync-db-roles','netbox-sync-migrate','netbox-sync-db-grants'):
        run([*target_cmd,'--profile','tools','run','--rm','--no-deps',service])
    backup_cli(target,'restore',str(bundle))
    restored=db_state(target_cmd)
    assert restored['principal']==auth_before['principal']
    assert restored['source_teams']==auth_before['source_teams']==team_saved
    assert restored['allowed_hosts']==auth_before['allowed_hosts']
    assert restored['sessions']=={} and restored['invitation'] is None and restored['receipts']=={}
    assert restored['mode']=='legacy' and restored['ceiling'] is None
    assert restored.get('ldap')==auth_before.get('ldap')
    assert restored.get('ldap_users')==auth_before.get('ldap_users')
    assert restored.get('ldap_user_revision')==auth_before.get('ldap_user_revision')
    assert restored['ldap_sessions']=={} and restored['ldap_test']=={}
    for name in ('sources','netbox','auth'):
        for path in (root/'secrets'/name).rglob('*'):
            if path.is_file() and path.name!='bootstrap.lock':
                assert path.read_bytes()==(target/'secrets'/name/path.relative_to(root/'secrets'/name)).read_bytes()
    if os.environ.get('NETBOX_SYNC_LDAP_COMPOSE_TEST')=='1':
        run([*target_cmd,'--profile','tools','run','--rm','netbox-sync-http-init'])
        run([*target_cmd,'up','-d','--no-build',*install._runtime_services()])
        run(['docker','network','connect','--alias','ldaps.fixture.test',project+'-restore_netbox-sync-ldap-egress',ldap_name])
        def restored_request(body,path,method='POST',cookie=''):
            return json.loads(run([*target_cmd,'exec','-T','--user','10001','netbox-sync-api','python','-c',CLIENT],
                input=json.dumps({'path':path,'body':body,'cookie':cookie,'method':method})))
        for _ in range(60):
            try:
                if restored_request(None,'/api/v1/auth/me','GET',session_cookie)['status']==401: break
            except RuntimeError: pass
            time.sleep(.5)
        else: raise RuntimeError('Restored API did not revoke old session')
        assert restored_request(dict(username='admin',password=password),'/api/v1/auth/login')['status']==200
        assert restored_request(dict(provider='ldap',username='viewer',password=ldap_data['password']),'/api/v1/auth/login')['status']==200
        print('PASS restored runtime: old sessions rejected, emergency and LDAPS login work with restored CA and bind file',flush=True)
    assert (root/'current').resolve().name=='probe-upgrade'
    assert request(None,'/api/v1/auth/me','GET')['status']==200
    print('PASS actual host CLI backup/create/verify/inspect/fresh-restore: identities, policy, source credentials, READY, service state retained; restored capabilities invalidated',flush=True)

assert request({},'/api/v1/auth/logout')['status']==200
assert request(None,'/api/v1/sources','GET')['status']==401
# Exercise actual HTTP login and DB-persisted deadlines; only fixture timestamps
# change, never production timeouts or password/session values in command output.
def login():
    global session_cookie
    response=request(dict(username='admin',password=password),'/api/v1/auth/login')
    assert response['status']==200
    session_cookie=response['cookie'].split(';')[0]
    assert request(None,'/api/v1/sources','GET')['status']==200

def expire_sessions(field):
    assert field in ('expires','last_seen','issued')
    target=compose('ps','-q','postgres') if pgmode=='bundled' else project+'-external-db'
    sql="UPDATE netbox_sync.auth_state SET value=jsonb_set(value,'{sessions}',(SELECT jsonb_object_agg(key,jsonb_set(s.value, '{"+field+"}', '0'::jsonb)) FROM jsonb_each(value->'sessions') s));"
    run(['docker','exec','-i',target,'psql','-U','netbox_sync_bootstrap','-d','netbox_sync','--set','ON_ERROR_STOP=1'],input=sql)

login()
expire_sessions('issued')
current_policy=request(None,'/api/v1/policy','GET')['body']
confirmation_change=dict(host='reauth.probe.test',expected_revision=current_policy['revision'],request_id='fixture-reauth-policy')
needs_confirmation=request(confirmation_change,'/api/v1/policy')
assert needs_confirmation['status']==403 and needs_confirmation['body']['error']['code']=='AUTH_REAUTH_REQUIRED'
assert request(None,'/api/v1/auth/me','GET')['status']==200
assert request(dict(password='fixture-incorrect'),'/api/v1/auth/reauthenticate')['status']==401
assert request(None,'/api/v1/auth/me','GET')['status']==200
assert request(dict(password=password),'/api/v1/auth/reauthenticate')['status']==200
assert request(None,'/api/v1/policy','GET')['body']==current_policy
assert request(confirmation_change,'/api/v1/policy')['status']==200
# Undo only this fixture's policy exception so the existing upgrade assertions remain exact.
current_policy=request(None,'/api/v1/policy','GET')['body']
assert request(dict(host='reauth.probe.test',operation='revoke',expected_revision=current_policy['revision'],request_id='fixture-reauth-revoke'),'/api/v1/policy')['status']==200
policy_before_restart=request(None,'/api/v1/policy','GET')['body']
print('PASS real API/auth-worker Unix RPC: recent proof expiry keeps session, password confirmation does not mutate policy, explicit retry succeeds',flush=True)

for deadline in ('last_seen','expires'):
    login()
    expire_sessions(deadline)
    assert request(None,'/api/v1/sources','GET')['status']==401
login()
compose('exec','-T','--user','0','netbox-sync-auth-worker','python','-m','netbox_sync.auth_worker','revoke')
assert request(None,'/api/v1/sources','GET')['status']==401
login()
assert request(None,'/api/v1/policy','GET')['body']==policy_before_restart
assert request(None,'/api/v1/teams','GET')['body']==team_saved
assert request({},'/api/v1/auth/logout')['status']==200
assert request(None,'/api/v1/sources','GET')['status']==401
print('PASS runtime session idle/absolute expiry, root revocation, fresh login, retained policy',flush=True)
print('PASS auth policy: direct 401, enrollment/cookie, live CAS permission without recreation, stale receipt refusal, registration, worker outage/restart/logout',flush=True)


if os.environ.get('NETBOX_SYNC_WORKER_FULL_SYNC_TEST') == '1':
    exec(compile(Path('/review/tests/worker_full_sync_scenario.py').read_text(), 'worker_full_sync_scenario.py', 'exec'))
