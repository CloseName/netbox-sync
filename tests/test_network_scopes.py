"""Explicit network scopes through real pynetbox HTTP, including VM and LXC."""
from copy import deepcopy
from dataclasses import replace
import pytest
from netbox_sync.network_scopes import rules, NetworkScopeError
from netbox_sync.netbox_catalog import project
from netbox_sync.application.runtime_plan import build_runtime_plan
from netbox_sync.netbox_full_apply import apply_full_sync
from netbox_sync.esxi_runtime import execute_esxi_runtime
from netbox_sync.prerequisites import definition
from tests.fakes import FakeNetBox, FakeRecord, FakeProxmox
from tests.fakes.netbox_http import netbox_http
from tests.test_first_sync import target
from tests.test_esxi_runtime import _config, _inventory
from tests.sample_data import sample_source_config, proxmox_responses
from netbox_sync.proxmox_discovery import discover_hosts


def fixture(provider):
    seed = FakeNetBox()
    config = target(seed, _config() if provider == 'esxi' else replace(sample_source_config(), legacy_identity_owner=False))
    hosts = _inventory(2) if provider == 'esxi' else discover_hosts(FakeProxmox(proxmox_responses()), config)
    refs = {kind: project(kind, record.serialize()) for kind, record in {
        'site': seed.dcim.sites.get(id=1), 'cluster': seed.virtualization.clusters.get(id=3),
        'cluster_type': seed.virtualization.cluster_types.get(id=2), 'platform': seed.dcim.platforms.get(id=5),
        'device_role': seed.dcim.device_roles.get(id=4)}.items()}
    refs['cluster']['type'] = {'id': 2, 'name': 'Proxmox'}
    choice = project('device_type', {'id': 6, 'model': 'Known hardware', 'slug': 'generic', 'manufacturer': {'id': 7, 'name': 'Manufacturer'}})
    selected = []
    members = [*hosts[0].virtual_machines, *hosts[0].containers]
    assert len(members) == 2
    for index, vm in enumerate(members, 10):
        nic = vm.interfaces[0]
        nic.bridge = f'isolated-{index}'
        nic.ip_addresses = ['192.0.2.60/24']
        row = dict(id=index, name=f'VRF {index}', rd=f'65000:{index}', enforce_unique=True)
        seed.ipam.vrfs.add(FakeRecord(**row))
        selected.append(dict(host_id=hosts[0].source_id, bridge=nic.bridge, vlan_id=nic.vlan_id, vrf=project('vrf', row)))
    seed.extras.custom_fields.add(FakeRecord(id=77, **definition('sync_network_observations')))
    mapping = dict(version=1, references=refs, host_types={h.source_id: choice for h in hosts},
                   hosts=[dict(id=h.source_id, manufacturer=None, model=None) for h in hosts],
                   ip_conflict_policy='observe', network_scope_rules=selected)
    return seed, replace(config, settings={'onboarding_mapping': mapping}), hosts


def apply(api, hosts, config):
    if config.source_type == 'esxi':
        return execute_esxi_runtime(api, hosts, config, confirmed=True)
    return apply_full_sync(api, hosts, config.target, confirmed=True)


@pytest.mark.parametrize('provider', ['esxi', 'proxmox'])
def test_explicit_existing_scopes_allow_same_ip_and_noop_replan(provider):
    seed, config, hosts = fixture(provider)
    requests = []
    with netbox_http(seed, requests=requests) as (api, rows, writes):
        plan = build_runtime_plan(api, hosts, config)
        assert plan.apply_allowed and not plan.conflicts
        assert not any(i.reason_code == 'IP_OBSERVATION_ONLY' for i in plan.items)
        assert writes == []
        apply(api, hosts, config)
        ips = list(rows['ipam.ip_addresses'].values())
        selected = [p for p in ips if p['address'] == '192.0.2.60/24']
        assert {p.get('vrf') for p in selected} == {10, 11}
        assert len({p['assigned_object_id'] for p in selected}) == 2
        before = deepcopy(rows)
        writes.clear()
        repeated = build_runtime_plan(api, hosts, config)
        assert repeated.apply_allowed
        assert not [i for i in repeated.items if i.action.value in ('CREATE', 'UPDATE')]
        assert writes == [] and rows == before
        assert not [(method, path) for method, path in requests if method != 'GET' and '/ipam/vrfs/' in path]


