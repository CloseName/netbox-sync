"""Inventory evidence must distinguish repeated facts from ambiguous ownership."""
from copy import deepcopy
from dataclasses import asdict
import json
from netbox_sync.esxi_discovery import discover_hosts
from netbox_sync.application.inventory_conflicts import inventory_conflicts
from netbox_sync.application.inventory_order import canonical_hosts
from netbox_sync.application.runtime_plan import build_runtime_plan
from netbox_sync.api.dto import SyncPlanDTO
from tests.fakes.esxi import fake_esxi_service
from tests.test_esxi import esxi_config


def test_repeated_managed_object_is_collected_once():
    service = fake_esxi_service()
    service.host.vm.append(service.host.vm[0])
    hosts = discover_hosts(service, esxi_config())
    assert len(hosts[0].virtual_machines) == 1
    assert not inventory_conflicts(hosts)


def test_distinct_objects_sharing_identity_block_before_netbox_calls():
    service = fake_esxi_service()
    other = deepcopy(service.host.vm[0])
    other._moId = 'vm-999'
    other.name = 'other VM'
    service.host.vm.append(other)
    hosts = discover_hosts(service, esxi_config())
    plan = build_runtime_plan(object(), hosts, esxi_config())
    assert not plan.apply_allowed
    conflict = next(c for c in plan.conflicts if c.kind == 'VM_IDENTITY')
    assert len({p.provider_object_id for p in conflict.participants}) == 2
    assert {p.name for p in conflict.participants} == {other.name, service.host.vm[0].name}
    public = SyncPlanDTO.from_worker(json.loads(plan.canonical_json()) | {'digest': plan.digest})
    assert public.conflicts
    hosts[0].virtual_machines.reverse()
    assert build_runtime_plan(object(), hosts, esxi_config()).digest == plan.digest


def test_same_interface_fact_deduplicated_but_other_interface_blocks():
    hosts = discover_hosts(fake_esxi_service(), esxi_config())
    nic = hosts[0].virtual_machines[0].interfaces[0]
    nic.ip_addresses *= 2
    assert not inventory_conflicts(hosts)
    normalized = canonical_hosts(hosts)
    assert len(normalized[0].virtual_machines[0].interfaces[0].ip_addresses) == 1
    other = deepcopy(nic)
    other.name = 'another NIC'
    other.external_id = '4001'
    other.bridge = 'different network label'
    other.vlan_id = 999
    hosts[0].virtual_machines[0].interfaces.append(other)
    conflicts = inventory_conflicts(hosts)
    assert len(conflicts) == 1
    assert len(conflicts[0].participants) == 2


def test_different_prefixes_do_not_hide_same_address_conflict():
    hosts = discover_hosts(fake_esxi_service(), esxi_config())
    nic = hosts[0].virtual_machines[0].interfaces[0]
    nic.ip_addresses = ['192.0.2.50/24', '192.0.2.50/32']
    assert inventory_conflicts(hosts)[0].kind == 'IP_ASSIGNMENT'


def test_evidence_excludes_vm_description():
    hosts = discover_hosts(fake_esxi_service(), esxi_config())
    vm = hosts[0].virtual_machines[0]
    vm.description = 'PRIVATE-DESCRIPTION'
    other = deepcopy(vm)
    other.provider_object_id = 'vm-888'
    hosts[0].virtual_machines.append(other)
    assert 'PRIVATE-DESCRIPTION' not in json.dumps([asdict(c) for c in inventory_conflicts(hosts)])


