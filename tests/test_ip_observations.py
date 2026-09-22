"""Address observations never authorize arbitrary IPAM ownership or VM adoption."""
from copy import deepcopy
import pytest
from netbox_sync.application.ip_observations import assignment_inventory
from netbox_sync.esxi_discovery import discover_hosts
from tests.fakes.esxi import fake_esxi_service
from tests.test_esxi import esxi_config


def inventory():
    return discover_hosts(fake_esxi_service(), esxi_config())


def test_strict_default_retains_blocking_and_all_masks():
    hosts = inventory()
    nic = hosts[0].virtual_machines[0].interfaces[0]
    nic.ip_addresses = ['192.0.2.50/24', '192.0.2.50/32']
    projected, blockers, observations = assignment_inventory(hosts)
    assert blockers and not observations
    assert projected[0].virtual_machines[0].interfaces[0].ip_addresses == nic.ip_addresses


def test_observe_excludes_every_disputed_mask_preserves_unrelated_facts_and_input():
    hosts = inventory()
    nic = hosts[0].virtual_machines[0].interfaces[0]
    nic.ip_addresses = ['192.0.2.50/24', '192.0.2.50/32', '192.0.2.51/24']
    before = deepcopy(hosts)
    projected, blockers, observations = assignment_inventory(hosts, 'observe')
    assert not blockers
    assert hosts == before
    assert projected[0].virtual_machines[0].interfaces[0].ip_addresses == ['192.0.2.51/24']
    assert {p.address for p in observations[0].participants} == {'192.0.2.50/24', '192.0.2.50/32'}
    assert all(p.interface == nic.name for p in observations[0].participants)


def test_different_vms_do_not_gain_arbitrary_assignment_or_network_area():
    hosts = inventory()
    vm = hosts[0].virtual_machines[0]
    other = deepcopy(vm)
    other.external_id = 'different-id'
    other.provider_object_id = 'vm-999'
    other.interfaces[0].bridge = 'different-label'
    other.interfaces[0].vlan_id = 999
    hosts[0].virtual_machines.append(other)
    projected, blockers, observations = assignment_inventory(hosts, 'observe')
    assert not blockers and len(observations[0].participants) == 2
    assert all(not v.interfaces[0].ip_addresses for v in projected[0].virtual_machines)
    assert len(projected[0].virtual_machines) == 2


def test_vm_identity_still_blocks_without_projection():
    hosts = inventory()
    hosts[0].virtual_machines.append(deepcopy(hosts[0].virtual_machines[0]))
    projected, blockers, observations = assignment_inventory(hosts, 'observe')
    assert any(c.kind == 'VM_IDENTITY' for c in blockers)
    assert not observations
    assert projected[0].virtual_machines[0].interfaces[0].ip_addresses


def test_exact_fact_is_deduplicated_not_downgraded_to_observation():
    hosts = inventory()
    hosts[0].virtual_machines[0].interfaces[0].ip_addresses *= 2
    projected, blockers, observations = assignment_inventory(hosts, 'observe')
    assert not blockers and not observations
    assert len(projected[0].virtual_machines[0].interfaces[0].ip_addresses) == 1


def test_unknown_policy_fails_closed():
    with pytest.raises(ValueError, match='policy'):
        assignment_inventory(inventory(), 'guess')


def test_interface_metadata_preserves_observations_and_other_source_entries():
    from netbox_sync.netbox_vm_interface_metadata import build_nic_custom_fields
    hosts = inventory()
    hosts[0].virtual_machines[0].interfaces[0].ip_addresses = ['192.0.2.50/24', '192.0.2.50/32']
    projected, _, _ = assignment_inventory(hosts, 'observe')
    vm = projected[0].virtual_machines[0]
    nic = vm.interfaces[0]
    existing = {'manual': 'retained', 'sync_network_observations': {'other-source': {'version': 1}}}
    fields = build_nic_custom_fields(vm, nic, existing)
    assert fields['manual'] == 'retained'
    assert fields['sync_network_observations']['other-source'] == {'version': 1}
    observed = fields['sync_network_observations'][vm.source_instance]
    assert observed['addresses'] == ['192.0.2.50/24', '192.0.2.50/32']
    assert observed['status'] == 'REVIEW_REQUIRED' and not observed['ipam_complete']
    assert build_nic_custom_fields(vm, nic, fields) == fields
    assert existing == {'manual': 'retained', 'sync_network_observations': {'other-source': {'version': 1}}}


def test_strict_mode_never_overwrites_saved_observations():
    from netbox_sync.netbox_vm_interface_metadata import build_nic_custom_fields
    vm = inventory()[0].virtual_machines[0]
    existing = {'sync_network_observations': {'old': {'status': 'REVIEW_REQUIRED'}}}
    assert build_nic_custom_fields(vm, vm.interfaces[0], existing)['sync_network_observations'] == existing['sync_network_observations']


