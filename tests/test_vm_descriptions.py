"""Full provider text is planned and applied; absent does not mean empty."""
from dataclasses import replace
from types import SimpleNamespace
import pytest
from netbox_sync.proxmox_discovery import discover_hosts
from netbox_sync.esxi_discovery import discover_hosts as discover_esxi
from netbox_sync.netbox_vm_apply import build_vm_create_fields, _vm_changes
from netbox_sync.application.runtime_plan import build_runtime_plan
from netbox_sync.netbox_full_apply import apply_full_sync
from netbox_sync.esxi_runtime import execute_esxi_runtime
from tests.fakes import FakeProxmox
from tests.fakes.esxi import fake_esxi_service
from tests.sample_data import proxmox_responses, sample_source_config
from tests.netbox_scenarios import add_target
from tests.test_esxi_runtime import _config

@pytest.mark.parametrize('provider',['proxmox','esxi'])
@pytest.mark.parametrize('value',[None,'','First line\nВторая строка\n'+'x'*400])
def test_description_discovery_plan_apply_replan(provider,value,fake_netbox):
    if provider=='esxi':
        config=_config(); service=fake_esxi_service()
        if value is not None: service.host.vm[0].config.annotation=value
        hosts=discover_esxi(service,config)
        execute=lambda:execute_esxi_runtime(fake_netbox,hosts,config,confirmed=True)
    else:
        config=sample_source_config(); responses=proxmox_responses()
        key=next(key for key in responses if key[-3:]==('qemu',100,'config'))
        if value is not None: responses[key]['description']=value
        hosts=discover_hosts(FakeProxmox(responses),config)
        execute=lambda:apply_full_sync(fake_netbox,hosts,config.target,confirmed=True)
    from tests.test_first_sync import target
    target(fake_netbox,config)
    from tests.fakes.netbox_http import netbox_http
    with netbox_http(fake_netbox) as (fake_netbox,rows,writes):
        vm=hosts[0].virtual_machines[0]
        assert vm.description==value
        plan=build_runtime_plan(fake_netbox,hosts,config)
        rows=[dict(row.after) for row in plan.items if row.object_kind=='virtualization.virtual_machines' and row.action.value=='CREATE' and row.name==vm.original_name]
        assert rows
        assert rows[0].get('comments')==value
        if value is None: assert 'comments' not in rows[0]
        execute()
        read=lambda:next(row for row in fake_netbox.virtualization.virtual_machines.all() if row.name==vm.original_name)
        stored=read()
        assert stored.serialize().get('comments')==(value if value is not None else '')
        assert not [row for row in build_runtime_plan(fake_netbox,hosts,config).items if row.action.value in ('CREATE','UPDATE')]
        vm.description='Changed\nFull text'
        assert any(dict(row.after).get('comments')==vm.description for row in build_runtime_plan(fake_netbox,hosts,config).items)
        execute(); assert read().comments==vm.description
        vm.description=None
        assert not any('comments' in dict(row.after) for row in build_runtime_plan(fake_netbox,hosts,config).items if row.action.value=='UPDATE')
        execute(); assert read().comments=='Changed\nFull text'
        vm.description='';execute();assert read().comments==''
