from copy import deepcopy

import pytest

from netbox_sync.application.runtime_plan import build_runtime_plan
from netbox_sync.api.dto import SyncPlanDTO
from netbox_sync.esxi_runtime import execute_esxi_runtime
from netbox_sync.netbox_record_values import object_id
from tests.test_esxi_runtime import _config, _manual_primary, _setup


@pytest.mark.parametrize("name_field", ["name", "bridge"])
def test_unowned_interface_only_defers_its_guest_network(fake_netbox, name_field):
    config = _config()
    hosts, card, legacy = _setup(fake_netbox)
    fake_netbox.virtualization.virtual_machines.records.remove(legacy)
    guest, peer = hosts[0].virtual_machines
    manual, ip = _manual_primary(fake_netbox, card)
    manual.name = getattr(guest.interfaces[0], name_field).upper()
    before = deepcopy(manual.serialize()), deepcopy(ip.serialize())
    for _ in range(2):
        plan = build_runtime_plan(fake_netbox, hosts, config)
        assert plan.apply_allowed
        SyncPlanDTO.from_worker({**plan.canonical_dict(), "digest": plan.digest})
        collisions = [row for row in plan.items if row.reason_code == "VM_NIC_NAME_OCCUPIED"]
        assert len(collisions) == 1 and collisions[0].matched_object_id == manual.id
        assert guest.original_name in collisions[0].name
        execute_esxi_runtime(fake_netbox, hosts, config, confirmed=True)
        assert (manual.serialize(), ip.serialize()) == before
        assert card.primary_ip4.id == ip.id
        assert card.vcpus == 4
        nics = fake_netbox.virtualization.interfaces.all()
        assert len(nics) == 2
        cards = fake_netbox.virtualization.virtual_machines.all()
        assert len(cards) == 2
        peer_card = next(vm for vm in cards if vm.name == peer.original_name)
        assert any(object_id(nic.virtual_machine) == peer_card.id and nic.custom_fields.get("sync_identities") for nic in nics)

    manual.name = "operator-port"
    resumed = build_runtime_plan(fake_netbox, hosts, config)
    assert resumed.apply_allowed and all(row.reason_code != "VM_NIC_NAME_OCCUPIED" for row in resumed.items)
    execute_esxi_runtime(fake_netbox, hosts, config, confirmed=True)
    assert len(fake_netbox.virtualization.interfaces.all()) == 3
    assert card.primary_ip4.id == ip.id
