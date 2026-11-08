"""Two ESXi collections after a generation change or conflicting guest report."""

from copy import deepcopy
import pytest
from netbox_sync.application.runtime_plan import build_runtime_plan
from netbox_sync.esxi_runtime import execute_esxi_runtime
from netbox_sync.esxi_discovery import discover_hosts
from tests.fakes.esxi import fake_esxi_service
from tests.fakes.netbox_http import netbox_http
from tests.test_network_scopes import fixture


@pytest.mark.parametrize("scenario", ["RAV", "PAM"])
@pytest.mark.parametrize("policy", ["observe", "strict"])
def test_two_collections_keep_distinct_vm_ownership(scenario, policy):
    seed, config, _ = fixture("esxi")
    config.target.onboarding_mapping["network_scope_rules"] = []
    config.target.onboarding_mapping["ip_conflict_policy"] = policy
    owner_name, guest_name = (
        ("RAV_main_DB", "RAV_CM_Client")
        if scenario == "RAV"
        else ("AL - IPAMA on WinSrv 2022", "Service - Resource on WinSrv 2022 (Used UI tests)")
    )
    service = fake_esxi_service(vm_name=owner_name)
    owner = service.host.vm[0]
    guest = deepcopy(owner)
    guest.name = guest_name
    guest._moId = "vm-41"
    guest.config.instanceUuid = "503c5ad7-aaaa-bbbb-cccc-0123456789ab"
    guest.config.uuid = "42000000-aaaa-bbbb-cccc-0123456789ab"
    guest.config.hardware.device[1].macAddress = "00:0c:29:42:b5:3c"
    guest.config.hardware.device[1].backing.deviceName = "LAN6"
    owner.guest.net[0].ipConfig.ipAddress[0].ipAddress = "10.11.5.250"
    owner.guest.net[0].ipAddress = ["10.11.5.250"]
    guest.guest.net = []
    if scenario == "RAV":
        service.host.vm.append(guest)
    with netbox_http(seed) as (api, rows, writes):
        execute_esxi_runtime(api, discover_hosts(service, config), config, confirmed=True)
        cards = rows["virtualization.virtual_machines"]
        old = {pk: deepcopy(row["custom_fields"]["sync_identities"]) for pk, row in cards.items()}
        address = next(r for r in rows["ipam.ip_addresses"].values() if r["address"] == "10.11.5.250/24")
        assigned = address["assigned_object_id"]
        if scenario == "RAV":
            for i, vm in enumerate((owner, guest), 1):
                vm.config.instanceUuid = f"52340000-0000-0000-0000-{i:012d}"
        else:
            owner.runtime.powerState = "poweredOff"
            guest.guest.net = deepcopy(owner.guest.net)
            guest.guest.net[0].macAddress = guest.config.hardware.device[1].macAddress
            owner.guest.net = []
            service.host.vm.append(guest)
        for index in range(2):
            if index:
                service.host.vm.reverse()
            inventory = discover_hosts(service, config)
            writes.clear()
            plan = build_runtime_plan(api, inventory, config)
            assert plan.apply_allowed and not writes
            execute_esxi_runtime(api, inventory, config, confirmed=True)
            assert len(cards) == (4 if scenario == "RAV" else 2)
            assert all(cards[pk]["custom_fields"]["sync_identities"] == ids for pk, ids in old.items())
            assert rows["ipam.ip_addresses"][address["id"]]["assigned_object_id"] == assigned
            if policy == "observe":
                assert any(
                    nic["custom_fields"]
                    .get("sync_network_observations", {})
                    .get(config.source_instance, {})
                    .get("addresses")
                    == [address["address"]]
                    for nic in rows["virtualization.interfaces"].values()
                    if nic["id"] != assigned
                )
            else:
                assert any(row.reason_code == "VM_NETWORK_DEFERRED" for row in plan.items)
            if index:
                # Another host hardware observation can advance its timestamp.
                assert all((method, endpoint) == ('PATCH', 'dcim.devices') for method, endpoint, _ in writes)
