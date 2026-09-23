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
