"""Two ESXi collections after a generation change or conflicting guest report."""
from copy import deepcopy
import pytest
from netbox_sync.application.runtime_plan import build_runtime_plan
from netbox_sync.esxi_runtime import execute_esxi_runtime
from tests.fakes.netbox_http import netbox_http
from tests.test_network_scopes import fixture


@pytest.mark.parametrize("scenario", ["RAV", "PAM"])
@pytest.mark.parametrize("policy", ["observe", "strict"])
def test_two_collections_keep_distinct_vm_ownership(scenario, policy):
    seed, config, hosts = fixture("esxi")
    config.target.onboarding_mapping["network_scope_rules"] = []
    config.target.onboarding_mapping["ip_conflict_policy"] = policy
    owner, guest = hosts[0].virtual_machines
    owner.original_name, guest.original_name = ("RAV_main_DB", "RAV_CM_Client") if scenario == "RAV" else (
        "AL - IPAMA on WinSrv 2022", "Service - Resource on WinSrv 2022 (Used UI tests)")
    owner.interfaces[0].ip_addresses = ["10.11.5.250/24"]
    guest.interfaces[0].ip_addresses = []
    with netbox_http(seed) as (api, rows, writes):
        previous = deepcopy(hosts)
        if scenario == "PAM":
            previous[0].virtual_machines.pop()
        execute_esxi_runtime(api, previous, config, confirmed=True)
        cards = rows["virtualization.virtual_machines"]
        old = {pk: deepcopy(row["custom_fields"]["sync_identities"]) for pk, row in cards.items()}
        address = next(r for r in rows["ipam.ip_addresses"].values() if r["address"] == "10.11.5.250/24")
        assigned = address["assigned_object_id"]
        if scenario == "RAV":
            for i, vm in enumerate((owner, guest), 1):
                vm.esxi_instance_uuid = vm.external_id = vm.vmid = f"52340000-0000-0000-0000-{i:012d}"
                vm.source_id = "esxi:" + vm.external_id
        else:
            owner.status = "stopped"
            owner.interfaces[0].ip_addresses = []
            guest.interfaces[0].ip_addresses = [address["address"]]
        for index in range(2):
            inventory = deepcopy(hosts)
            if index:
                inventory[0].virtual_machines.reverse()
            writes.clear()
            plan = build_runtime_plan(api, inventory, config)
            assert plan.apply_allowed and not writes
            execute_esxi_runtime(api, inventory, config, confirmed=True)
            assert len(cards) == (4 if scenario == "RAV" else 2)
            assert all(cards[pk]["custom_fields"]["sync_identities"] == ids for pk, ids in old.items())
            assert rows["ipam.ip_addresses"][address["id"]]["assigned_object_id"] == assigned
            if policy == "observe":
                assert any(nic["custom_fields"].get("sync_network_observations", {}).get(
                    config.source_instance, {}).get("addresses") == [address["address"]]
                    for nic in rows["virtualization.interfaces"].values() if nic["id"] != assigned)
            else:
                assert any(row.reason_code == "VM_NETWORK_DEFERRED" for row in plan.items)
            if index:
                assert not writes
