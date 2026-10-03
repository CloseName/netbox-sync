"""Comments match persisted trimming without losing internal formatting."""
import pytest
from tests.test_vm_name_length import (
    _config, discover_esxi, fake_esxi_service, sample_source_config,
    discover_hosts, FakeProxmox, proxmox_responses, target, netbox_http,
    execute_esxi_runtime, apply_full_sync, build_runtime_plan,
)

@pytest.mark.parametrize("provider", ["esxi", "proxmox"])
def test_comments_create_update_and_replan(provider, fake_netbox):
    config = _config() if provider == "esxi" else sample_source_config()
    hosts = (discover_esxi(fake_esxi_service(), config) if provider == "esxi"
             else discover_hosts(FakeProxmox(proxmox_responses()), config))
    vm = hosts[0].virtual_machines[0]
    vm.description = "  Heading\n\n  indented line  \nlast\n   "
    target(fake_netbox, config)
    def execute():
        if provider == "esxi":
            execute_esxi_runtime(fake_netbox, hosts, config, confirmed=True)
        else:
            apply_full_sync(fake_netbox, hosts, config.target, confirmed=True)
    with netbox_http(fake_netbox) as (fake_netbox, _, _):
        api = fake_netbox
        execute()
        record = next(r for r in api.virtualization.virtual_machines.all()
                      if r.name == vm.original_name)
        assert record.comments == "Heading\n\n  indented line  \nlast"
        # Existing live NetBox values are already trimmed.
        record.update({"comments": vm.description.strip()})
        def changes():
            return [r for r in build_runtime_plan(api, hosts, config).items
                    if r.action.value in ("CREATE", "UPDATE")]
        assert not changes()
        vm.description = "\n Heading\n\n  changed line  \nlast   "
        assert changes()
        execute()
        assert api.virtualization.virtual_machines.get(id=record.id).comments == vm.description.strip()
        assert not changes()
        vm.description = None
        assert not changes()  # Missing source comments do not clear existing text.
        vm.description = " \n\t "
        execute()
        assert api.virtualization.virtual_machines.get(id=record.id).comments == ""
        assert not changes()
