from types import SimpleNamespace
from netbox_sync import pfsense_scheduler as scheduler
from netbox_sync.api.pfsense import Schedule, Connect
from netbox_sync.api.auth import permission
import pytest


def test_schedule_validation_and_permission():
    assert permission('POST','/api/v1/pfsense/2609/schedule') == 'source.apply'
    for interval in (0, 4, 10081):
        with pytest.raises(ValueError): Schedule(sync_enabled=True, interval_minutes=interval, policy_revision=1)
    assert Schedule(sync_enabled=False, interval_minutes=60, policy_revision=1).sync_enabled is False


def test_tick_uses_current_policy_per_vm_without_credentials(tmp_path, monkeypatch):
    root=tmp_path/'pfsense'; root.mkdir()
    for name in ('1.json','2.json','not-a-vm.json'): (root/name).write_text('{}')
    calls=[]; policies=[]
    def policy(*args):
        policies.append(args)
        return {'result':{'effective':{'revision':len(policies)}}}
    monkeypatch.setattr(scheduler,'request',policy)
    monkeypatch.setattr(scheduler,'handle',lambda store,lock,payload,**kwargs:calls.append((payload,kwargs)))
    scheduler.tick(SimpleNamespace(root=tmp_path),'lock')
    assert [c[0]['vm_id'] for c in calls] == [1,2]
    assert all(c[0]['data']=={} and c[0]['session'] is None for c in calls)
    assert [c[1]['scheduled_policy']['revision'] for c in calls]==[1,2]


def test_busy_tick_defers_without_attempting_other_hosts(tmp_path,monkeypatch):
    root=tmp_path/'pfsense';root.mkdir()
    for name in ('1.json','2.json'): (root/name).write_text('{}')
    calls=[]
    monkeypatch.setattr(scheduler,'request',lambda *a:{'result':{'effective':{}}})
    class Busy(Exception): code='SOURCE_APPLY_ACTIVE'
    def handle(*args,**kwargs): calls.append(1);raise Busy()
    monkeypatch.setattr(scheduler,'handle',handle)
    scheduler.tick(SimpleNamespace(root=tmp_path),'lock')
    assert calls==[1]


def test_persisted_due_state_requires_explicit_opt_in_and_key():
    from netbox_sync.pfsense_control import collection_due
    import json
    state=dict(key='secret',host_key='pinned',next_attempt=100,sync_enabled=True)
    assert collection_due(json.loads(json.dumps(state)),100)
    assert not collection_due(state,99)
    assert not collection_due({**state,'sync_enabled':False},200)
    assert not collection_due({'key':'legacy','host_key':'pinned'},200)
    assert not collection_due({**state,'host_key':None},200)


def test_scheduler_policy_is_not_a_public_action():
    from tests.test_auth_policy import enrolled, call
    service,session,_=enrolled()
    assert service.root('pfsense.policy',{})['effective']==service.policy()['effective']
    with pytest.raises(Exception): call(service,session,'pfsense.policy')
