"""Bounded coordination never enters the audit/confirm body without apply ownership."""
from contextlib import contextmanager
from types import SimpleNamespace
import sys
import os
import pytest
from netbox_sync.run_reconciliation import RunReconciliation
from netbox_sync.source_lifecycle import LifecycleError


def test_waits_then_releases_both_locks_on_body_error(tmp_path, monkeypatch):
    calls=[]
    fcntl=SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda fd, mode:calls.append(('intent',fd)))
    monkeypatch.setattr(os,'O_NOFOLLOW',getattr(os,'O_NOFOLLOW',0),raising=False)
    monkeypatch.setitem(sys.modules,'fcntl',fcntl)
    monkeypatch.setattr('netbox_sync.run_reconciliation.time.sleep',lambda _:None)
    @contextmanager
    def lock(path):
        calls.append(('apply',path))
        if sum(x[0]=='apply' for x in calls)<3:
            raise LifecycleError('SOURCE_APPLY_ACTIVE')
        try:yield
        finally:calls.append(('released',path))
    control=RunReconciliation(SimpleNamespace(lock_path=str(tmp_path/'apply.lock'),lock=lock),None)
    with pytest.raises(ValueError):
        with control._waiting_lock():
            assert sum(x[0]=='apply' for x in calls)==3
            raise ValueError('body')
    assert calls[-1][0]=='released'
    with pytest.raises(OSError):os.fstat(calls[0][1])


def test_wait_deadline_never_enters_body(tmp_path,monkeypatch):
    monkeypatch.setattr(os,'O_NOFOLLOW',getattr(os,'O_NOFOLLOW',0),raising=False)
    monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *args:None))
    times=iter([0,11])
    monkeypatch.setattr('netbox_sync.run_reconciliation.time.monotonic',lambda:next(times))
    @contextmanager
    def lock(path):
        raise LifecycleError('SOURCE_APPLY_ACTIVE')
        yield
    control=RunReconciliation(SimpleNamespace(lock_path=str(tmp_path/'apply.lock'),lock=lock),None)
    with pytest.raises(LifecycleError,match='SOURCE_APPLY_ACTIVE'):
        with control._waiting_lock():pytest.fail('must not enter')


@pytest.mark.skipif(sys.platform=='win32',reason='POSIX production lock')
def test_pending_review_defers_scheduler_and_releases_intent(tmp_path):
    import fcntl
    from netbox_sync.source_lifecycle import apply_lock
    path=str(tmp_path/'apply.lock')
    control=RunReconciliation(SimpleNamespace(lock_path=path,lock=apply_lock),None)
    with open(path+'.reconciliation','a') as scheduler:
        with control._waiting_lock():
            with pytest.raises(BlockingIOError):
                fcntl.flock(scheduler,fcntl.LOCK_SH|fcntl.LOCK_NB)
            with pytest.raises(LifecycleError):
                with apply_lock(path):pytest.fail('writer entered')
        fcntl.flock(scheduler,fcntl.LOCK_SH|fcntl.LOCK_NB)


@pytest.mark.skipif(sys.platform=='win32',reason='POSIX production lock')
def test_scheduler_double_check_yields_to_pending_review(tmp_path):
    import fcntl
    import subprocess
    path=str(tmp_path/'apply.lock')
    intent=path+'.reconciliation'
    # Reproduce the wrapper's second check under its acquired apply lock.
    with open(intent,'a') as pending:
        fcntl.flock(pending,fcntl.LOCK_EX|fcntl.LOCK_NB)
        result=subprocess.run(['flock','-n',path,'sh','-c',
          'flock -s -n "$1" true || exit 0; printf writer-ran','scheduler',intent],capture_output=True)
        assert result.returncode==0 and result.stdout==b''
    result=subprocess.run(['flock','-n',path,'sh','-c',
      'flock -s -n "$1" true || exit 0; printf writer-ran','scheduler',intent],capture_output=True)
    assert result.returncode==0 and result.stdout==b'writer-ran'
