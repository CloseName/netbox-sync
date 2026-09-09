"""Host administration has no invitation in argv/env/stdout and fails before RPC."""
from pathlib import Path
from types import SimpleNamespace
import os
import pytest
from deploy import auth
pytestmark=pytest.mark.skipif(os.name!='posix',reason='POSIX root-only control file modes')

def test_root_invitation_file_is_exclusive_and_private(tmp_path,monkeypatch,capsys):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(auth.os,'geteuid',lambda:0)
    monkeypatch.setattr(auth.install,'compose_command',lambda _root,*args:['docker',*args])
    calls=[]
    def run(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0,stdout='{"invitation":"opaque-fixture-invitation"}')
    monkeypatch.setattr(auth.subprocess,'run',run)
    args=['--root',str(tmp_path),'--invitation-file',str(tmp_path/'invite'),'invite']
    assert auth.main(args)==0
    assert (tmp_path/'invite').stat().st_mode & 0o777==0o600
    assert 'opaque-fixture-invitation' not in str(calls)+capsys.readouterr().out
    assert auth.main(args)==1 and len(calls)==1
    assert (tmp_path/'invite').read_text().strip()=='opaque-fixture-invitation'

def test_non_root_and_unsafe_parent_never_call_control(tmp_path,monkeypatch):
    monkeypatch.setattr(auth.subprocess,'run',lambda *a,**k:pytest.fail('Control must not be called'))
    monkeypatch.setattr(auth.os,'geteuid',lambda:10001)
    with pytest.raises(SystemExit):auth.main(['--root',str(tmp_path),'revoke'])
    monkeypatch.setattr(auth.os,'geteuid',lambda:0)
    tmp_path.chmod(0o755)
    assert auth.main(['--root',str(tmp_path),'--invitation-file',str(tmp_path/'invite'),'invite'])==1
    assert not (tmp_path/'invite').exists()
