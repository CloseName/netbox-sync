"""First synchronization regressions; controlled inventory only."""
from dataclasses import replace
from tests.fakes import FakeNetBox, FakeRecord, FakeProxmox
from tests.netbox_scenarios import add_target
from tests.sample_data import sample_source_config, proxmox_responses
from netbox_sync.proxmox_discovery import discover_hosts
from netbox_sync.application.runtime_plan import build_runtime_plan


def target(api, config):
    add_target(api)
    api.dcim.device_roles.add(FakeRecord(id=4,name='Server',slug='server'))
    api.dcim.platforms.add(FakeRecord(id=5,name='Proxmox',slug='proxmox'))
    api.dcim.device_types.add(FakeRecord(id=6,model='Known hardware',slug='generic',manufacturer=FakeRecord(id=7,name='Manufacturer')))
    return config


def test_proxmox_empty_target_full_plan():
    api=FakeNetBox();config=target(api,replace(sample_source_config(),legacy_identity_owner=False))
    hosts=discover_hosts(FakeProxmox(proxmox_responses()),config)
    plan=build_runtime_plan(api,hosts,config)
    assert api.mutations==[]
    assert plan.apply_allowed
    assert any(i.action.value=='CREATE' and i.object_kind=='dcim.devices' for i in plan.items)
    assert sum(i.action.value=='CREATE' and i.object_kind=='virtualization.virtual_machines' for i in plan.items)==2


def test_esxi_empty_target_full_plan():
    from tests.test_esxi_runtime import _config, _inventory
    api=FakeNetBox();config=target(api,_config());hosts=_inventory(1)
    plan=build_runtime_plan(api,hosts,config)
    assert api.mutations==[] and plan.apply_allowed
    assert any(i.action.value=='CREATE' and i.object_kind=='dcim.devices' for i in plan.items)
    assert any(i.action.value=='CREATE' and i.object_kind=='virtualization.virtual_machines' for i in plan.items)


import pytest
from tests.fakes.netbox_http import netbox_http

@pytest.mark.parametrize(('provider', 'existing_host'), [('proxmox', False), ('proxmox', True), ('esxi', False)])
def test_real_pynetbox_plan_apply_replan_new_source(provider, existing_host):
    from tests.test_esxi_runtime import _config, _inventory
    from netbox_sync.netbox_full_apply import apply_full_sync
    from netbox_sync.esxi_runtime import execute_esxi_runtime
    from netbox_sync.netbox_catalog import project
    seed=FakeNetBox()
    config=target(seed,_config() if provider=='esxi' else replace(sample_source_config(),legacy_identity_owner=False))
    hosts=_inventory(1) if provider=='esxi' else discover_hosts(FakeProxmox(proxmox_responses()),config)
    refs={kind:project(kind,record.serialize()) for kind,record in {
        'site':seed.dcim.sites.get(id=1),'cluster':seed.virtualization.clusters.get(id=3),
        'cluster_type':seed.virtualization.cluster_types.get(id=2),'platform':seed.dcim.platforms.get(id=5),
        'device_role':seed.dcim.device_roles.get(id=4)}.items()}
    refs['cluster']['type']={'id':2,'name':'Proxmox'}
    choice=project('device_type',{'id':6,'model':'Known hardware','slug':'generic','manufacturer':{'id':7,'name':'Manufacturer'}})
    mapping=dict(version=1,references=refs,host_types={h.source_id:choice for h in hosts},
                 hosts=[dict(id=h.source_id,manufacturer=None,model=None) for h in hosts])
    config=replace(config,settings={'onboarding_mapping':mapping})
    requests=[]
    behavior={}
    with netbox_http(seed, requests=requests, behavior=behavior) as (api,rows,writes):
        if existing_host:
            from netbox_sync.netbox_apply import apply_hosts
            apply_hosts(api,hosts,config.target,confirmed=True)
            assert rows['dcim.devices'] and rows['dcim.interfaces']
            assert not rows['virtualization.virtual_machines']
            writes.clear()
        plan=build_runtime_plan(api,hosts,config)
        assert writes==[] and plan.apply_allowed
        assert any(i.action.value=='CREATE' for i in plan.items)
        assert not [i for i in plan.items if i.reason_code=='EXECUTOR_CREATE_UNSUPPORTED']
        if provider=='esxi':assert any(i.reason_code=='ESXI_HOST_NETWORK_UNSUPPORTED' for i in plan.items)
        if provider=='proxmox':apply_full_sync(api,hosts,config.target,confirmed=True)
        else:execute_esxi_runtime(api,hosts,config,confirmed=True)
        assert len(rows['dcim.devices'])==1
        assert len(rows['virtualization.virtual_machines'])==(2 if provider=='proxmox' else 1)
        assert rows['virtualization.interfaces']
        if provider=='proxmox':
            assert rows['dcim.interfaces']
            assert {r['virtual_machine'] for r in rows['virtualization.interfaces'].values()} == set(rows['virtualization.virtual_machines'])
        writes.clear()
        repeated=build_runtime_plan(api,hosts,config)
        assert writes==[]
        assert not [i for i in repeated.items if i.action.value in ('CREATE','UPDATE')]
        behavior['reverse_reads']=True
        assert build_runtime_plan(api,hosts,config).digest==repeated.digest
        assert requests and not any('/-' in path or '=-' in path for _,path in requests)


def test_esxi_report_only_network_survives_public_discovery_contract():
    from dataclasses import asdict
    from tests.test_esxi_runtime import _config, _inventory
    from netbox_sync.application.discovery_review import build_esxi_review
    from netbox_sync.esxi_adoption import build_esxi_adoption_plan
    from netbox_sync.api.dto import DiscoveryResultDTO
    api=FakeNetBox();config=target(api,_config())
    review=build_esxi_review(build_esxi_adoption_plan(api,_inventory(1),config),config)
    result=DiscoveryResultDTO.model_validate(asdict(review))
    assert any(i.object_kind=='host_network' and i.classification=='UNSUPPORTED' for i in result.items)


def test_reordered_provider_inventory_has_identical_exact_plan():
    from copy import deepcopy
    from netbox_sync.discovery import DiscoveredHostInterface
    seed = FakeNetBox()
    config = target(seed, replace(sample_source_config(), legacy_identity_owner=False))
    hosts = discover_hosts(FakeProxmox(proxmox_responses()), config)
    hosts[0].interfaces.extend([DiscoveredHostInterface(name='eth9', interface_type='eth'), DiscoveredHostInterface(name='eth8', interface_type='eth')])
    second_host = deepcopy(hosts[0])
    second_host.source_id = 'node-b'; second_host.original_name = 'node-b'; second_host.normalized_name = 'NODE-B'
    second_host.management_ip = '10.20.30.11'; second_host.interfaces[0].addresses = ['10.20.30.11/24']; second_host.virtual_machines = []; second_host.containers = []
    hosts.append(second_host)
    other = deepcopy(hosts)
    other[0].interfaces.reverse()
    other.reverse()
    with netbox_http(seed) as (api, _rows, writes):
        first = build_runtime_plan(api, hosts, config)
        second = build_runtime_plan(api, other, config)
        assert first.digest == second.digest
        api.token = 'test-read-only'
        read_plan = build_runtime_plan(api, hosts, config)
        api.token = 'test-apply-capable'
        assert build_runtime_plan(api, hosts, config).digest == read_plan.digest
        # A different token is harmless only when it sees identical relevant data.
        other[0].memory_bytes += 1024**3
        assert build_runtime_plan(api, other, config).digest != first.digest
        assert not writes
