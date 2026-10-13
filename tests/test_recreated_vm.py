"""A missing owned VM must not lend its identity or network to its replacement."""
from copy import deepcopy
import pytest
from netbox_sync.application.runtime_plan import build_runtime_plan
from netbox_sync.esxi_runtime import execute_esxi_runtime
from netbox_sync.netbox_vm_metadata import build_vm_custom_fields
from tests.test_esxi_runtime import _setup, _config, _manual_primary


def replacement(api):
    hosts, managed, old = _setup(api)
    new = hosts[0].virtual_machines[1]
    previous = deepcopy(new)
    previous.external_id = previous.vmid = '52000000-1111-2222-3333-444444444444'
    previous.source_id = 'esxi:' + previous.external_id
    old.custom_fields = build_vm_custom_fields(previous)
    api.base_url = 'https://netbox.example/api'
    return hosts, managed, old, new


def test_replacement_is_isolated_other_vm_updates_and_old_network_survives(fake_netbox):
    hosts, managed, old, new = replacement(fake_netbox)
    interface, ip = _manual_primary(fake_netbox, old)
    before = deepcopy(old.serialize()), deepcopy(interface.serialize()), deepcopy(ip.serialize())
    plan = build_runtime_plan(fake_netbox, hosts, _config())
    assert plan.apply_allowed
    row = next(i for i in plan.items if i.reason_code == 'VM_RECREATED_NAME')
    assert row.action.value == 'REVIEW_REQUIRED'
    assert row.matched_object_id is None  # Evidence is not permission to adopt.
    candidate = dict(row.before)['matching_candidates'][0]
    assert candidate['id'] == old.id
    assert candidate['url'] == f'https://netbox.example/virtualization/virtual-machines/{old.id}/'
    assert candidate['external_ids'] != [new.external_id]
    assert fake_netbox.mutations == []
    execute_esxi_runtime(fake_netbox, hosts, _config(), confirmed=True)
    assert managed.vcpus == 4
    assert (old.serialize(), interface.serialize(), ip.serialize()) == before
    assert len(fake_netbox.virtualization.virtual_machines.all()) == 2


@pytest.mark.parametrize('case', ['foreign', 'still_present', 'duplicate', 'network'])
def test_real_ambiguities_remain_blocked(fake_netbox, case):
    hosts, _, old, new = replacement(fake_netbox)
    if case == 'foreign':
        old.custom_fields['sync_identities'][0]['instance'] = 'another-source'
    elif case == 'still_present':
        previous = deepcopy(new)
        previous.external_id = previous.vmid = old.custom_fields['sync_identities'][0]['external_id']
        previous.source_id = 'esxi:' + previous.external_id
        previous.original_name = 'renamed-old'
        previous.esxi_instance_uuid = previous.external_id
        previous.esxi_bios_uuid = '42000000-1111-2222-3333-444444444444'
        previous.provider_object_id = 'vm-999'
        previous.interfaces = []
        hosts[0].virtual_machines.append(previous)
    elif case == 'duplicate':
        from tests.fakes import FakeRecord
        fake_netbox.virtualization.virtual_machines.add(FakeRecord(
            id=100, name=old.name, cluster=old.cluster, custom_fields=deepcopy(old.custom_fields)))
    else:
        _, ip = _manual_primary(fake_netbox, old)
        new.interfaces[0].ip_addresses = [str(ip.address)]
    plan = build_runtime_plan(fake_netbox, hosts, _config())
    assert not plan.apply_allowed
    assert fake_netbox.mutations == []


def test_rename_allows_separate_creation_without_rebinding_old(fake_netbox):
    hosts, _, old, new = replacement(fake_netbox)
    before = deepcopy(old.serialize())
    new.original_name = 'replacement-with-new-name'
    plan = build_runtime_plan(fake_netbox, hosts, _config())
    assert plan.apply_allowed
    assert any(i.action.value == 'CREATE' and i.object_kind == 'virtualization.virtual_machines'
               for i in plan.items)
    execute_esxi_runtime(fake_netbox, hosts, _config(), confirmed=True)
    assert old.serialize() == before
    assert len(fake_netbox.virtualization.virtual_machines.all()) == 3
