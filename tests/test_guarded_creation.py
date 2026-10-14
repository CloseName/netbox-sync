"""Creation receipt facade stays outside dry runs and keeps record semantics."""
from types import SimpleNamespace
from uuid import uuid4
import pynetbox
import pytest
from netbox_sync.guarded_creation import GuardedCreation, for_run
from netbox_sync.retirement_transport import GuardTransportError
from netbox_sync.application.planning_netbox import PlanningNetBox


class Client:
    def __init__(self): self.calls=[]
    def create(self,*args):
        self.calls.append(args)
        return {'id': 19, **args[-1]}


def test_vm_replacement_nonce_is_run_and_card_bound():
    api = pynetbox.api('https://netbox.invalid')
    calls = []
    client = SimpleNamespace(_request=lambda method, path, body: calls.append((method, path, body)) or {'id': 19})
    run = uuid4()
    for _ in range(2):
        facade = GuardedCreation(api, client, 'esxi-fixture', 7, run)
        facade.replace_vm(19, {'name': 'recreated'})
    assert calls[0] == calls[1]
    assert calls[0][0:2] == ('POST', 'vm-replacements/19/execute/')


def test_vm_replacement_review_uses_read_transport(monkeypatch):
    from netbox_sync.vm_replacement import configure
    import json
    api = pynetbox.api('https://netbox.invalid', token='fixture-token')
    captured = []
    class Response:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, size): return [json.dumps({'fingerprint': 'a' * 64}).encode()]
    monkeypatch.setattr(api.http_session, 'get', lambda url, **kw: captured.append((url, kw)) or Response())
    configure(api)
    assert api.replacement_review(19, 'esxi-fixture', 7) == {'fingerprint': 'a' * 64}
    assert captured[0][0] == 'https://netbox.invalid/api/plugins/netbox-sync-guard/vm-replacements/19/review/?source_instance=esxi-fixture&cluster_id=7'
    assert captured[0][1]['allow_redirects'] is False


def test_real_pynetbox_records_and_read_delegation(monkeypatch):
    api=pynetbox.api('https://netbox.invalid',token='test-only')
    client=Client();run=uuid4()
    facade=GuardedCreation(api,client,'esxi-fixture',7,run)
    record=facade.dcim.devices.create(name='host',cluster=7)
    assert record.id==19 and record.name=='host'
    assert record.endpoint is facade.dcim.devices.endpoint
    assert record.endpoint.url == api.dcim.devices.url
    assert client.calls[0][1:4]==('esxi-fixture','device',7)
    monkeypatch.setattr(facade.dcim.devices.endpoint,'get',lambda value: record)
    assert facade.dcim.devices.get(19) is record
    assert facade.extras is api.extras
    assert facade.dcim.device_types.url == api.dcim.device_types.url


def test_nonce_is_run_bound_and_not_changed_by_payload():
    api=pynetbox.api('https://netbox.invalid')
    run=uuid4();first=Client();changed=Client();other=Client()
    GuardedCreation(api,first,'esxi-fixture',7,run).virtualization.virtual_machines.create(name='one')
    GuardedCreation(api,changed,'esxi-fixture',7,run).virtualization.virtual_machines.create(name='changed')
    GuardedCreation(api,other,'esxi-fixture',7,uuid4()).virtualization.virtual_machines.create(name='one')
    assert first.calls[0][0]==changed.calls[0][0]
    assert first.calls[0][0]!=other.calls[0][0]


def test_nested_preflight_creates_never_reach_guard():
    api=pynetbox.api('https://netbox.invalid');client=Client()
    facade=GuardedCreation(api,client,'esxi-fixture',7,uuid4())
    planned=PlanningNetBox(PlanningNetBox(facade))
    host=planned.dcim.devices.create(name='host',cluster=7)
    planned.dcim.interfaces.create(device=host.id,name='eth0')
    assert len(planned.mutations)==2 and not client.calls


def test_optional_mode_does_not_claim_old_objects_and_requires_durable_run():
    api=object();config=SimpleNamespace(settings={},source_instance='esxi-fixture')
    assert for_run(api,config,instance='',run_id=None,url='',token='') is api
    with pytest.raises(GuardTransportError,match='GUARD_RUN_REQUIRED'):
        for_run(api,config,instance=str(uuid4()),run_id=None,url='',token='')
    with pytest.raises(GuardTransportError,match='GUARD_PLACEMENT_REQUIRED'):
        for_run(api,config,instance=str(uuid4()),run_id=uuid4(),url='',token='')


def test_partial_run_keeps_successful_host_and_failed_vm_nonce_without_retry():
    from netbox_sync.worker_failure import diagnostic, safe_diagnostic
    from netbox_sync.apply_worker import _failure, ApplyWorkerError
    from netbox_sync.scheduled_failure import record, ExecutionEvidence
    class Refused(Client):
        def create(self,*args):
            if args[2]=='vm':
                self.calls.append(args)
                raise GuardTransportError('OBJECT_INVALID',detail=dict(code='OBJECT_INVALID',http_status=409))
            return super().create(*args)
    client=Refused();run=uuid4()
    facade=GuardedCreation(pynetbox.api('https://netbox.invalid'),client,'esxi-fixture',31,run)
    assert facade.dcim.devices.create(name='host',cluster=31).id==19
    with pytest.raises(GuardTransportError) as caught:
        facade.virtualization.virtual_machines.create(name='private',cluster=31)
    exc=caught.value
    failure=ApplyWorkerError('OUTCOME_UNCERTAIN',diagnostic=_failure(exc,'apply'))
    detail=safe_diagnostic(failure.diagnostic,failure.code)
    assert detail['guard']['run_id']==str(run)
    assert detail['guard']['nonce']==str(client.calls[-1][0])
    assert detail['guard']['code']=='OBJECT_INVALID'
    assert len(client.calls)==2 and client.calls[0][2]=='device'
    scheduled=record(exc,ExecutionEvidence(stage='apply',writes_possible=True),run)
    assert scheduled['write_outcome']=='MAY_HAVE_WRITTEN'
    assert scheduled['guard']==detail['guard']
