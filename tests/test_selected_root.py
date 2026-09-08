"""Root-level deployment contract; any actual filesystem install is container-only."""
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import shutil
import pytest
from deploy import install, backup

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize('value',['/','/etc','/run','/opt','/srv/../etc','/bad root','/bad%root'])
def test_systemd_root_rejects_unsafe_paths(value):
    if os.name!='posix':pytest.skip('POSIX path grammar')
    with pytest.raises(install.InstallError):install.validate_root(Path(value))


@pytest.mark.skipif(os.name!='posix',reason='POSIX unit paths')
def test_rendered_unit_has_selected_root_and_global_lock():
    root=Path('/netbox-sync-test')
    unit=install.render_systemd((ROOT/'deploy/systemd/netbox-sync.service').read_text(),root)
    assert '/opt/netbox-sync' not in unit
    assert 'WorkingDirectory='+str(root/'current') in unit
    assert 'Environment=NETBOX_SYNC_ROOT='+str(root) in unit
    assert 'ReadWritePaths=/run/netbox-sync' in unit
    assert 'NETBOX_SYNC_ROOT:-/opt' not in (ROOT/'scripts/run-scheduled-sync.sh').read_text()


def test_other_root_cannot_take_over_global_systemd_unit(tmp_path):
    (tmp_path/'netbox-sync.service').write_text('WorkingDirectory=/existing/current\n')
    with pytest.raises(install.InstallError):install.validate_systemd_root(Path('/netbox-sync-test'),tmp_path)


@pytest.mark.skipif(getattr(os,'geteuid',lambda:-1)()!=0,reason='Disposable Linux root only')
@pytest.mark.parametrize('selected',['/opt/netbox-sync','/netbox-sync-test','/srv/example-sync'])
def test_exact_root_clean_install_publishes_no_opt_dependency(monkeypatch,tmp_path,selected):
    root=Path(selected)
    assert not root.exists(), 'test requires a disposable clean container'
    events=[]
    monkeypatch.setattr(install,'validate_prerequisites',lambda **k:None)
    monkeypatch.setattr(install,'validate_ingress_prerequisites',lambda *a:None)
    monkeypatch.setattr(install,'check_legacy_dropin',lambda *a:None)
    monkeypatch.setattr(install,'run',lambda command,**k:events.append(command) or SimpleNamespace(returncode=0,stdout=''))
    monkeypatch.setattr(install,'prepare_stack',lambda prepared:events.append(install.compose_command(root,'config','--quiet',release=prepared.release,config=prepared.config)))
    monkeypatch.setattr(install,'start_runtime',lambda prepared:events.append(install.compose_command(root,'up','-d')))
    units=tmp_path/'units';units.mkdir()
    real_install=install.install_systemd
    monkeypatch.setattr(install,'install_systemd',lambda root,start=True:real_install(root,start=start,unit_directory=units))
    assert install.main(['--root',str(root),'--source',str(ROOT),'--release-id','root-contract',
                         '--public-url','https://netbox-sync-test.indeed-id.hq','--ingress-mode','external'])==0
    assert (root/'current').resolve()==root/'releases/root-contract'
    for directory in ('config','secrets','state','backups','ingress'):assert (root/directory).is_dir()
    for path in (root/'config').glob('*.env'):
        if selected != '/opt/netbox-sync':assert '/opt/netbox-sync' not in path.read_text()
    values=install.read_compose_values(root)
    assert values['NETBOX_SYNC_INGRESS_DIR']==str(root/'ingress')
    assert values['NETBOX_SYNC_APPLY_LOCK_DIR']=='/run/netbox-sync'
    assert (install.GLOBAL_RUNTIME/'apply.lock').is_file()
    assert not (root/'run').exists()
    if selected != '/opt/netbox-sync':assert '/opt/netbox-sync' not in repr(events)
    assert 'WorkingDirectory='+str(root/'current') in (units/'netbox-sync.service').read_text()
    assert ['systemctl','enable','--now','netbox-sync.timer'] in events
    monkeypatch.setattr(install,'__file__',str(root/'current/deploy/install.py'))
    assert install.default_root()==root
    identity=backup.deployment_identity(root)
    assert identity['root']==selected
    assert identity['tls_dir']==str(root/'secrets/tls')
    assert identity['tls_layout']=='legacy'
    assert identity['ingress_mode']=='external'
    backup.validate_deployment_identity(identity)
    assert install.resolve_tls_settings(root,Path('/etc/example/cert'))==(Path('/etc/example/cert'),'corporate')


@pytest.mark.skipif(getattr(os,'geteuid',lambda:-1)()!=0,reason='Disposable Linux TLS metadata')
def test_corporate_tls_files_and_restore_stay_outside_application_root(tmp_path):
    from tests.tls_fixture import create_certificates
    root=tmp_path/'app';root.mkdir();install.initialize_tls_layout(root)
    directory=tmp_path/'etc/service/cert';install.initialize_operator_tls(directory)
    certs=create_certificates(tmp_path/'certs')
    for source,target in (('fullchain.pem','ssl.crt'),('privkey.pem','ssl.key')):
        path=directory/target;shutil.copyfile(certs/source,path);os.chown(path,0,10001);path.chmod(0o640)
    subprocess.run(['openssl','genpkey','-genparam','-algorithm','DH','-pkeyopt','group:ffdhe2048',
                    '-out',str(directory/'dhparam.pem')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    os.chown(directory/'dhparam.pem',0,10001);(directory/'dhparam.pem').chmod(0o640)
    settings=(directory,'corporate')
    install.validate_tls_material(root,'https://sync.example.test',settings)
    (root/'config').mkdir()
    for name in ('api.env','compose.env'):(root/'config'/name).write_text('')
    prepared=install.PreparedDeployment(root,root/'current',root/'config','test')
    install.configure_tls(prepared,'https://sync.example.test',settings)
    assert install.resolve_tls_settings(root)==settings
    before={p.name:(p.read_bytes(),p.stat().st_mode,p.stat().st_mtime_ns) for p in directory.iterdir()}
    stage=tmp_path/'stage';stage.mkdir();install.initialize_tls_layout(stage)
    (stage/'config').mkdir()
    for name in ('api.env','compose.env'):(stage/'config'/name).write_text('')
    backup._extend_tls_restored_configuration(stage,root)
    assert {p.name:(p.read_bytes(),p.stat().st_mode,p.stat().st_mtime_ns) for p in directory.iterdir()}==before
    assert not (stage/'secrets/tls/ssl.key').exists()
    assert install.read_compose_values(stage)['NETBOX_SYNC_TLS_DIR']==str(directory)
    (directory/'dhparam.pem').write_text('invalid DH parameters')
    with pytest.raises(install.InstallError):install.validate_tls_material(root,'https://sync.example.test',settings)


def test_restore_requires_explicit_root_before_any_io(monkeypatch):
    monkeypatch.setattr(backup,'DatabaseTool',lambda *a:pytest.fail('must reject before database access'))
    assert backup.main(['restore','/missing/bundle','--check'])==1


@pytest.mark.parametrize('identity',[{}, {'root':'/bad'}])
def test_invalid_recorded_identity_fails_closed(identity):
    with pytest.raises(backup.BackupError):backup.validate_deployment_identity(identity)
