"""BIOS disambiguation uses the complete inventory and persisted ownership keys."""
from copy import deepcopy
from dataclasses import replace
from uuid import UUID
import pytest
from tests.fakes.esxi import fake_esxi_service
from tests.test_esxi_runtime import _config
from tests.netbox_scenarios import add_target
from tests.fakes import FakeRecord
from netbox_sync.esxi_discovery import discover_hosts
from netbox_sync.esxi_vm_identity import resolve_vm_identities, PREFIX
from netbox_sync.netbox_vm_metadata import build_vm_custom_fields
from netbox_sync.application.runtime_plan import build_runtime_plan
from netbox_sync.esxi_runtime import execute_esxi_runtime
from netbox_sync.source_identity import virtual_machine_nic_source_identity


def inventory(count=13):
    service = fake_esxi_service()
    template = service.host.vm[0]
    service.host.vm = []
    for i in range(count):
        vm = deepcopy(template)
        vm._moId = f'vm-{1000+i}'
        vm.name = f'PAM-{i}'
        vm.config.uuid = str(UUID(int=100+i))
        vm.config.hardware.device[1].macAddress = f'02:00:00:00:00:{i:02x}'
        vm.guest.net[0].ipConfig.ipAddress[0].ipAddress = f'192.0.2.{20+i}'
        service.host.vm.append(vm)
    return discover_hosts(service, _config())


def persist(api, vm, id=1):
    return api.virtualization.virtual_machines.add(FakeRecord(id=id, name=vm.original_name,
        custom_fields=build_vm_custom_fields(vm)))


def test_duplicate_instance_resolves_all_thirteen_and_is_order_independent(fake_netbox):
    hosts = inventory()
    resolved, conflicts = resolve_vm_identities(fake_netbox, hosts, _config())
    assert not conflicts
    keys = {v.provider_object_id:v.external_id for v in resolved[0].virtual_machines}
    assert len(set(keys.values())) == 13 and all(k.startswith(PREFIX) for k in keys.values())
    assert len({v.external_id for v in hosts[0].virtual_machines}) == 1
    hosts[0].virtual_machines.reverse()
    again, conflicts = resolve_vm_identities(fake_netbox, hosts, _config())
    assert not conflicts and {v.provider_object_id:v.external_id for v in again[0].virtual_machines} == keys


@pytest.mark.parametrize('bad', [None, 'same'])
def test_unusable_bios_blocks_without_excluding_any_vm(fake_netbox, bad):
    hosts=inventory(2)
    hosts[0].virtual_machines[1].esxi_bios_uuid = None if bad is None else hosts[0].virtual_machines[0].esxi_bios_uuid
    resolved, conflicts=resolve_vm_identities(fake_netbox,hosts,_config())
    assert conflicts and len(resolved[0].virtual_machines)==2


def test_bios_collision_outside_duplicate_group_blocks(fake_netbox):
    hosts=inventory(3); outside=hosts[0].virtual_machines[2]
    outside.esxi_instance_uuid=outside.external_id=outside.vmid=str(UUID(int=999))
    outside.esxi_bios_uuid=hosts[0].virtual_machines[0].esxi_bios_uuid
    assert resolve_vm_identities(fake_netbox,hosts,_config())[1]


def test_old_shared_owner_blocks_no_automatic_migration(fake_netbox):
    hosts=inventory(2); old=persist(fake_netbox,hosts[0].virtual_machines[0])
    before=deepcopy(old.custom_fields)
    assert resolve_vm_identities(fake_netbox,hosts,_config())[1]
    assert old.custom_fields==before
    plan=build_runtime_plan(fake_netbox,hosts,_config())
    assert not plan.apply_allowed and plan.conflicts


def test_persisted_choice_survives_group_shrink_and_instance_loss(fake_netbox):
    hosts=inventory(2); resolved,_=resolve_vm_identities(fake_netbox,hosts,_config())
    vm=resolved[0].virtual_machines[0]; persist(fake_netbox,vm)
    hosts[0].virtual_machines=hosts[0].virtual_machines[:1]
    for instance in (hosts[0].virtual_machines[0].esxi_instance_uuid, None, str(UUID(int=999))):
        hosts[0].virtual_machines[0].esxi_instance_uuid=instance
        result, conflicts=resolve_vm_identities(fake_netbox,hosts,_config())
        assert not conflicts and result[0].virtual_machines[0].external_id==vm.external_id
        assert virtual_machine_nic_source_identity(result[0].virtual_machines[0],vm.interfaces[0])==virtual_machine_nic_source_identity(vm,vm.interfaces[0])


def test_am_cm_unique_legacy_identity_unchanged(fake_netbox):
    hosts=inventory(1);vm=hosts[0].virtual_machines[0];persist(fake_netbox,vm)
    result,conflicts=resolve_vm_identities(fake_netbox,hosts,_config())
    assert not conflicts and result==hosts