def test_prerequisite_upgrade_only_adds_observation_field():
    from netbox_sync.prerequisites import FIELDS, VERSION, definition, reconcile
    assert VERSION == 2
    old = [dict(definition(name), id=index+1) for index, name in enumerate(FIELDS) if name != 'sync_network_observations']
    before = deepcopy(old)
    result = reconcile(old)
    assert [field['name'] for field in result if field['status'] == 'missing'] == ['sync_network_observations']
    assert all(field['status'] == 'ready' for field in result if field['name'] != 'sync_network_observations')
    assert old == before
    assert definition('sync_network_observations')['object_types'] == ['virtualization.vminterface']


@pytest.mark.parametrize('provider', ['esxi', 'proxmox'])
def test_http_observations_persist_on_interfaces_and_replan_without_duplicates(provider):
    from dataclasses import replace
    from tests.fakes import FakeNetBox, FakeRecord, FakeProxmox
    from tests.fakes.netbox_http import netbox_http
    from tests.test_first_sync import target
    from tests.sample_data import sample_source_config, proxmox_responses
    from netbox_sync.proxmox_discovery import discover_hosts as discover_proxmox
    from netbox_sync.netbox_full_apply import apply_full_sync
    from netbox_sync.esxi_runtime import execute_esxi_runtime
    from netbox_sync.application.runtime_plan import build_runtime_plan
    from netbox_sync.netbox_catalog import project
    from netbox_sync.prerequisites import definition
    seed = FakeNetBox()
    config = target(seed, esxi_config() if provider=='esxi' else replace(sample_source_config(), legacy_identity_owner=False))
    hosts = inventory() if provider=='esxi' else discover_proxmox(FakeProxmox(proxmox_responses()), config)
    for vm in [*hosts[0].virtual_machines, *hosts[0].containers]:
        vm.interfaces[0].ip_addresses = ['192.0.2.60/24', '192.0.2.60/32']
    refs = {kind:project(kind,record.serialize()) for kind,record in {
        'site':seed.dcim.sites.get(id=1),'cluster':seed.virtualization.clusters.get(id=3),
        'cluster_type':seed.virtualization.cluster_types.get(id=2),'platform':seed.dcim.platforms.get(id=5),
        'device_role':seed.dcim.device_roles.get(id=4)}.items()}
    refs['cluster']['type']={'id':2,'name':'Proxmox'}
    choice=project('device_type',{'id':6,'model':'Known hardware','slug':'generic','manufacturer':{'id':7,'name':'Manufacturer'}})
    mapping=dict(version=1,references=refs,host_types={h.source_id:choice for h in hosts},
                 hosts=[dict(id=h.source_id,manufacturer=None,model=None) for h in hosts],ip_conflict_policy='observe')
    config=replace(config,settings={'onboarding_mapping':mapping})
    seed.extras.custom_fields.add(FakeRecord(id=77,**definition('sync_network_observations')))
    seed.ipam.ip_addresses.add(FakeRecord(id=99,address='192.0.2.60/24',assigned_object_type='virtualization.vminterface',assigned_object_id=999,description='manual retained'))
    with netbox_http(seed) as (api,rows,writes):
        saved_field=rows['extras.custom_fields'].pop(77)
        blocked=build_runtime_plan(api,hosts,config)
        assert not blocked.apply_allowed and any(i.reason_code=='OBSERVATION_FIELD_REQUIRED' for i in blocked.items)
        assert writes==[]
        rows['extras.custom_fields'][77]=saved_field
        plan=build_runtime_plan(api,hosts,config)
        assert plan.apply_allowed and any(i.reason_code=='IP_OBSERVATION_ONLY' for i in plan.items)
        assert writes == []
        if provider=='esxi':execute_esxi_runtime(api,hosts,config,confirmed=True)
        else:apply_full_sync(api,hosts,config.target,confirmed=True)
        interfaces=rows['virtualization.interfaces']
        assert interfaces
        for row in interfaces.values():
            evidence=row['custom_fields']['sync_network_observations'][config.source_instance]
            assert evidence['addresses']==['192.0.2.60/24','192.0.2.60/32']
            assert evidence['status']=='REVIEW_REQUIRED'
        matching=[row for row in rows['ipam.ip_addresses'].values() if str(row['address']).startswith('192.0.2.60/')]
        assert len(matching)==1 and matching[0]['id']==99
        assert matching[0]['assigned_object_id']==999 and matching[0]['description']=='manual retained'
        writes.clear()
        repeated=build_runtime_plan(api,hosts,config)
        assert not any(i.action.value in ('CREATE','UPDATE') for i in repeated.items)
        assert any(i.reason_code=='IP_OBSERVATION_ONLY' for i in repeated.items)
        assert writes == []
