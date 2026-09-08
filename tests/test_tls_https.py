"""Real HTTPS private-CA/hostname validation, entirely local and disposable."""
import json
import os
from pathlib import Path
import ssl
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
import requests
from netbox_sync.bootstrap_probe import probe,FIELDS
from netbox_sync.api.egress import pinned_dns
from netbox_sync.netbox_tls import configure_session
from netbox_sync.tls_config import TLSConfigurationError
from tests.tls_fixture import create_certificates
from deploy import install,backup

pytestmark=pytest.mark.skipif(getattr(os,'geteuid',lambda:-1)()!=0,reason='Disposable Linux root and OpenSSL required')

@pytest.fixture
def certificates(tmp_path):return create_certificates(tmp_path/'certificates')

@pytest.fixture
def https_server(certificates):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def respond(self,value):
            raw=json.dumps(value).encode();self.send_response(200)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if '/custom-fields/' in self.path:
                self.respond(dict(next=None,results=[dict(name=n,type=k,object_types=list(m)) for n,(k,m) in FIELDS.items()]))
            else:self.respond(dict(count=0,results=[],next=None,previous=None))
        def do_OPTIONS(self):
            self.respond(dict(actions={} if self.headers.get('Authorization')=='Token TEST-READ' else {'POST':{}}))
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificates/'fullchain.pem',certificates/'privkey.pem')
    server.socket=context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield server.server_port
    server.shutdown();server.server_close();thread.join()


def test_bootstrap_and_runtime_client_trust_private_ca_without_insecure_fallback(certificates,https_server,monkeypatch,tmp_path):
    port=https_server
    class LocalOnly:
        def resolve(self,host,_port):return host,'127.0.0.1'
    payload=dict(url=f'https://netbox.example.test:{port}',read_token='TEST-READ',apply_token='TEST-APPLY')
    monkeypatch.setattr('netbox_sync.netbox_tls.CA_FILE',tmp_path/'absent.pem')
    assert probe(payload,policy=LocalOnly())['safe_code']=='TLS_FAILED'
    monkeypatch.setattr('netbox_sync.netbox_tls.CA_FILE',certificates/'ca.pem')
    assert probe(payload,policy=LocalOnly())['safe_code'] is None
    import pynetbox
    api=pynetbox.api(payload['url'],token='TEST-READ')
    configure_session(api.http_session)
    with pinned_dns('netbox.example.test','127.0.0.1',port):
        assert list(api.dcim.devices.all())==[]
    assert probe({**payload,'url':f'https://wrong.example.test:{port}'},policy=LocalOnly())['safe_code']=='TLS_FAILED'
    (certificates/'ca.pem').write_text('invalid corporate CA')
    assert probe(payload,policy=LocalOnly())['safe_code']=='TLS_FAILED'


def test_tls_preflight_modes_hostname_and_key_match(certificates,tmp_path):
    import shutil
    root=tmp_path/'deployment'
    install.initialize_tls_layout(root)
    for name in ('fullchain.pem','privkey.pem'):
        path=root/'secrets/tls'/name;shutil.copyfile(certificates/name,path)
        os.chown(path,0,10001);path.chmod(0o640)
    install.validate_tls_material(root,'https://sync.example.test')
    with pytest.raises(install.InstallError):install.validate_tls_material(root,'https://wrong.example.test')
    (root/'secrets/tls/privkey.pem').chmod(0o644)
    with pytest.raises(install.TLSConfigurationError):install.validate_tls_material(root,'https://sync.example.test')
    (root/'secrets/tls/privkey.pem').chmod(0o640)
    shutil.copyfile(certificates/'ca.key',root/'secrets/tls/privkey.pem')
    with pytest.raises(install.InstallError):install.validate_tls_material(root,'https://sync.example.test')


def test_ca_symlink_and_writable_file_never_fall_back(certificates,tmp_path):
    path=tmp_path/'netbox-ca.pem';path.symlink_to(certificates/'ca.pem')
    with pytest.raises(TLSConfigurationError):configure_session(requests.Session(),path)
    (certificates/'ca.pem').chmod(0o666)
    with pytest.raises(TLSConfigurationError):configure_session(requests.Session(),certificates/'ca.pem')


def test_backup_roundtrip_preserves_exact_tls_and_ca_metadata(certificates,tmp_path):
    import shutil
    root=tmp_path/'deployment'
    install.initialize_tls_layout(root)
    for directory in ('config','secrets/infrastructure','secrets/sources','secrets/netbox'):
        (root/directory).mkdir(parents=True,exist_ok=True);(root/directory).chmod(0o700)
    for name in install.CONFIG_NAMES:
        path=root/'config'/name;path.write_text('');path.chmod(0o600)
    for name in ('fullchain.pem','privkey.pem'):
        path=root/'secrets/tls'/name;shutil.copyfile(certificates/name,path);os.chown(path,0,10001);path.chmod(0o640)
    ca=root/'secrets/ca/netbox-ca.pem';shutil.copyfile(certificates/'ca.pem',ca);ca.chmod(0o644)
    before=backup._file_metadata(root)
    records={item['path']:item for item in before}
    assert records['secrets/tls/privkey.pem']['gid']==10001
    assert records['secrets/tls/privkey.pem']['mode']=='0640'
    assert records['secrets/ca/netbox-ca.pem']['mode']=='0644'
    archive=tmp_path/'state.tar'
    import subprocess
    subprocess.run(['tar','--xattrs','--numeric-owner','-cf',str(archive),'-C',str(root),'config','secrets'],check=True)
    restored=tmp_path/'restored';restored.mkdir()
    backup._tar_extract(archive,restored)
    assert backup._file_metadata(restored)==before
    (restored/'secrets/tls/privkey.pem').chmod(0o644)
    with pytest.raises(backup.BackupError):backup._file_metadata(restored)