@pytest.mark.parametrize('provider', ['esxi', 'proxmox'])
def test_scope_change_retains_existing_assignments_as_observation(provider):
    seed, config, hosts = fixture(provider)
    with netbox_http(seed) as (api, rows, writes):
        apply(api, hosts, config)
        ips = deepcopy(rows['ipam.ip_addresses'])
        changed = deepcopy(dict(config.settings))
        changed['onboarding_mapping']['network_scope_rules'] = []
        config = replace(config, settings=changed)
        plan = build_runtime_plan(api, hosts, config)
        assert plan.apply_allowed and any(i.reason_code == 'IP_OBSERVATION_ONLY' for i in plan.items)
        apply(api, hosts, config)
        assert rows['ipam.ip_addresses'] == ips
        for nic in rows['virtualization.interfaces'].values():
            observation = nic['custom_fields']['sync_network_observations'][config.source_instance]
            assert not observation['ipam_complete']
            assert observation['scope_conflicts']


@pytest.mark.parametrize('change', ['missing', 'renamed'])
def test_changed_vrf_blocks_before_mutations(change):
    seed, config, hosts = fixture('esxi')
    with netbox_http(seed) as (api, rows, writes):
        if change == 'missing': rows['ipam.vrfs'].pop(10)
        else: rows['ipam.vrfs'][10]['name'] = 'Changed'
        plan = build_runtime_plan(api, hosts, config)
        assert not plan.apply_allowed
        assert any(i.reason_code == 'NETWORK_SCOPE_REVIEW_REQUIRED' for i in plan.items)
        assert writes == []


def test_rule_fencing_and_duplicate_selector():
    _, config, _ = fixture('esxi')
    selected = config.settings['onboarding_mapping']['network_scope_rules']
    with pytest.raises(NetworkScopeError): rules([selected[0], selected[0]])
    changed = deepcopy(selected)
    changed[0]['vrf']['id'] = 999
    with pytest.raises(NetworkScopeError): rules(changed)


@pytest.mark.parametrize('mask', [24, 32])
def test_foreign_existing_same_scope_address_is_observed_not_stolen(mask):
    seed, config, hosts = fixture('esxi')
    seed.ipam.ip_addresses.add(FakeRecord(id=90, address=f'192.0.2.60/{mask}', vrf=10,
        assigned_object_type='virtualization.vminterface', assigned_object_id=999, description='retained manual data'))
    with netbox_http(seed) as (api, rows, writes):
        foreign = deepcopy(rows['ipam.ip_addresses'][90])
        plan = build_runtime_plan(api, hosts, config)
        assert plan.apply_allowed and any(i.reason_code == 'IP_OBSERVATION_ONLY' for i in plan.items)
        apply(api, hosts, config)
        assert rows['ipam.ip_addresses'][90] == foreign
        assert len([r for r in rows['ipam.ip_addresses'].values() if r.get('vrf') == 10]) == 1
        assert len([r for r in rows['ipam.ip_addresses'].values() if r.get('vrf') == 11]) == 1
        repeated = build_runtime_plan(api, hosts, config)
        assert not [i for i in repeated.items if i.action.value in ('CREATE','UPDATE')]


def test_host_global_address_does_not_match_same_address_in_explicit_vrf():
    from netbox_sync.netbox_apply import _find_ip_matches
    seed = FakeNetBox()
    seed.ipam.ip_addresses.add(FakeRecord(id=1,address='192.0.2.60/24',vrf=10))
    seed.ipam.ip_addresses.add(FakeRecord(id=2,address='192.0.2.60/24',vrf=None))
    assert [r.id for r in _find_ip_matches(seed,'192.0.2.60/24')] == [2]


def test_vrf_read_refusal_is_not_converted_to_empty_inventory():
    from pynetbox.core.query import RequestError
    seed, config, hosts = fixture('esxi')
    with netbox_http(seed,behavior={'deny_reads':['ipam.vrfs']}) as (api, rows, writes):
        with pytest.raises(RequestError): build_runtime_plan(api, hosts, config)
        assert writes == []
