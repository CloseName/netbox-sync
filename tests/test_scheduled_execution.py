"""Real REST parity between manual reconciliation and scheduled full sync."""
from dataclasses import replace
import pytest
from tests.fakes import FakeNetBox, FakeProxmox
from tests.fakes.netbox_http import netbox_http
from tests.test_first_sync import target
from tests.sample_data import sample_source_config, proxmox_responses
from netbox_sync.proxmox_discovery import discover_hosts
from netbox_sync.netbox_full_apply import apply_full_sync
from netbox_sync.application.runtime_plan import build_runtime_plan
from netbox_sync import execute_discovered_source


def test_scheduled_after_manual_does_not_load_legacy_catalog(monkeypatch):
    seed=FakeNetBox()
    config=target(seed,replace(sample_source_config(),legacy_identity_owner=False))
    hosts=discover_hosts(FakeProxmox(proxmox_responses()),config)
    requests=[]
    with netbox_http(seed,requests=requests,behavior={'deny_reads': ['virtualization.virtual_disks']}) as (api,rows,writes):
        plan=build_runtime_plan(api,hosts,config)
        assert plan.apply_allowed
        apply_full_sync(api,hosts,config.target,confirmed=True)
        assert rows['dcim.interfaces'] and rows['dcim.mac_addresses'] and rows['ipam.ip_addresses']
        assert len(rows['virtualization.virtual_machines'])==2
        assert not [i for i in build_runtime_plan(api,hosts,config).items if i.action.value in ('CREATE','UPDATE')]
        writes.clear();requests.clear()
        monkeypatch.delenv('NETBOX_SYNC_NETBOX_CONFIG_FILE',raising=False)
        monkeypatch.setenv('NB_API_URL',api.base_url.removesuffix('/api'))
        monkeypatch.setenv('APPLY_SCOPE','full');monkeypatch.setenv('APPLY_CONFIRM','FULL_WRITE')
        monkeypatch.setattr('netbox_sync._read_secret',lambda _: 'local-test-only')
        result=execute_discovered_source(config,hosts,'apply')
        assert result.digest and not [i for i in result.items if i.action.value in ('CREATE','UPDATE')]
        assert not writes
        assert not any('/virtual-disks/' in path for _,path in requests)


def test_scheduled_write_refusal_keeps_plan_and_does_not_retry(monkeypatch,capsys):
    from uuid import uuid4
    from types import SimpleNamespace
    from netbox_sync.orchestrator import run_sources
    from tests.test_orchestrator import RunRecorder
    import json
    seed=FakeNetBox()
    config=target(seed,replace(sample_source_config(),legacy_identity_owner=False))
    hosts=discover_hosts(FakeProxmox(proxmox_responses()),config)
    behavior={}
    with netbox_http(seed,behavior=behavior) as (api,rows,writes):
        apply_full_sync(api,hosts,config.target,confirmed=True)
        hosts[0].memory_bytes+=1024**3
        writes.clear();behavior['fail_next_write']=True
        monkeypatch.delenv('NETBOX_SYNC_NETBOX_CONFIG_FILE',raising=False)
        monkeypatch.setenv('NB_API_URL',api.base_url.removesuffix('/api'))
        monkeypatch.setenv('APPLY_SCOPE','full');monkeypatch.setenv('APPLY_CONFIRM','FULL_WRITE')
        monkeypatch.setattr('netbox_sync._read_secret',lambda _: 'local-test-only')
        history=RunRecorder();run_id=uuid4()
        history.start_run=lambda *args: SimpleNamespace(run_id=run_id)
        result=run_sources([config],lambda c:execute_discovered_source(c,hosts,'apply'),run_repository=history)
        assert result.failed==1 and len(writes)==1 and writes[0][0]=='PATCH'
        value=json.loads(capsys.readouterr().err)
        assert value['run_id']==str(run_id) and value['stage']=='apply'
        assert value['http']=={'status':503,'method':'PATCH','endpoint':'dcim.devices'}
        assert value['write_outcome']=='MAY_HAVE_WRITTEN'
        assert history.finished[0][2]['plan_digest'] and history.finished[0][2]['planner_version']
        assert 'PRIVATE_REMOTE_RESPONSE_MUST_NOT_APPEAR' not in str(value)


def test_blocked_scheduled_plan_never_enters_apply(monkeypatch):
    from types import SimpleNamespace
    from netbox_sync.scheduled_failure import ScheduledPlanBlocked
    monkeypatch.delenv('NETBOX_SYNC_NETBOX_CONFIG_FILE',raising=False)
    monkeypatch.setenv('NB_API_URL','https://unused.invalid')
    monkeypatch.setenv('APPLY_SCOPE','full');monkeypatch.setenv('APPLY_CONFIRM','FULL_WRITE')
    monkeypatch.setattr('netbox_sync._read_secret',lambda _: 'local-test-only')
    monkeypatch.setattr('netbox_sync.application.runtime_plan.build_runtime_plan',lambda *a: SimpleNamespace(apply_allowed=False))
    def forbidden(*args,**kwargs): pytest.fail('Blocked plan entered apply')
    monkeypatch.setattr('netbox_sync.apply_full_sync',forbidden)
    with pytest.raises(ScheduledPlanBlocked): execute_discovered_source(sample_source_config(),[],'apply')


def test_partial_scope_failure_is_not_reported_as_before_write(monkeypatch,capsys):
    import json
    from netbox_sync.orchestrator import run_sources
    monkeypatch.delenv('NETBOX_SYNC_NETBOX_CONFIG_FILE',raising=False)
    monkeypatch.setenv('NB_API_URL','https://unused.invalid')
    monkeypatch.setenv('APPLY_SCOPE','host');monkeypatch.setenv('APPLY_CONFIRM','HOST_WRITE')
    monkeypatch.setattr('netbox_sync._read_secret',lambda _: 'local-test-only')
    monkeypatch.setattr('netbox_sync._load_nb_objects',lambda _: {})
    def fail(*args,**kwargs): raise RuntimeError('PRIVATE')
    monkeypatch.setattr('netbox_sync.apply_hosts',fail)
    result=run_sources([sample_source_config()],lambda c:execute_discovered_source(c,[],'apply'))
    assert result.failed==1
    record=json.loads(capsys.readouterr().err)
    assert record['stage']=='apply' and record['write_outcome']=='MAY_HAVE_WRITTEN'