def test_prepare_refuses_structured_conflict(monkeypatch):
    from netbox_sync.apply_worker import ApplySupervisor, ApplyWorkerError
    import pytest
    hosts = discover_hosts(fake_esxi_service(), esxi_config())
    hosts[0].virtual_machines.append(deepcopy(hosts[0].virtual_machines[0]))
    plan = build_runtime_plan(object(), hosts, esxi_config())
    supervisor = ApplySupervisor('', '', '', '', '', '', '')
    monkeypatch.setattr(supervisor, '_source', lambda _: esxi_config())
    monkeypatch.setattr(supervisor, '_payload', lambda *_: {})
    monkeypatch.setattr(supervisor, '_child', lambda _: plan.canonical_dict() | {'digest':plan.digest})
    with pytest.raises(ApplyWorkerError, match='PLAN_BLOCKED') as caught:
        supervisor.prepare(esxi_config().source_instance, plan.digest)
    assert caught.value.reason == 'PLAN_FORBIDDEN'


def test_repeated_guest_records_preserve_all_addresses_without_duplicate_facts():
    service = fake_esxi_service()
    vm = service.host.vm[0]
    network = deepcopy(vm.guest.net[0])
    network.ipConfig.ipAddress[0].ipAddress = '192.0.2.51'
    vm.guest.net.extend([deepcopy(vm.guest.net[0]), network])
    result = discover_hosts(service, esxi_config())[0].virtual_machines[0]
    assert result.interfaces[0].ip_addresses == ['192.0.2.50/24', '192.0.2.51/24']


def test_different_vm_identity_same_ip_is_network_conflict_only():
    hosts = discover_hosts(fake_esxi_service(), esxi_config())
    other = deepcopy(hosts[0].virtual_machines[0])
    other.external_id = 'different-id'
    other.provider_object_id = 'vm-123'
    hosts[0].virtual_machines.append(other)
    assert [c.kind for c in inventory_conflicts(hosts)] == ['IP_ASSIGNMENT']


import pytest
@pytest.mark.parametrize('provider', ['esxi', 'proxmox'])
def test_readded_source_does_not_automatically_acquire_retained_objects(provider):
    from dataclasses import replace
    from tests.fakes import FakeNetBox, FakeProxmox
    from tests.fakes.netbox_http import netbox_http
    from tests.test_first_sync import target
    from tests.sample_data import sample_source_config, proxmox_responses
    from netbox_sync.proxmox_discovery import discover_hosts as discover_proxmox
    from netbox_sync.netbox_full_apply import apply_full_sync
    from netbox_sync.esxi_runtime import execute_esxi_runtime
    config = esxi_config() if provider == 'esxi' else replace(sample_source_config(), legacy_identity_owner=False)
    hosts = (discover_hosts(fake_esxi_service(), config) if provider == 'esxi'
             else discover_proxmox(FakeProxmox(proxmox_responses()), config))
    seed = FakeNetBox(); target(seed, config)
    with netbox_http(seed) as (api, rows, writes):
        if provider == 'esxi': execute_esxi_runtime(api, hosts, config, confirmed=True)
        else: apply_full_sync(api, hosts, config.target, confirmed=True)
        saved = deepcopy(rows)
        writes.clear()
        new_config = replace(config, id='readded-source', source_instance='readded-source')
        for host in hosts:
            host.source_instance = new_config.source_instance
            for vm in [*host.virtual_machines, *host.containers]: vm.source_instance = new_config.source_instance
        # Re-registration is not evidence authorizing adoption of another owner's rows.
        plan = build_runtime_plan(api, hosts, new_config)
        assert not any(i.action.value in ('CREATE', 'UPDATE') for i in plan.items)
        assert writes == [] and rows == saved


def test_equivalent_address_notation_is_one_fact_on_one_interface():
    hosts = discover_hosts(fake_esxi_service(), esxi_config())
    nic = hosts[0].virtual_machines[0].interfaces[0]
    nic.ip_addresses = ['2001:db8::1/64', '2001:0db8:0:0:0:0:0:1/64']
    normalized = canonical_hosts(hosts)
    assert normalized[0].virtual_machines[0].interfaces[0].ip_addresses == ['2001:db8::1/64']
    assert not inventory_conflicts(normalized)