def test_apply_replan_relations_and_partial_creation_retry(fake_netbox):
    site,_,cluster,_=add_target(fake_netbox)
    hosts=inventory(3)
    from netbox_sync.netbox_metadata import build_device_custom_fields
    fake_netbox.dcim.devices.add(FakeRecord(id=5,name=hosts[0].original_name,site=site,cluster=cluster,custom_fields=build_device_custom_fields(hosts[0])))
    plan=build_runtime_plan(fake_netbox,hosts,_config());assert plan.apply_allowed
    hosts[0].virtual_machines.reverse()
    assert build_runtime_plan(fake_netbox,hosts,_config()).digest==plan.digest
    hosts[0].virtual_machines.reverse()
    execute_esxi_runtime(fake_netbox,hosts,_config(),confirmed=True)
    records=list(fake_netbox.virtualization.virtual_machines.all())
    assert len(records)==3
    assert len(fake_netbox.virtualization.interfaces.all())==3
    keys={r.custom_fields['sync_identities'][0]['external_id'] for r in records}
    by_id={r.id:r for r in records}
    for nic in fake_netbox.virtualization.interfaces.all():
        parent=nic.virtual_machine
        parent_id=parent if isinstance(parent,int) else parent.id
        parent_key=by_id[parent_id].custom_fields['sync_identities'][0]['external_id']
        assert nic.custom_fields['sync_identities'][0]['external_id']==parent_key+':4000'
    assert len(keys)==3 and all(k.startswith(PREFIX) for k in keys)
    again=build_runtime_plan(fake_netbox,hosts,_config())
    assert again.apply_allowed
    assert not [i for i in again.items if i.action.value in ('CREATE','UPDATE')]
    hosts[0].virtual_machines=hosts[0].virtual_machines[:1]
    remaining=build_runtime_plan(fake_netbox,hosts,_config())
    assert remaining.apply_allowed and not [i for i in remaining.items if i.action.value=='CREATE']


def test_partial_creation_keeps_remaining_selection(fake_netbox):
    hosts=inventory(3);resolved,_=resolve_vm_identities(fake_netbox,hosts,_config())
    persist(fake_netbox,resolved[0].virtual_machines[0])
    retry,conflicts=resolve_vm_identities(fake_netbox,hosts,_config())
    assert not conflicts and retry==resolved


def test_disputed_ip_remains_observation(fake_netbox):
    from netbox_sync.application.ip_observations import assignment_inventory
    hosts=inventory(2)
    for vm in hosts[0].virtual_machines:vm.interfaces[0].ip_addresses=['10.11.5.25/32']
    resolved,conflicts=resolve_vm_identities(fake_netbox,hosts,_config());assert not conflicts
    executable,blockers,observations=assignment_inventory(resolved,'observe')
    assert not blockers and len(observations)==1
    for vm in executable[0].virtual_machines:
        assert not vm.interfaces[0].ip_addresses
        assert vm.interfaces[0].network_observations['addresses']==['10.11.5.25/32']


def test_changed_preference_cannot_duplicate_legacy_bios_owner(fake_netbox):
    hosts=inventory(1);vm=hosts[0].virtual_machines[0]
    prior=replace(vm,external_id=vm.esxi_bios_uuid,vmid=vm.esxi_bios_uuid,source_id='esxi:'+vm.esxi_bios_uuid)
    persist(fake_netbox,prior)
    assert resolve_vm_identities(fake_netbox,hosts,_config())[1]


def test_corrupt_persisted_bios_collision(fake_netbox):
    hosts=inventory(2);resolved,_=resolve_vm_identities(fake_netbox,hosts,_config())
    persist(fake_netbox,resolved[0].virtual_machines[0])
    persist(fake_netbox,resolved[0].virtual_machines[0],id=2)
    assert resolve_vm_identities(fake_netbox,hosts,_config())[1]


def test_changed_bios_of_last_member_blocks(fake_netbox):
    hosts=inventory(2);resolved,_=resolve_vm_identities(fake_netbox,hosts,_config())
    persist(fake_netbox,resolved[0].virtual_machines[0])
    hosts[0].virtual_machines=hosts[0].virtual_machines[:1]
    hosts[0].virtual_machines[0].esxi_bios_uuid=str(UUID(int=9999))
    assert resolve_vm_identities(fake_netbox,hosts,_config())[1]


def test_foreign_object_never_adopted(fake_netbox):
    site,_,cluster,_=add_target(fake_netbox)
    hosts=inventory(2);resolved,_=resolve_vm_identities(fake_netbox,hosts,_config())
    foreign=replace(resolved[0].virtual_machines[0],source_instance='other-source')
    record=persist(fake_netbox,foreign)
    record.cluster=cluster
    before=deepcopy(record.custom_fields)
    plan=build_runtime_plan(fake_netbox,hosts,_config())
    assert not plan.apply_allowed
    assert record.custom_fields==before


def test_loss_of_both_uuids_cannot_replace_persisted_bios_vm(fake_netbox):
    hosts=inventory(2);resolved,_=resolve_vm_identities(fake_netbox,hosts,_config())
    persist(fake_netbox,resolved[0].virtual_machines[0])
    hosts[0].virtual_machines=hosts[0].virtual_machines[:1]
    vm=hosts[0].virtual_machines[0]
    vm.esxi_instance_uuid=vm.esxi_bios_uuid=None
    vm.external_id=vm.vmid=vm.provider_object_id
    assert resolve_vm_identities(fake_netbox,hosts,_config())[1]


def test_persisted_choice_and_old_bios_owner_are_ambiguous(fake_netbox):
    hosts=inventory(2);resolved,_=resolve_vm_identities(fake_netbox,hosts,_config())
    vm=resolved[0].virtual_machines[0];persist(fake_netbox,vm)
    persist(fake_netbox,replace(vm,external_id=vm.esxi_bios_uuid,vmid=vm.esxi_bios_uuid),id=2)
    assert resolve_vm_identities(fake_netbox,hosts,_config())[1]
    hosts[0].virtual_machines=hosts[0].virtual_machines[:1]
    hosts[0].virtual_machines[0].esxi_instance_uuid=None
    assert resolve_vm_identities(fake_netbox,hosts,_config())[1]
