"""Real TLS/LDAP protocol fixture. Run in tests/Dockerfile.ldap with --network none.

OpenLDAP simulates the queried AD attributes, not Microsoft AD compatibility.
No network, Docker socket, product mounts, or persistent volumes are required.
"""
import copy
import os
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import subprocess
import time
import pytest
from netbox_sync.ldap_directory import DEFAULT, DirectoryClient, DirectoryError

pytestmark = pytest.mark.skipif(not shutil.which('slapd'), reason='requires isolated tests/Dockerfile.ldap OpenLDAP fixture')

def quiet(args, **kwargs):
    result = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    assert result.returncode == 0, 'fixture setup command failed (output intentionally suppressed)'

def protected(path, text):
    path.write_text(text); path.chmod(0o600)

@pytest.fixture()
def directory(tmp_path):
    import ldap3
    ca = tmp_path/'ca.crt'; key = tmp_path/'ca.key'; cert = tmp_path/'server.crt'; private = tmp_path/'server.key'
    quiet(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(ca),'-days','1','-subj','/CN=Isolated fixture CA','-addext','basicConstraints=critical,CA:TRUE'])
    quiet(['openssl','req','-new','-newkey','rsa:2048','-nodes','-keyout',str(private),'-out',str(tmp_path/'server.csr'),'-subj','/CN=localhost'])
    protected(tmp_path/'ext','subjectAltName=DNS:localhost,DNS:ldaps.fixture.test\nbasicConstraints=critical,CA:FALSE\nextendedKeyUsage=serverAuth\n')
    quiet(['openssl','x509','-req','-in',str(tmp_path/'server.csr'),'-CA',str(ca),'-CAkey',str(key),'-CAcreateserial','-out',str(cert),'-days','1','-extfile',str(tmp_path/'ext')])
    key.chmod(0o600); private.chmod(0o600)
    schema = tmp_path/'fixture.schema'
    schema.write_text("""attributetype ( 1.3.6.1.4.1.55555.100.1 NAME 'userAccountControl' EQUALITY integerMatch SYNTAX 1.3.6.1.4.1.1466.115.121.1.27 SINGLE-VALUE )
attributetype ( 1.3.6.1.4.1.55555.100.2 NAME 'accountExpires' EQUALITY integerMatch SYNTAX 1.3.6.1.4.1.1466.115.121.1.27 SINGLE-VALUE )
attributetype ( 1.3.6.1.4.1.55555.100.3 NAME 'pwdLastSet' EQUALITY integerMatch SYNTAX 1.3.6.1.4.1.1466.115.121.1.27 SINGLE-VALUE )
attributetype ( 1.3.6.1.4.1.55555.100.4 NAME 'msDS-User-Account-Control-Computed' EQUALITY integerMatch SYNTAX 1.3.6.1.4.1.1466.115.121.1.27 SINGLE-VALUE )
attributetype ( 1.3.6.1.4.1.55555.100.6 NAME 'memberOf' EQUALITY distinguishedNameMatch SYNTAX 1.3.6.1.4.1.1466.115.121.1.12 )
objectclass ( 1.3.6.1.4.1.55555.100.5 NAME 'fixtureAccount' SUP top AUXILIARY MAY ( memberOf $ userAccountControl $ accountExpires $ pwdLastSet $ msDS-User-Account-Control-Computed ) )
""")
    db = tmp_path/'database'; db.mkdir()
    root_secret, bind_secret, user_secret = (secrets.token_urlsafe(24) for _ in range(3))
    configfile = tmp_path/'slapd.conf'
    protected(configfile,f"""include /etc/ldap/schema/core.schema
include /etc/ldap/schema/cosine.schema
include /etc/ldap/schema/inetorgperson.schema
include {schema}
pidfile {tmp_path}/slapd.pid
argsfile {tmp_path}/slapd.args
modulepath /usr/lib/ldap
moduleload back_mdb
TLSCACertificateFile {ca}
TLSCertificateFile {cert}
TLSCertificateKeyFile {private}
database mdb
maxsize 10485760
suffix dc=fixture
rootdn cn=manager,dc=fixture
rootpw {root_secret}
directory {db}
access to attrs=userPassword by anonymous auth by self read by * none
access to * by users read by * none
""")
    entries = ["dn: dc=fixture\nobjectClass: domain\ndc: fixture", "dn: ou=people,dc=fixture\nobjectClass: organizationalUnit\nou: people", "dn: ou=groups,dc=fixture\nobjectClass: organizationalUnit\nou: groups",f"dn: cn=reader,dc=fixture\nobjectClass: organizationalRole\nobjectClass: simpleSecurityObject\ncn: reader\nuserPassword: {bind_secret}"]
    for name in ('viewer','operator','admin','multi','unmapped'):
        entries.append(f"dn: uid={name},ou=people,dc=fixture\nobjectClass: inetOrgPerson\nobjectClass: fixtureAccount\nuid: {name}\ncn: {name}\nsn: {name}\nuserAccountControl: 512\nuserPassword: {user_secret}")
    for role in ('viewer','operator','admin'):
        entries.append(f"dn: cn={role},ou=groups,dc=fixture\nobjectClass: groupOfNames\ncn: {role}\nmember: uid={role},ou=people,dc=fixture\nmember: uid=multi,ou=people,dc=fixture")
    entries=[entry+('\nmemberOf: cn=allowed,ou=groups,dc=fixture' if entry.startswith('dn: uid=') and not entry.startswith('dn: uid=unmapped,') else '') for entry in entries]
    entries.append('dn: cn=allowed,ou=groups,dc=fixture\nobjectClass: groupOfNames\ncn: allowed\n'+'\n'.join('member: uid='+name+',ou=people,dc=fixture' for name in ('viewer','operator','admin','multi')))
    ldif = tmp_path/'seed.ldif'; protected(ldif,'\n\n'.join(entries)+'\n')
    quiet(['slapadd','-f',str(configfile),'-l',str(ldif)])
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    process=subprocess.Popen(['slapd','-f',str(configfile),'-h',f'ldaps://0.0.0.0:{port}','-d','0'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.1): break
            except OSError: time.sleep(.05)
        else: pytest.fail('fixture LDAPS listener did not start')
        config={**copy.deepcopy(DEFAULT),'enabled':True,'host':'localhost','port':port,'bind_dn':'cn=reader,dc=fixture',
            'user_base':'ou=people,dc=fixture','group_base':'ou=groups,dc=fixture','user_attribute':'uid',
            'user_object_class':'inetOrgPerson','group_object_class':'groupOfNames','identity_attribute':'entryUUID',
            'ca_pem':ca.read_text(),'group_dn':'cn=allowed,ou=groups,dc=fixture'}
        tls=ldap3.Tls(validate=ssl.CERT_REQUIRED,ca_certs_file=str(ca),valid_names=['localhost'])
        manager=ldap3.Connection(ldap3.Server('localhost',port=port,use_ssl=True,tls=tls),user='cn=manager,dc=fixture',password=root_secret,auto_bind=True)
        yield config,bind_secret,user_secret,manager
        manager.unbind()
    finally:
        process.terminate(); process.wait(timeout=5)


def test_real_ldaps_roles_password_filter_and_refresh(directory):
    config,bind,user,manager=directory; client=DirectoryClient()
    assert client.call(config,bind,'test')['ok']
    for role in ('viewer','operator','admin','multi'):
        result=client.call(config,bind,'login',username=role,password=user)
        assert result['active'] and result['username']==role and 'role' not in result
        assert client.call(config,bind,'refresh',username=role,expected_id=result['identity'])==result
    for name,password in [('viewer','incorrect'),('unknown',user),('unmapped',user),('*',user),('viewer)(uid=*)',user)]:
        with pytest.raises(DirectoryError,match='LDAP_ACCESS_DENIED'): client.call(config,bind,'login',username=name,password=password)
    with pytest.raises(DirectoryError,match='LDAP_BIND_FAILED'): client.call(config,'incorrect','test')


def test_real_ldaps_ca_hostname_and_unavailable(directory):
    config,bind,user,_=directory; client=DirectoryClient()
    for changes in ({'ca_pem':''},{'host':'127.0.0.1'}):
        with pytest.raises(DirectoryError,match='LDAP_TLS_FAILED'): client.call({**config,**changes},bind,'test')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        with pytest.raises(DirectoryError,match='LDAP_UNAVAILABLE'): client.call({**config,'port':port},bind,'test')


def test_real_ldaps_role_revocation_disable_expiry(directory):
    import ldap3
    config,bind,user,manager=directory; client=DirectoryClient()
    identity=client.call(config,bind,'login',username='operator',password=user)['identity']
    assert manager.modify('cn=allowed,ou=groups,dc=fixture',{'member':[(ldap3.MODIFY_DELETE,['uid=operator,ou=people,dc=fixture'])]})
    with pytest.raises(DirectoryError,match='LDAP_ACCESS_DENIED'): client.call(config,bind,'refresh',username='operator',expected_id=identity)
    for attribute,value in [('userAccountControl','514'),('msDS-User-Account-Control-Computed','16'),('accountExpires','1'),('pwdLastSet','0')]:
        assert manager.modify('uid=viewer,ou=people,dc=fixture',{attribute:[(ldap3.MODIFY_REPLACE,[value])]})
        with pytest.raises(DirectoryError,match='LDAP_ACCESS_DENIED'): client.call(config,bind,'login',username='viewer',password=user)
        assert manager.modify('uid=viewer,ou=people,dc=fixture',{attribute:[(ldap3.MODIFY_REPLACE,['512'] if attribute=='userAccountControl' else [])]})


def test_real_directory_through_http_settings_login_and_logout(directory,tmp_path,caplog,request):
    from fastapi.testclient import TestClient
    from netbox_sync.api.app import create_app
    from netbox_sync.api.settings import ApiSettings
    from netbox_sync.auth_policy import AuthPolicy,initial_state
    from netbox_sync.auth_secrets import AuthSecrets
    config,bind,password,_=directory
    secret_root=tmp_path/'auth-secrets'; secret_root.mkdir(mode=0o700)
    import multiprocessing
    from netbox_sync.auth_secrets import serve_auth_secrets
    sockdir=tmp_path/'socket'; sockdir.mkdir(mode=0o700)
    sock=str(sockdir/'worker.sock')
    process=multiprocessing.Process(target=serve_auth_secrets,args=(sock,secret_root))
    process.start()
    def stop():
        process.terminate(); process.join(5)
    request.addfinalizer(stop)
    for _ in range(100):
        if Path(sock).exists(): break
        time.sleep(.02)
    else: pytest.fail('auth secret broker socket missing')
    from netbox_sync.local_control import request as secret_request, ControlError
    for invalid in ({'action':'read','key':'ldap-bind-'+'0'*32},
                    {'action':'delete','key':'ldap-bind-'+'0'*32},
                    {'action':'create','value':'fixture','key':'../../outside'},
                    {'action':'create','value':''}):
        with pytest.raises(ControlError) as refused:
            secret_request(sock, invalid)
        assert refused.value.code == 'CONTROL_REQUEST_INVALID'
    assert list(secret_root.iterdir()) == []
    service=AuthPolicy(initial_state(),directory=DirectoryClient(),auth_secrets=AuthSecrets(secret_root,sock))
    invitation=service.root('invite',{})['invitation']
    class Transport:
        def call(self,action,**payload): return service.call(dict(action=action,**payload))
    app=create_app(settings=ApiSettings(bootstrap_socket=''),auth_client=Transport())
    headers={'Origin':'https://localhost:8000','X-NetBox-Sync-CSRF':'same-origin'}
    with TestClient(app,base_url='https://localhost:8000') as http:
        response=http.post('/api/v1/auth/enroll',headers=headers,json={'invitation':invitation,'username':'admin','password':secrets.token_urlsafe(24)})
        assert response.status_code==200
        payload=dict(expected_revision=0,config=config,bind_password=bind)
        assert http.post('/api/v1/settings/ldap/test',headers=headers,json=payload).status_code==200
        saved=http.post('/api/v1/settings/ldap',headers=headers,json=payload)
        assert saved.status_code==200 and saved.json()['bind_secret_present']
        assert bind not in saved.text and 'secret_key' not in saved.text
        files=list(secret_root.iterdir()); assert len(files)==1
        assert files[0].stat().st_mode & 0o777 == 0o600
        assert http.post('/api/v1/users/sync',headers=headers,json={}).status_code==200
        users=http.get('/api/v1/users').json()
        assert len(users['users'])==4 and all(row['role']=='viewer' for row in users['users'])
        for username,role in [('operator','operator'),('multi','admin')]:
            users=http.get('/api/v1/users').json()
            row=next(row for row in users['users'] if row['username']==username)
            assert http.post('/api/v1/users/role',headers=headers,json={'id':row['id'],'role':role,'revision':users['revision']}).status_code==200
        assert http.post('/api/v1/auth/logout',headers=headers,json={}).status_code==200
        for role in ('viewer','operator','admin'):
            response=http.post('/api/v1/auth/login',headers=headers,json=dict(username=('multi' if role=='admin' else role),password=password))
            assert response.status_code==200
            assert password not in response.text
            cookie=response.headers['set-cookie']
            assert all(word in cookie for word in ('HttpOnly','Secure','SameSite=lax'))
            assert http.get('/api/v1/auth/me').json()['role']==role
            assert http.get('/api/v1/settings/ldap').status_code==(200 if role=='admin' else 403)
            assert http.post('/api/v1/auth/logout',headers=headers,json={}).status_code==200
            assert http.get('/api/v1/auth/me').status_code==401
        assert bind not in caplog.text and password not in caplog.text
        assert bind not in str(service.state) and password not in str(service.state)


def test_real_paged_sync_before_login_rename_and_disabled_account(directory):
    import ldap3
    config,bind,user,manager=directory
    for index in range(205):
        assert manager.add(f'uid=bulk{index},ou=people,dc=fixture',['inetOrgPerson','fixtureAccount'],
            {'uid':f'bulk{index}','cn':f'Bulk {index}','sn':'Fixture','userAccountControl':512,
             'memberOf':config['group_dn']})
    client=DirectoryClient()
    snapshot=client.call(config,bind,'sync')
    assert snapshot['complete'] and len(snapshot['users'])==209
    prior=next(row for row in snapshot['users'] if row['username']=='viewer')
    assert manager.modify_dn('uid=viewer,ou=people,dc=fixture','uid=renamed')
    assert manager.modify(config['group_dn'],{'member':[(ldap3.MODIFY_DELETE,['uid=viewer,ou=people,dc=fixture']),(ldap3.MODIFY_ADD,['uid=renamed,ou=people,dc=fixture'])]})
    assert manager.modify('uid=renamed,ou=people,dc=fixture',{'displayName':[(ldap3.MODIFY_REPLACE,['Renamed person'])]})
    current=client.call(config,bind,'refresh',username='viewer',expected_id=prior['identity'])
    assert current['username']=='renamed' and current['identity']==prior['identity']
    assert manager.modify('uid=renamed,ou=people,dc=fixture',{'userAccountControl':[(ldap3.MODIFY_REPLACE,[514])]})
    snapshot=client.call(config,bind,'sync')
    assert not next(row for row in snapshot['users'] if row['identity']==prior['identity'])['active']


def test_nested_group_members_are_not_admitted_or_synchronized(directory):
    config,bind,password,manager=directory
    import ldap3
    user='uid=unmapped,ou=people,dc=fixture'
    child='cn=nested,ou=groups,dc=fixture'
    assert manager.add(child,['groupOfNames'],{'cn':'nested','member':user})
    assert manager.modify(config['group_dn'],{'member':[(ldap3.MODIFY_ADD,[child])]})
    assert manager.modify(user,{'memberOf':[(ldap3.MODIFY_ADD,[child])]})
    client=DirectoryClient()
    users=client.call(config,bind,'sync')['users']
    assert 'unmapped' not in {u['username'] for u in users}
    with pytest.raises(DirectoryError,match='LDAP_ACCESS_DENIED'):
        client.call(config,bind,'login',username='unmapped',password=password)
