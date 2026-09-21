"""UI-6 HTTP boundaries: exact source, closed DTO, CSRF and safe errors."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from tests.auth_support import authenticated_app as create_app
from netbox_sync.api.settings import ApiSettings
from netbox_sync.api.apply_client import ApplyRequestError
from netbox_sync.api.lifecycle_adapters import ReservedSourceError
from tests.test_discovery_web import HEADERS
from tests.test_source_operations_postgres import plan


def operation(**changes):
    now=datetime.now(timezone.utc).isoformat()
    return dict(operation_id=str(uuid4()),source_instance='pve-test',operation_kind='PLAN',
                status='RUNNING',started_at=now,updated_at=now,finished_at=None,
                safe_error_code=None,result=None,**changes)

class Operations:
    def __init__(self,row):self.row=row;self.calls=[];self.invalidated=[]
    def operations(self,source):return {'operations':[self.row]}
    def start_operation(self,source,kind):self.calls.append((source,kind));return {'operation':self.row}
    def invalidate_plan(self,source,identity):self.invalidated.append((source,str(identity)))

def app(client, **extra):
    extra.setdefault('run_service',SimpleNamespace(plan_run=lambda *args: None))
    return TestClient(create_app(ApiSettings(allowed_write_hosts=('localhost:8000',)),
        source_service=SimpleNamespace(get_source=lambda _: object()), discovery_client=client, **extra))

@pytest.mark.parametrize('route',['operations/plan','operations/discovery','remove'])
def test_ui6_writes_require_existing_same_origin_protection(route):
    client=Operations(operation())
    with app(client) as api:
        assert api.post('/api/v1/sources/pve-test/'+route,json={}).status_code==403
    assert client.calls==[]

def test_start_returns_same_id_and_ready_read_strips_internal_identity():
    row=operation();client=Operations(row)
    with app(client) as api:
        first=api.post('/api/v1/sources/pve-test/operations/plan',json={},headers=HEADERS)
        second=api.post('/api/v1/sources/pve-test/operations/plan',json={},headers=HEADERS)
        assert first.status_code==second.status_code==202
        assert first.json()['operation_id']==second.json()['operation_id']
        row.update(status='READY',finished_at=row['started_at'],result=plan('pve-test'))
        ready=api.get('/api/v1/sources/pve-test/operations')
        assert ready.status_code==200
        assert ready.json()['operations'][0]['result']['digest']==row['result']['digest']
        assert 'source_id' not in ready.json()['operations'][0]['result']

@pytest.mark.parametrize('patch',[{'source_instance':'foreign-source'},{'status':'SUCCEEDED'},{'result':{'secret':'SENTINEL'}},{'safe_error_code':'SENTINEL'}])
def test_malformed_operation_never_leaks_data(patch,caplog):
    row=operation();row.update(patch)
    with app(Operations(row)) as api:
        result=api.get('/api/v1/sources/pve-test/operations')
    assert result.status_code>=400 and 'SENTINEL' not in result.text+caplog.text

def test_failed_revalidation_invalidates_only_reviewed_uuid():
    row=operation();client=Operations(row)
    def fail(*_,**kwargs):raise ApplyRequestError('PLAN_STALE')
    with app(client,apply_client=SimpleNamespace(prepare=fail)) as api:
        response=api.post('/api/v1/sources/pve-test/sync-confirmations',headers=HEADERS,
                          json=dict(plan_digest='a'*64,operation_id=row['operation_id'],confirmed=True))
    assert response.status_code==409
    assert client.invalidated==[('pve-test',row['operation_id'])]

def test_reserved_registration_has_distinct_safe_message():
    def register(_):raise ReservedSourceError()
    # Exercise the same installed exception handler with a narrowly injected service.
    with app(Operations(operation()),onboarding_service=SimpleNamespace(test_connection=register)) as api:
        response=api.post('/api/v1/sources/test-connection',headers=HEADERS,json=dict(
            source_type='proxmox',address='pve.example',verify_ssl=True,username='root@pam',secret='fake',token_id='token'))
    assert response.status_code==409
    assert response.json()['error']['code']=='SOURCE_ID_RESERVED'
    assert 'reserved by a removed source' in response.json()['error']['message']


def test_name_edit_is_narrow_and_requires_csrf(monkeypatch):
    from netbox_sync.api.lifecycle_client import LifecycleClient
    from netbox_sync.api.auth import permission
    calls=[]
    def rename(self, source, payload=None, action=None):
        calls.append((source,payload,action))
        return dict(source_instance=source,display_name=payload['name'],revision='b'*64,
                    removed_at=None,credential_state=None)
    monkeypatch.setattr(LifecycleClient,'request',rename)
    body=dict(name='MiXeD Name',revision='a'*64)
    with app(Operations(operation())) as api:
        assert api.patch('/api/v1/sources/pve-test/name',json=body).status_code==403
        assert api.patch('/api/v1/sources/pve-test/name',json={**body,'address':'foreign'},headers=HEADERS).status_code==422
        response=api.patch('/api/v1/sources/pve-test/name',json=body,headers=HEADERS)
    assert response.status_code==200 and response.json()['display_name']=='MiXeD Name'
    assert calls==[('pve-test',body,'rename_source')]
    assert permission('PATCH','/api/v1/sources/pve-test/name')=='source.configure'


def test_used_plan_projection_survives_history_pagination():
    row=operation();row.update(status='READY',finished_at=row['started_at'],result=plan('pve-test'))
    run_id=str(uuid4());calls=[]
    def lookup(*args):calls.append(args);return run_id
    with app(Operations(row),run_service=SimpleNamespace(plan_run=lookup)) as api:
        response=api.get('/api/v1/sources/pve-test/operations')
    assert response.status_code==200
    assert response.json()['operations'][0]['used_run_id']==run_id
    assert calls[0][:2]==('pve-test',row['result']['digest'])


def test_remove_defaults_to_exclusive_cleanup_without_relaxing_fencing(monkeypatch):
    from netbox_sync.api.lifecycle_client import LifecycleClient
    from netbox_sync.api.auth import permission
    calls=[]
    def request(self,source,payload=None,action=None):
        calls.append((source,payload,action))
        return dict(source_instance=source,display_name='Source',revision='b'*64,
                    removed_at=datetime.now(timezone.utc).isoformat(),credential_state='REMOVED')
    monkeypatch.setattr(LifecycleClient,'request',request)
    body=dict(revision='a'*64,confirmed_source='Source')
    with app(Operations(operation())) as api:
        assert api.post('/api/v1/sources/pve-test/remove',json=body).status_code==403
        assert api.post('/api/v1/sources/pve-test/remove',json={'confirmed_source':'Source'},headers=HEADERS).status_code==422
        response=api.post('/api/v1/sources/pve-test/remove',json=body,headers=HEADERS)
    assert response.status_code==200
    assert len(calls)==1 and calls[0][1]=={**body,'remove_credentials':True}
    assert permission('POST','/api/v1/sources/pve-test/remove')=='source.remove'
