"""Exercise the real Unix server's error allowlist, not just a mock API adapter."""
import os
from multiprocessing import get_context
from pathlib import Path
import time
import pytest

@pytest.mark.skipif(os.name!='posix' or not Path('/.dockerenv').is_file(),reason='isolated Linux socket owner fixture')
@pytest.mark.parametrize('code',[
    'SOURCE_RECOVERY_IDENTITY_REVIEW','SOURCE_RECOVERY_EVIDENCE_CHANGED',
    'SOURCE_IDENTITY_UNPROVED','RUN_RECONCILIATION_UNAVAILABLE',
    'RETIREMENT_PERMISSION_DENIED','RETIREMENT_OWNERSHIP_UNPROVEN','untrusted secret text'])
def test_lifecycle_error_through_real_socket(tmp_path,code):
    from netbox_sync.local_control import serve,request,ControlError
    def reject(_):raise ControlError(code)
    path=tmp_path/'control'/'worker.sock'
    process=get_context('fork').Process(target=serve,args=(path,reject,os.getuid()))
    process.start()
    try:
        deadline=time.monotonic()+5
        while not path.exists() and process.is_alive() and time.monotonic()<deadline:time.sleep(.01)
        assert path.exists()
        expected='CONTROL_UNAVAILABLE' if code=='untrusted secret text' else code
        with pytest.raises(ControlError) as error:request(str(path),{'action':'fixture'})
        assert error.value.code==expected and str(error.value)==expected
    finally:
        process.terminate();process.join(3)
        if process.is_alive():process.kill();process.join(3)
        assert not process.is_alive()
