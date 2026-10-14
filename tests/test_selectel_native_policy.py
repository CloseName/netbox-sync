import copy
import importlib
from pathlib import Path
import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from netbox_sync.hardware_identity import observation
from netbox_sync.selectel_host_match import matches
from netbox_sync.selectel_authority import owned_fields
import pytest

package = types.ModuleType('_native_policy_tests')
package.__path__ = [str(Path(__file__).resolve().parents[1] / 'deploy/netbox_guard')]
sys.modules[package.__name__] = package
native_fields = importlib.import_module(package.__name__ + '.provider_native_fields').native_fields


def snapshot(kind='dedicated'):
    now = datetime.now(timezone.utc).isoformat()
    return {'identity':dict(account='29916',kind=kind,native_id='server-a',project='',region=''),
            'sections':{k:dict(status='collected',retained=False,observed_at=now,data=data)
                        for k,data in {'resource':dict(name='Provider name',serial='SERIAL-A',status='ACTIVE'),
                                       'hardware':dict(vcpus=4,ram=8192)}.items()}}


def candidate(snap=None, **fields):
    snap = snap or snapshot()
    return SimpleNamespace(serial='SERIAL-A',custom_fields={
        'selectel_inventory':snap,'selectel_refs':[{'provider':'selectel',**snap['identity']}],**fields})


def host(serial='SERIAL-A', uuid=None):
    rows=[('system_serial',serial,'serial')]
    if uuid: rows.append(('system_uuid',uuid,'uuid'))
    return SimpleNamespace(hardware_identity=observation('esxi',rows))


def test_authoritative_values_no_network_mutation():
    s=snapshot('cloud_vm'); before=copy.deepcopy(s)
    assert native_fields(s)==dict(name='Provider name',status='active',vcpus=4,memory=8192)
    assert s==before
    assert native_fields(snapshot())==dict(name='Provider name',serial='SERIAL-A')


def test_failed_retained_unknown_values_never_clear():
    s=snapshot('cloud_vm')
    s['sections']['hardware']['retained']=True
    s['sections']['resource']['data']['status']='BUILD'
    assert native_fields(s)==dict(name='Provider name')
    s['sections']['resource']['status']='failed'
    assert native_fields(s)=={}
    s=snapshot('cloud_vm'); s['sections']['hardware']['data']=dict(vcpus=True,ram=-1)
    assert 'vcpus' not in native_fields(s) and 'memory' not in native_fields(s)


def test_long_names_are_stable_scoped_and_bounded():
    s=snapshot(); s['sections']['resource']['data']['name']='x'*120
    first=native_fields(s)['name']
    assert len(first)<=64 and first==native_fields(s)['name']
    s['identity']['account']='435835'
    assert first != native_fields(s)['name']


def test_reverse_matching_requires_fresh_typed_identity():
    c=candidate()
    assert matches([c],host())==[c]
    assert matches([c],SimpleNamespace())==[]
    assert matches([c],host('OTHER-SERIAL'))==[]
    c.custom_fields['selectel_inventory']['sections']['resource']['observed_at']=(datetime.now(timezone.utc)-timedelta(days=3)).isoformat()
    with pytest.raises(ValueError,match='SELECTEL_HARDWARE_REVIEW_REQUIRED'): matches([c],host())


def test_ambiguous_or_already_managed_is_never_adopted():
    with pytest.raises(ValueError,match='SELECTEL_MULTIPLE_HARDWARE_MATCHES'): matches([candidate(),candidate()],host())
    with pytest.raises(ValueError,match='SELECTEL_HOST_ALREADY_MANAGED'): matches([candidate(sync_identities=[{'kind':'host'}])],host())


def test_conflicting_uuid_with_equal_serial_blocks_adoption():
    s=snapshot(); s['sections']['resource']['data']['system_uuid']='b64f8ef7-5c89-48db-8b2a-886731fa16a4'
    with pytest.raises(ValueError,match='SELECTEL_HARDWARE_IDENTITY_CONFLICT'):
        matches([candidate(s)],host(uuid='a64f8ef7-5c89-48db-8b2a-886731fa16a4'))


