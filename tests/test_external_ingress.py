"""Explicit ingress selection, merged Compose and fail-closed installation."""
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import pytest
from deploy import install, backup

ROOT = Path(__file__).parents[1]
URL = 'https://sync.example.test'


def test_mode_defaults_and_persistence_are_explicit(tmp_path):
    assert install.resolve_ingress_mode(tmp_path) == 'standalone'
    config = tmp_path/'config'; config.mkdir()
    (config/'compose.env').write_text('NETBOX_SYNC_INGRESS_MODE=external\n')
    assert install.resolve_ingress_mode(tmp_path) == 'external'
    assert install.resolve_ingress_mode(tmp_path, 'standalone') == 'standalone'
    command = install.compose_command(tmp_path, 'ps')
    assert str(tmp_path/'current/compose.external-ingress.yml') in command
    for text in ('NETBOX_SYNC_INGRESS_MODE=typo\n',
                 'NETBOX_SYNC_INGRESS_MODE=external\nNETBOX_SYNC_INGRESS_MODE=standalone\n'):
        (config/'compose.env').write_text(text)
        with pytest.raises(install.InstallError):install.compose_command(tmp_path, 'ps')


@pytest.mark.parametrize('version,allowed',[('2.24.3',False),('2.24.4',True),('v5.5.0',True),('unknown',False)])
def test_external_requires_compose_safe_override_support(monkeypatch,version,allowed):
    monkeypatch.setattr(install,'run',lambda *a,**k:SimpleNamespace(stdout=version))
    if allowed:install.validate_ingress_prerequisites('external')
    else:
        with pytest.raises(install.InstallError):install.validate_ingress_prerequisites('external')


def test_external_install_skips_server_certificate_but_keeps_ca_and_public_url(tmp_path,monkeypatch):
    calls=[]
    for name in ('validate_prerequisites','validate_ingress_prerequisites'):
        monkeypatch.setattr(install,name,lambda *a,**k:None)
    monkeypatch.setattr(install,'validate_tls_material',lambda *a:pytest.fail('duplicate server TLS is forbidden'))
    monkeypatch.setattr(install,'prepare_stack',lambda p:calls.append('prepared'))
    monkeypatch.setattr(install,'shared_apply_lock',lambda *a:__import__('contextlib').nullcontext())
    root=tmp_path/'root'
    assert install.main(['--root',str(root),'--source',str(ROOT),'--release-id','external-test',
                         '--ingress-mode','external','--public-url',URL,'--prepare-only','--no-systemd'])==0
    assert calls==['prepared'] and (root/'ingress').is_dir()
    assert not (root/'secrets/tls/privkey.pem').exists()
    ca=root/'secrets/ca/netbox-ca.pem';ca.write_text('invalid');ca.chmod(0o644)
    assert install.main(['--root',str(root),'--ingress-mode','external','--public-url',URL,'--check-tls'])==1


@pytest.mark.parametrize('mode',['standalone','external'])
def test_merged_compose_has_only_intended_publication(mode,tmp_path):
    if shutil.which('docker') is None:pytest.skip('Docker CLI unavailable')
    env=__import__('os').environ.copy();env['NETBOX_SYNC_INGRESS_DIR']=str(tmp_path/'ingress')
    args=['docker','compose','-f',str(ROOT/'compose.production.yml')]
    if mode=='external':args+=['-f',str(ROOT/'compose.external-ingress.yml')]
    model=json.loads(subprocess.check_output(args+['config','--format','json'],env=env,text=True))
    services=model['services'];proxy=services['netbox-sync-proxy']
    assert proxy['tmpfs']==['/tmp:size=64m,mode=1777']
    for service in services.values():
        assert all(mount.startswith('/') for mount in service.get('tmpfs', []))
    if mode=='standalone':assert {p['published'] for p in proxy['ports']}=={'80','443'}
    else:
        assert not proxy.get('ports') and proxy['network_mode']=='none'
        assert not proxy.get('networks')
        assert '/run/netbox-sync-tls' not in {v['target'] for v in proxy['volumes']}
    for name,service in services.items():
        if name!='netbox-sync-proxy':assert not service.get('ports'),name
    assert services['netbox-sync-secret-broker']['network_mode']=='none'


def test_restore_preserves_target_external_mode_without_certificates(tmp_path):
    root=tmp_path/'target';root.mkdir();install.initialize_tls_layout(root)
    for path in (root/'config',tmp_path/'stage/config',tmp_path/'stage/secrets'):path.mkdir(parents=True)
    (root/'config/api.env').write_text('NETBOX_SYNC_PUBLIC_URL='+URL+'\n')
    (root/'config/compose.env').write_text('NETBOX_SYNC_INGRESS_MODE=external\n')
    stage=tmp_path/'stage'
    (stage/'config/api.env').write_text('NETBOX_SYNC_PUBLIC_URL='+URL+'\n')
    (stage/'config/compose.env').write_text('NETBOX_SYNC_INGRESS_MODE=standalone\n')
    backup._extend_tls_restored_configuration(stage,root)
    assert install.ingress_mode_from_config(stage/'config/compose.env')=='external'
    assert not (stage/'secrets/tls/privkey.pem').exists()


@pytest.mark.skipif(getattr(__import__('os'),'geteuid',lambda:-1)()!=0,reason='Linux root TLS metadata')
def test_external_bundle_uses_prepared_standalone_certificate_pair(tmp_path):
    import os
    from tests.tls_fixture import create_certificates
    certs=create_certificates(tmp_path/'certs')
    root=tmp_path/'target';root.mkdir();install.initialize_tls_layout(root)
    stage=tmp_path/'stage';stage.mkdir();install.initialize_tls_layout(stage)
    for directory,mode in ((root,'standalone'),(stage,'external')):
        (directory/'config').mkdir()
        (directory/'config/api.env').write_text('NETBOX_SYNC_PUBLIC_URL='+URL+'\n')
        (directory/'config/compose.env').write_text('NETBOX_SYNC_INGRESS_MODE='+mode+'\nNETBOX_SYNC_TLS_DIR='+str(directory/'secrets/tls')+'\n')
    for name in ('fullchain.pem','privkey.pem'):
        target=root/'secrets/tls'/name;shutil.copyfile(certs/name,target)
        target.chmod(0o640);os.chown(target,0,10001)
    backup._extend_tls_restored_configuration(stage,root)
    assert install.ingress_mode_from_config(stage/'config/compose.env')=='standalone'
    install.validate_tls_material(stage,URL)
    assert (stage/'secrets/tls/privkey.pem').read_bytes()==(root/'secrets/tls/privkey.pem').read_bytes()
