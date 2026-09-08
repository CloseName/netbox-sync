"""Public origin, strict NetBox trust and canonical deployment boundary regressions."""
import json
import os
from pathlib import Path
import ssl
from types import SimpleNamespace
import pytest
import requests
from fastapi.testclient import TestClient
from netbox_sync.api.app import create_app
from netbox_sync.api.settings import ApiSettings
from netbox_sync.api.bootstrap import BootstrapClient
from netbox_sync.tls_config import public_authority,TLSConfigurationError
from netbox_sync.netbox_tls import configure_session
from deploy import install,backup

ROOT=Path(__file__).parents[1]
URL='https://sync.example.test'

@pytest.mark.parametrize('url',['http://sync.example.test','https://sync.example.test/','https://sync.example.test:443',
 'https://user:secret@sync.example.test','https://sync.example.test?q=x','https://*.example.test',
 'https://localhost','https://10.0.0.1','https://SYNC.example.test','https://sync.example.test\n','https://x.example/;return 200;'])
def test_public_url_is_an_exact_https_fqdn(url):
    with pytest.raises(TLSConfigurationError):public_authority(url)


def test_canonical_public_url_has_no_wildcard_or_loopback_defaults():
    assert public_authority(URL)=='sync.example.test'
    assert ApiSettings.from_environment({'NETBOX_SYNC_PUBLIC_URL':URL}).public_url==URL


def test_https_origin_is_accepted_only_on_controlled_unix_boundary(monkeypatch):
    monkeypatch.setattr(BootstrapClient,'call',lambda *_args,**_kwargs:dict(revision=1,status='READY',url='https://nb.example.test',completed=True,
        read_token_present=True,apply_token_present=True,safe_code=None,checks=[],validated_at=1))
    app=create_app(ApiSettings(public_url=URL,bootstrap_socket='/test'))
    headers={'Origin':URL,'X-Forwarded-Proto':'https','X-NetBox-Sync-CSRF':'same-origin'}
    with TestClient(app,base_url='http://sync.example.test',client=None) as proxy:
        assert proxy.post('/api/v1/bootstrap/finish',json={'revision':1},headers=headers).status_code==200
        for patch in ({'Origin':'https://evil.example.test'},{'Origin':'http://sync.example.test'},
                      {'Host':'evil.example.test'},{'X-Forwarded-Proto':'http'},{'X-Forwarded-Proto':'https,http'}):
            assert proxy.post('/api/v1/bootstrap/finish',json={'revision':1},headers={**headers,**patch}).status_code==403
    with TestClient(app,base_url=URL,client=('127.0.0.1',9000)) as direct:
        assert direct.post('/api/v1/bootstrap/finish',json={'revision':1},headers=headers).status_code==403
        assert direct.get('/',headers={'X-Forwarded-Proto':'https','Forwarded':'proto=https;host=sync.example.test'}).status_code==403


def test_absent_custom_ca_uses_standard_trust_and_ignores_environment(tmp_path,monkeypatch):
    monkeypatch.setenv('REQUESTS_CA_BUNDLE','/attacker/ca.pem')
    monkeypatch.setenv('HTTPS_PROXY','https://attacker.invalid')
    session=configure_session(requests.Session(),tmp_path/'missing.pem')
    assert session.verify is True and session.trust_env is False


def test_invalid_ca_fails_closed_without_raw_contents(tmp_path):
    path=tmp_path/'netbox-ca.pem';path.write_text('SENSITIVE-MARKER-not-a-certificate');path.chmod(0o644)
    with pytest.raises(TLSConfigurationError) as caught:configure_session(requests.Session(),path)
    assert 'SENSITIVE-MARKER' not in str(caught.value)


def test_tls_preflight_blocks_before_database_work(tmp_path,monkeypatch):
    monkeypatch.setattr(install,'validate_prerequisites',lambda **_:None)
    monkeypatch.setattr(install,'prepare_stack',lambda *_:pytest.fail('must not reach database'))
    assert install.main(['--root',str(tmp_path/'root'),'--public-url',URL,'--release-id','test'])==1
    assert not (tmp_path/'root/releases').exists()


def test_tls_settings_are_explicit_and_existing_authority_is_preserved(tmp_path):
    (tmp_path/'config').mkdir();(tmp_path/'config/api.env').write_text('NETBOX_SYNC_PUBLIC_URL='+URL+'\n')
    assert install.resolve_public_url(tmp_path,None)==URL
    with pytest.raises(install.InstallError):install.resolve_public_url(tmp_path,'https://other.example.test')


def test_compose_proxy_and_mount_boundaries():
    text=(ROOT/'compose.production.yml').read_text()
    proxy=text.split('  netbox-sync-proxy:',1)[1].split('  netbox-sync-http-init:',1)[0]
    api=text.split('  netbox-sync-api:',1)[1].split('  netbox-sync-secret-broker:',1)[0]
    broker=text.split('  netbox-sync-secret-broker:',1)[1].split('  netbox-sync-lifecycle-worker:',1)[0]
    assert '"80:8080"' in proxy and '"443:8443"' in proxy
    assert 'user: "10001:10001"' in proxy and 'cap_drop: [ALL]' in proxy
    assert '/run/netbox-sync-tls:ro' in proxy and '/run/netbox-sync-http:ro' in proxy
    assert 'ports:' not in api and 'network_mode: none' in broker
    assert 'CA_DIR' not in api+broker+proxy
    assert text.count('/run/netbox-sync-ca:ro')==4
    assert 'docker.sock' not in text
    assert 'proxy_headers=False' in (ROOT/'netbox_sync/web_runtime.py').read_text()


def test_backup_additional_modes_are_exact_path_capabilities():
    assert backup._persistent_permissions('secrets/tls/privkey.pem')==(0o640,10001)
    assert backup._persistent_permissions('secrets/ca/netbox-ca.pem')==(0o644,0)
    assert backup._persistent_permissions('secrets/netbox/bootstrap.json')==(0o600,0)
    with pytest.raises(backup.BackupError):backup._persistent_permissions('secrets/tls/other.key')


def test_tls_configuration_rewrites_restored_host_paths(tmp_path):
    config=tmp_path/'config';config.mkdir()
    (config/'compose.env').write_text('NETBOX_SYNC_TLS_DIR=/old/secrets/tls\nNETBOX_SYNC_CA_DIR=/old/secrets/ca\nNETBOX_SYNC_PUBLIC_HOST=old.example.test\n')
    (config/'api.env').write_text('')
    install.configure_tls(SimpleNamespace(root=tmp_path,config=config),URL)
    content=(config/'compose.env').read_text()
    assert '/old/' not in content
    assert 'NETBOX_SYNC_PUBLIC_HOST=sync.example.test' in content


def test_release_packaging_never_copies_operator_private_material(tmp_path):
    import shutil
    source=tmp_path/'checkout';source.mkdir()
    (source/'code.py').write_text('print(1)')
    digest=install._release_digest(source)
    (source/'secrets').mkdir()
    for path in (source/'secrets'/'fullchain.pem',source/'privkey.pem',source/'operator.key'):
        path.write_text('TEST-ONLY-PRIVATE-MARKER')
    assert install._release_digest(source)==digest
    target=tmp_path/'release'
    shutil.copytree(source,target,ignore=install._ignore)
    assert {path.name for path in target.iterdir()}=={'code.py'}