def test_only_explicit_authority_is_preserved_by_other_sources():
    c=candidate(); c.custom_fields['selectel_inventory']['native_fields']=['name','site_id','vcpus','primary_ip4']
    assert owned_fields(c.custom_fields)=={'name','site_id','vcpus'}
    c.custom_fields.pop('selectel_refs')
    assert owned_fields(c.custom_fields)==set()


def test_hypervisor_update_does_not_overwrite_provider_native_values():
    from netbox_sync.netbox_vm_apply import _vm_changes
    from netbox_sync.proxmox_discovery import discover_hosts
    from tests.fakes import FakeProxmox
    from tests.sample_data import proxmox_responses, sample_source_config
    vm=discover_hosts(FakeProxmox(proxmox_responses()),sample_source_config())[0].virtual_machines[0]
    cf={'selectel_refs':[{'provider':'selectel'}],
        'selectel_inventory':{'native_fields':['name','status','vcpus','memory']}}
    existing=SimpleNamespace(serialize=lambda:dict(name='Provider',status='offline',vcpus=99,memory=999,custom_fields=cf))
    changes=_vm_changes(existing,vm,SimpleNamespace(id=123),cf,False)
    assert not {'name','status','vcpus','memory'} & changes.keys()
    assert changes['cluster']==123


def test_esxi_review_accepts_provider_device_before_cluster_assignment():
    from tests.fakes import FakeNetBox, FakeRecord
    from tests.test_esxi_adoption import _inventory, _target, _config
    from netbox_sync.esxi_adoption import build_esxi_adoption_plan, AdoptionClassification
    from netbox_sync.application.discovery_review import build_esxi_review
    api=FakeNetBox(); site,cluster=_target(api); hosts=_inventory()
    hosts[0].hardware_identity=host().hardware_identity
    provider=candidate()
    record=api.dcim.devices.add(FakeRecord(id=901,name='Selectel first',site=site,cluster=None,
        serial=provider.serial,custom_fields=provider.custom_fields))
    plan=build_esxi_adoption_plan(api,hosts,_config())
    item=next(i for i in plan.items if i.object_kind=='host')
    assert item.classification==AdoptionClassification.MANAGED and item.selected_object_id==record.id
    review=build_esxi_review(plan,_config())
    assert next(i for i in review.items if i.object_kind=='host').reason_code=='SELECTEL_HARDWARE_MATCH'
    record.cluster=FakeRecord(id=9876,name='Other cluster')
    plan=build_esxi_adoption_plan(api,hosts,_config())
    assert next(i for i in plan.items if i.object_kind=='host').classification==AdoptionClassification.AMBIGUOUS


def test_esxi_full_plan_and_apply_reuse_provider_primary_key():
    from tests.fakes import FakeNetBox, FakeRecord
    from tests.test_first_sync import target
    from tests.test_esxi_runtime import _config, _inventory
    from netbox_sync.application.runtime_plan import build_runtime_plan
    from netbox_sync.esxi_runtime import execute_esxi_runtime
    api=FakeNetBox(); config=target(api,_config()); hosts=_inventory(1)
    hosts[0].hardware_identity=host().hardware_identity
    c=candidate()
    record=api.dcim.devices.add(FakeRecord(id=901,name='Selectel first',site=api.dcim.sites.get(id=1),
        cluster=None,serial=c.serial,custom_fields=c.custom_fields))
    plan=build_runtime_plan(api,hosts,config)
    assert plan.apply_allowed and api.mutations==[]
    assert not any(i.action.value=='CREATE' and i.object_kind=='dcim.devices' for i in plan.items)
    execute_esxi_runtime(api,hosts,config,confirmed=True)
    assert len(list(api.dcim.devices.all()))==1 and record.name=='Selectel first'
    assert record.custom_fields['selectel_refs']==c.custom_fields['selectel_refs']
    assert record.custom_fields['sync_identities']
