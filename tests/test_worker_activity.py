import json
import os
import time
import pytest
from netbox_sync.worker_activity import activity,bounded_busy,MAX_BUSY_SECONDS
pytestmark=pytest.mark.skipif(os.name!='posix' or os.geteuid()!=0,reason='Linux root-owned worker health metadata')


def test_busy_is_bounded_and_cleared_after_operation(tmp_path):
    path=tmp_path/'activity'
    assert not bounded_busy(path)
    with activity(path):
        assert bounded_busy(path)
        value=json.loads(path.read_text());value['since']-=MAX_BUSY_SECONDS+1;path.write_text(json.dumps(value))
        assert not bounded_busy(path)
    assert not path.exists() and not bounded_busy(path)


@pytest.mark.parametrize('change',['pid','start','mode','extra','link'])
def test_untrusted_or_stale_activity_does_not_hide_failure(tmp_path,change):
    path=tmp_path/'activity'
    with activity(path):
        value=json.loads(path.read_text())
        if change=='mode':path.chmod(0o644)
        elif change=='link':os.link(path,tmp_path/'alias')
        else:
            if change=='pid':value['pid']=2147483647
            elif change=='start':value['start']='wrong-generation'
            else:value['extra']='untrusted'
            path.write_text(json.dumps(value))
        assert not bounded_busy(path)


@pytest.mark.parametrize('busy',[False,True])
def test_health_fallback_is_only_for_apply_and_current_bounded_activity(monkeypatch,busy):
    from types import SimpleNamespace
    from netbox_sync import worker_supervisor,worker_activity
    monkeypatch.setattr(worker_activity,'bounded_busy',lambda:busy)
    monkeypatch.setattr(worker_supervisor.subprocess,'run',lambda args,**kw:SimpleNamespace(returncode=int('netbox-sync-apply' in args[-2])))
    assert worker_supervisor.health('sync')==(0 if busy else 1)
    monkeypatch.setattr(worker_supervisor.subprocess,'run',lambda *args,**kw:SimpleNamespace(returncode=1))
    assert worker_supervisor.health('sync')==1
    assert worker_supervisor.health('netbox')==1
