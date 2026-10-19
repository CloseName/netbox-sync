from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from netbox_sync import selectel_control as control
from netbox_sync import selectel_runner as runner
from netbox_sync import selectel_lifecycle_control as lifecycle
from netbox_sync.source_lifecycle import LifecycleError
import pytest


@pytest.fixture
def env(tmp_path,monkeypatch):
    state=dict(account='29916',name='Test',username='service',password='secret',enabled=False,
               status='completed',schedule={'kind':'daily'},next_run=123)
    path=tmp_path/'29916.json'; path.touch()
    (tmp_path/'netbox-token.json').touch()
    saved={path:state,tmp_path/'netbox-token.json':{'token':'private'}}
    monkeypatch.setattr(control,'root',lambda _:tmp_path)
    monkeypatch.setattr(control,'read',lambda p:deepcopy(saved[p]))
    monkeypatch.setattr(control,'write',lambda p,v:saved.__setitem__(p,deepcopy(v)))
    monkeypatch.setattr(lifecycle,'runtime_netbox',lambda *a:('https://netbox-test.invalid','unused'))
    monkeypatch.setattr(lifecycle,'apply_lock',lambda _:nullcontext())
    store=SimpleNamespace(locked=lambda:nullcontext(),path='unused')
    calls=[]; answers=[]
    def child(value,timeout):
        calls.append(deepcopy(value))
        return answers.pop(0)
    monkeypatch.setattr(runner,'child',child)
    return store,path,saved,calls,answers


def data(**kw):
    return dict(account='29916',operation='delete',key=None,fingerprint='a'*64,confirmed=True,**kw)


def test_unknown_result_retries_exact_nonce_then_erases_credentials(env):
    store,path,saved,calls,answers=env
    answers.append({'error':'IMPORT_UNCONFIRMED'})
    assert lifecycle.handle(store,'lock','lifecycle-execute',data())['error']=='LIFECYCLE_UNCONFIRMED'
    pending=deepcopy(saved[path]['lifecycle_pending'])
    assert pending['nonce'] and saved[path]['next_run'] is None
    answers.append({'writes_performed':True,'replayed':True})
    assert lifecycle.handle(store,'lock','lifecycle-execute',data())['replayed']
    assert calls[0]['payload']==calls[1]['payload']==pending
    assert saved[path]['deleted'] and not saved[path]['enabled']
    assert not ({'password','username','schedule','summary','lifecycle_pending'} & saved[path].keys())


def test_pending_cannot_be_replaced_and_review_cannot_authorize_new_action(env):
    store,path,saved,calls,answers=env
    answers.append({'error':'IMPORT_UNCONFIRMED'})
    lifecycle.handle(store,'lock','lifecycle-execute',data())
    changed=data(); changed['fingerprint']='b'*64
    assert lifecycle.handle(store,'lock','lifecycle-execute',changed)['error']=='LIFECYCLE_UNCONFIRMED'
    assert lifecycle.handle(store,'lock','lifecycle-review',{'account':'29916','operation':'delete'})['error']=='LIFECYCLE_UNCONFIRMED'
    assert len(calls)==1


def test_confirmed_rollback_allows_new_review(env):
    store,path,saved,calls,answers=env
    answers.append({'error':'PROVIDER_REVIEW_STALE','writes_performed':False,'rolled_back':True})
    assert lifecycle.handle(store,'lock','lifecycle-execute',data())['error']=='PROVIDER_REVIEW_STALE'
    assert 'lifecycle_pending' not in saved[path] and saved[path]['password']=='secret'


def test_disabled_and_confirmation_required_before_child(env):
    store,path,saved,calls,answers=env
    saved[path]['enabled']=True
    assert lifecycle.handle(store,'lock','lifecycle-execute',data())['error']=='DISABLE_ACCOUNT_FIRST'
    saved[path]['enabled']=False
    value=data(); value['confirmed']=False
    assert lifecycle.handle(store,'lock','lifecycle-execute',value)['error']=='LIFECYCLE_CONFIRMATION_REQUIRED'
    assert calls==[]


def test_busy_returns_actionable_result_without_stopping_scheduler(env,monkeypatch):
    store,path,saved,calls,answers=env
    def busy(_):raise LifecycleError('SOURCE_APPLY_ACTIVE')
    monkeypatch.setattr(lifecycle,'apply_lock',busy)
    assert lifecycle.handle(store,'lock','lifecycle-execute',data())=={'error':'LIFECYCLE_BUSY'}
    assert 'lifecycle_pending' not in saved[path] and not calls
