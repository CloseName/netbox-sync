"""VM names use the same bounded value in plans, writes and conflict checks."""
from copy import deepcopy
import pytest
from netbox_sync.proxmox_discovery import discover_hosts
from netbox_sync.esxi_discovery import discover_hosts as discover_esxi
from netbox_sync.application.runtime_plan import build_runtime_plan
from netbox_sync.netbox_full_apply import apply_full_sync
from netbox_sync.netbox_vm_apply import apply_virtual_machines, VMApplyError
from netbox_sync.esxi_runtime import execute_esxi_runtime
from tests.fakes import FakeProxmox
from tests.fakes.esxi import fake_esxi_service
from tests.sample_data import proxmox_responses, sample_source_config
from tests.test_esxi_runtime import _config
from tests.test_first_sync import target
from tests.fakes.netbox_http import netbox_http

@pytest.mark.parametrize("provider", ["esxi", "proxmox"])
@pytest.mark.parametrize("length", [63, 64, 65, 117])
def test_name_plan_create_update_replan(provider, length, fake_netbox):
    if provider == "esxi":
        config = _config()
        hosts = discover_esxi(fake_esxi_service(), config)
        execute = lambda: execute_esxi_runtime(fake_netbox, hosts, config, confirmed=True)
    else:
        config = sample_source_config()
        hosts = discover_hosts(FakeProxmox(proxmox_responses()), config)
        execute = lambda: apply_full_sync(fake_netbox, hosts, config.target, confirmed=True)
    vm = hosts[0].virtual_machines[0]
    original = "Р В РІР‚вЂњ" * length
    vm.original_name = original
    target(fake_netbox, config)
    with netbox_http(fake_netbox) as (fake_netbox, _, _):
        plan = build_runtime_plan(fake_netbox, hosts, config)
        assert any(row.object_kind == "virtualization.virtual_machines"
                   and row.action.value == "CREATE"
                   and dict(row.after).get("name") == original[:64]
                   for row in plan.items)
        execute()
        stored = next(v for v in fake_netbox.virtualization.virtual_machines.all()
                      if v.name == original[:64])
        assert vm.original_name == original
        assert not [r for r in build_runtime_plan(fake_netbox, hosts, config).items
                    if r.action.value in ("CREATE", "UPDATE")]
        vm.original_name = "R" * 117
        execute()
        assert fake_netbox.virtualization.virtual_machines.get(id=stored.id).name == "R" * 64
        assert not [r for r in build_runtime_plan(fake_netbox, hosts, config).items
                    if r.action.value in ("CREATE", "UPDATE")]

def test_truncated_collision_blocks_before_vm_creation(fake_netbox):
    config = _config()
    hosts = discover_esxi(fake_esxi_service(), config)
    first = hosts[0].virtual_machines[0]
    first.original_name = "x" * 64 + "a"
    second = deepcopy(first)
    second.original_name = "x" * 64 + "b"
    second.external_id = second.vmid = "503c5ad7-aaaa-bbbb-cccc-0123456789ab"
    second.source_id = "esxi:" + second.external_id
    hosts[0].virtual_machines.append(second)
    target(fake_netbox, config)
    with pytest.raises(VMApplyError, match="Duplicate discovered VM names"):
        apply_virtual_machines(fake_netbox, hosts, config.target, confirmed=True)
    assert not list(fake_netbox.virtualization.virtual_machines.all())


def test_bootstrap_detects_truncated_existing_name(fake_netbox):
    from tests.test_esxi_vm_bootstrap import _setup, _add_vm
    from netbox_sync.esxi_vm_bootstrap import _validate_target_names, EsxiNewVmBootstrapError
    cluster, hosts, _ = _setup(fake_netbox)
    vm = hosts[0].virtual_machines[0]
    vm.original_name = "z" * 64 + "suffix"
    _add_vm(fake_netbox, cluster, 99, "z" * 64)
    with pytest.raises(EsxiNewVmBootstrapError, match="Desired VM name already exists"):
        _validate_target_names(fake_netbox, cluster, [vm])


def test_bootstrap_detects_truncated_source_names(fake_netbox):
    from tests.test_esxi_vm_bootstrap import _setup
    from netbox_sync.esxi_vm_bootstrap import _validate_target_names, EsxiNewVmBootstrapError
    cluster, hosts, _ = _setup(fake_netbox, count=2)
    vms = hosts[0].virtual_machines
    for i, vm in enumerate(vms):
        vm.original_name = "z" * 64 + str(i)
    with pytest.raises(EsxiNewVmBootstrapError, match="Duplicate VM names after truncation"):
        _validate_target_names(fake_netbox, cluster, vms)
