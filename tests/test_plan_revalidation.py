"""Closed stale reasons, deterministic revalidation, no inventory/secret logging."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4
import json
import logging
import pytest
from netbox_sync.source_operations import OperationStore, OperationError
from netbox_sync.apply_worker import ApplySupervisor, ApplyWorkerError
from netbox_sync.plan_diagnostics import summary, differences, safe_reason, safe_categories
from tests.sample_data import sample_source_config
from tests.test_manual_sync_web import Apply, Discovery, HEADERS, create_app, ApiSettings, TestClient
from netbox_sync.api.apply_client import ApplyRequestError

@pytest.mark.parametrize(('change','reason'), [
    (None,'OPERATION_MISSING'), ({'operation_id':'other'},'OPERATION_VERSION'),
    ({'expired':True},'OPERATION_EXPIRED'), ({'expired':None},'OPERATION_EXPIRED'),
    ({'status':'STALE'},'OPERATION_STATUS'), ({'result':None},'RESULT_MISSING'),
    ({'result':{'digest':'b'*64}},'REVIEW_DIGEST'),
])
def test_operation_reasons_fail_closed(change, reason):
    row=dict(operation_id='reviewed',expired=False,status='READY',result={'digest':'a'*64})
    if change is None: row=None
    else: row.update(change)
    class Connection:
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def execute(self,*_): return self
        def fetchone(self): return row
    store=OperationStore('test','test',connector=lambda *_args,**_kwargs:Connection())
    with pytest.raises(OperationError) as caught: store.current_plan('source','a'*64,'reviewed')
    assert caught.value.code=='PLAN_STALE' and caught.value.reason==reason

@pytest.mark.parametrize(('field','category'), [('source_fingerprint','SOURCE_CONFIGURATION'),
    ('target_fingerprint','TARGET_CONFIGURATION'),('provider_fingerprint','PROVIDER_INVENTORY'),
    ('netbox_fingerprint','NETBOX_OBSERVATION'),('items','PLANNED_ACTIONS')])
def test_prepare_changed_plan_is_refused_with_safe_category(monkeypatch,field,category):
    config=sample_source_config()
    saved=dict(apply_allowed=True,digest='a'*64,planner_version='v',source_fingerprint='s',
        target_fingerprint='t',provider_fingerprint='p',netbox_fingerprint='n',items=[{'action':'CREATE'}])
    current=deepcopy(saved);current[field]=[{'action':'CREATE','name':'synthetic-private-inventory'}] if field=='items' else 'changed'
    current['digest']='b'*64
    class Operations:
        @contextmanager
        def review_guard(self,*_): yield saved
    supervisor=ApplySupervisor('','','','','','','');supervisor.operations=Operations()
    monkeypatch.setattr(supervisor,'_source',lambda _:config)
    monkeypatch.setattr(supervisor,'_payload',lambda *_:{})
    monkeypatch.setattr(supervisor,'_child',lambda _:current)
    with pytest.raises(ApplyWorkerError) as caught: supervisor.prepare(config.source_instance,saved['digest'],'id')
    assert caught.value.reason=='PLAN_DIGEST' and category in caught.value.categories
    assert 'synthetic-private-inventory' not in str(caught.value.__dict__)
    # A refreshed review is accepted; no guard is bypassed.
    saved.update(current)
    assert supervisor.prepare(config.source_instance,saved['digest'],'id')['confirmation_token']


def test_public_event_matches_api_log_and_untrusted_details_are_dropped(caplog):
    event=str(uuid4())
    class Worker(Apply):
        def prepare(self,*_,**kwargs):
            raise ApplyRequestError('PLAN_STALE','PLAN_DIGEST',['NETBOX_OBSERVATION','PRIVATE_SECRET'],event)
    client=TestClient(create_app(ApiSettings(allowed_write_hosts=('localhost:8000',)),
        discovery_client=Discovery(),apply_client=Worker()))
    with caplog.at_level(logging.WARNING,logger='netbox_sync.api'):
        response=client.post('/api/v1/sources/pve-test/sync-confirmations',headers=HEADERS,
            json={'plan_digest':'a'*64,'confirmed':True})
    assert response.status_code==409
    error=response.json()['error']
    assert error['event_id']==event and error['reason']=='PLAN_DIGEST'
    assert error['difference_categories']==['NETBOX_OBSERVATION']
    assert any(event in record.message for record in caplog.records)
    assert 'PRIVATE_SECRET' not in response.text and 'PRIVATE_SECRET' not in caplog.text
    assert safe_reason('PRIVATE_SECRET') is None and safe_categories(['PRIVATE_SECRET'])==[]
