"""Executed inside the owned production Compose scenario after local enrollment."""
local_cookie=session_cookie
ldap_name=project+'-ldap'
run(['docker','run','-d','--name',ldap_name,'--label','com.docker.compose.project='+project,
     '--network',project+'_netbox-sync-ldap-egress','--network-alias','ldaps.fixture.test','--network-alias','wrong.ldaps.fixture.test',
     '--mount','type=bind,source='+str(root/'current')+',target=/app,readonly',
     '-e','PYTHONDONTWRITEBYTECODE=1','netbox-sync-ldap-tests:review','python','-m','tests.ldap_fixture_service'])
for _ in range(60):
    result=subprocess.run(['docker','exec',ldap_name,'test','-f','/tmp/ldap-fixture.json'],capture_output=True)
    if result.returncode==0: break
    time.sleep(.5)
else: raise RuntimeError('Isolated directory fixture not ready')
ldap_data=json.loads(run(['docker','exec',ldap_name,'cat','/tmp/ldap-fixture.json']))
ldap_config=ldap_data['config']
change=dict(expected_revision=0,config=ldap_config,bind_password=ldap_data['bind'])
checked=request(change,'/api/v1/settings/ldap/test')
assert checked['status']==200,checked
saved=request(change,'/api/v1/settings/ldap')
assert saved['status']==200,saved
ldap_saved=saved['body']
assert ldap_saved['bind_secret_present'] and 'secret_key' not in json.dumps(ldap_saved)
assert ldap_data['bind'] not in json.dumps(ldap_saved)
assert request(change,'/api/v1/settings/ldap')['status']==409
assert len(list((root/'secrets/auth').iterdir()))==1
for path in (root/'secrets/auth').iterdir():
    assert path.stat().st_mode & 0o777==0o600
assert (root/'secrets/auth').stat().st_mode & 0o777==0o700
# Read-only is enforced by the container mount, including for auth-worker root.
compose('exec','-T','netbox-sync-auth-worker','python','-c',
    "import errno; from pathlib import Path\ntry: Path('/var/lib/netbox-sync/auth-secrets/forbidden').write_text('no')\nexcept OSError as e: assert e.errno==errno.EROFS\nelse: raise AssertionError('secret mount writable')")
for service in install._runtime_services():
    container=json.loads(run(['docker','inspect',compose('ps','-q',service)]))[0]
    if service!='netbox-sync-auth-worker':
        assert project+'_netbox-sync-ldap-egress' not in container['NetworkSettings']['Networks']
    if service not in ('netbox-sync-auth-worker','netbox-sync-secret-broker'):
        assert not any(m['Destination'] in ('/var/lib/netbox-sync/auth-secrets','/run/netbox-sync-auth-secrets') for m in container['Mounts'])
for role in ('viewer','operator','admin'):
    login_response=request(dict(provider='ldap',username=role,password=ldap_data['password']),'/api/v1/auth/login')
    assert login_response['status']==200,login_response
    session_cookie=login_response['cookie'].split(';')[0]
    assert request(None,'/api/v1/auth/me','GET')['body']['role']==role
    assert request(None,'/api/v1/sources','GET')['status']==200
    assert request(None,'/api/v1/settings/ldap','GET')['status']==(200 if role=='admin' else 403)
    if role=='viewer':
        assert request({},'/api/v1/sources/fixture/operations/plan')['status']==403
    assert request({},'/api/v1/auth/logout')['status']==200
    assert request(None,'/api/v1/auth/me','GET')['status']==401
session_cookie=local_cookie
def directory_change(action):
    run(['docker','exec','-i',ldap_name,'python','-c',
        "import sys; from pathlib import Path; p=Path('/tmp/ldap-command-done.json'); p.unlink(missing_ok=True); Path('/tmp/ldap-command.json').write_text(sys.stdin.read())"],input=json.dumps({'action':action}))
    for _ in range(60):
        if subprocess.run(['docker','exec',ldap_name,'test','-f','/tmp/ldap-command-done.json'],capture_output=True).returncode==0:break
        time.sleep(.1)
    else:raise RuntimeError('Directory change not confirmed')
    assert json.loads(run(['docker','exec',ldap_name,'cat','/tmp/ldap-command-done.json']))['ok']
for revoke,restore in [('remove-operator','add-operator'),('disable-operator','enable-operator')]:
    logged=request(dict(provider='ldap',username='operator',password=ldap_data['password']),'/api/v1/auth/login')
    assert logged['status']==200
    session_cookie=logged['cookie'].split(';')[0]
    directory_change(revoke)
    assert request({},'/api/v1/sources/fixture/operations/plan')['status']==401
    directory_change(restore)
    session_cookie=local_cookie
for username,pw in [('unknown',ldap_data['password']),('viewer','incorrect'),('unmapped',ldap_data['password'])]:
    assert request(dict(provider='ldap',username=username,password=pw),'/api/v1/auth/login')['status']==401
# Exact trust and hostname are checked, without persisting the bad draft.
for bad in ({'ca_pem':''},{'host':'wrong.ldaps.fixture.test'}):
    response=request(dict(expected_revision=1,config={**ldap_config,**bad},bind_password=ldap_data['bind']),'/api/v1/settings/ldap/test')
    assert response['body']['error']['code']=='LDAP_TLS_FAILED'
# A settings read and emergency session survive directory downtime.
run(['docker','stop',ldap_name])
assert request(dict(provider='ldap',username='viewer',password=ldap_data['password']),'/api/v1/auth/login')['status']!=200
assert request(None,'/api/v1/auth/me','GET')['status']==200
run(['docker','start',ldap_name])
# Fixture certificates/config rotate on fixture restart; re-test and explicitly save.
for _ in range(60):
    fresh=json.loads(run(['docker','exec',ldap_name,'cat','/tmp/ldap-fixture.json']))
    if fresh['config']['ca_pem']!=ldap_config['ca_pem']: break
    time.sleep(.5)
else: raise RuntimeError('Directory fixture did not restart')
ldap_data=fresh;ldap_config=fresh['config']
change=dict(expected_revision=1,config=ldap_config,bind_password=ldap_data['bind'])
assert request(change,'/api/v1/settings/ldap/test')['status']==200
assert request(change,'/api/v1/settings/ldap')['status']==200
ldap_saved=request(None,'/api/v1/settings/ldap','GET')['body']
print('PASS production LDAPS: Settings/test/save/login roles, CAS, CA rejection, read-only secret mount, network isolation and emergency access during outage',flush=True)

from concurrent.futures import ThreadPoolExecutor
check=dict(expected_revision=ldap_saved['revision'],config=ldap_config,bind_password='')
assert request(check,'/api/v1/settings/ldap/test')['status']==200
with ThreadPoolExecutor(2) as pool:
    concurrent=list(pool.map(lambda _:request(check,'/api/v1/settings/ldap'),range(2)))
assert sorted(item['status'] for item in concurrent)==[200,409]
ldap_saved=request(None,'/api/v1/settings/ldap','GET')['body']
# Runtime browser is driven by the host harness; no fixture responses are mocked.
if project.startswith('netbox-sync-probe-test-'):
    browser_login=request(dict(username='admin',password=password),'/api/v1/auth/login')
    assert browser_login['status']==200
    browser_cookie=browser_login['cookie'].split(';')[0]
    signal=root.parent/'browser-request.json';done=root.parent/'browser-done.json'
    if done.exists():done.unlink()
    signal.write_text(json.dumps(dict(kind='ldap',project=project,api=compose('ps','-q','netbox-sync-api'),cookie=browser_cookie,password=ldap_data['password'])))
    signal.chmod(0o600)
    for _ in range(480):
        if done.exists():break
        time.sleep(.5)
    else:raise RuntimeError('Production LDAP browser did not finish')
    assert json.loads(done.read_text())['ok']
    done.unlink()
    ldap_saved=request(None,'/api/v1/settings/ldap','GET')['body']

for service in ('netbox-sync-api','netbox-sync-auth-worker','netbox-sync-secret-broker'):
    logs=run(['docker','logs',compose('ps','-q',service)])
    assert ldap_data['bind'] not in logs and ldap_data['password'] not in logs and password not in logs
print('PASS LDAP group removal/account disable block writes, concurrent save has one winner, and logs omit credentials',flush=True)
