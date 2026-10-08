from tests.test_esxi_network_bootstrap import _managed_setup
from tests.fakes import FakeRecord
from netbox_sync.virtual_disks import apply_virtual_disks
import pytest


@pytest.mark.parametrize('byte_size,kib,expected', [(2049, 2, 2049), (None, 2, 2048), (0, 2, 2048), (0, 0, 0), (-1, None, 0)])
def test_esxi_capacity_uses_bytes_then_legacy_kib(byte_size, kib, expected):
    from types import SimpleNamespace
    from netbox_sync.esxi_discovery import _disk_size_bytes
    assert _disk_size_bytes(SimpleNamespace(capacityInBytes=byte_size,capacityInKB=kib)) == expected


def test_zero_disk_capacity_syncs_alongside_other_changes_and_recovers(fake_netbox):
    _,config,hosts,_,_=_managed_setup(fake_netbox, count=2)
    apply_virtual_disks(fake_netbox,hosts,config,confirmed=True)
    disks=fake_netbox.virtualization.virtual_disks.all()
    first=hosts[0].virtual_machines[0].disks[0]
    second=hosts[0].virtual_machines[1].disks[0]
    first.size_bytes += 1000000
    second.size_bytes=0
    apply_virtual_disks(fake_netbox,hosts,config,confirmed=True)
    assert disks[0].size==(first.size_bytes+999999)//1000000
    assert disks[1].size==0
    fake_netbox.clear_mutations()
    apply_virtual_disks(fake_netbox,hosts,config,confirmed=True)
    assert fake_netbox.mutations==[]
    second.size_bytes=40*1024**3
    apply_virtual_disks(fake_netbox,hosts,config,confirmed=True)
    assert disks[1].size==(second.size_bytes+999999)//1000000


def test_zero_size_is_an_applicable_plan_without_real_writes(fake_netbox):
    from tests.test_esxi_host_network import target
    from tests.test_esxi_network_bootstrap import _config
    from tests.fakes.esxi import fake_esxi_service
    from netbox_sync.esxi_discovery import discover_hosts
    from netbox_sync.application.runtime_plan import build_runtime_plan
    config=target(fake_netbox,_config())
    hosts=discover_hosts(fake_esxi_service(),config)
    vm=hosts[0].virtual_machines[0]
    vm.disks[0].size_bytes=0
    plan=build_runtime_plan(fake_netbox,hosts,config)
    assert plan.apply_allowed
    assert not any(r.reason_code=='DISK_SIZE_UNKNOWN' for r in plan.items)
    row=next(r for r in plan.items if r.object_kind=='virtualization.virtual_disks')
    assert dict(row.after)['size']==0
    assert fake_netbox.mutations==[]
    from netbox_sync.esxi_runtime import execute_esxi_runtime
    execute_esxi_runtime(fake_netbox,hosts,config,confirmed=True)
    assert fake_netbox.virtualization.virtual_disks.all()[0].size==0



def test_disk_create_resize_rename_and_second_run(fake_netbox):
    _, config, hosts, records, _ = _managed_setup(fake_netbox)
    disk=hosts[0].virtual_machines[0].disks[0]
    disk.external_id='2000'
    apply_virtual_disks(fake_netbox,hosts,config,confirmed=True)
    row=fake_netbox.virtualization.virtual_disks.all()[0]
    assert row.virtual_machine==records[0].id
    disk.name='Renamed disk';disk.size_bytes+=1000000
    apply_virtual_disks(fake_netbox,hosts,config,confirmed=True)
    assert len(fake_netbox.virtualization.virtual_disks.all())==1
    assert row.name=='Renamed disk'
    assert row.size==(disk.size_bytes+999999)//1000000
    fake_netbox.clear_mutations()
    apply_virtual_disks(fake_netbox,hosts,config,confirmed=True)
    assert fake_netbox.mutations==[]


def test_disk_name_does_not_adopt_manual_disk(fake_netbox):
    _,config,hosts,records,_=_managed_setup(fake_netbox)
    disk=hosts[0].virtual_machines[0].disks[0]
    fake_netbox.virtualization.virtual_disks.add(FakeRecord(id=99,name=disk.name,virtual_machine=records[0].id,size=10))
    fake_netbox.clear_mutations()
    with pytest.raises(ValueError,match='unmanaged'):
        apply_virtual_disks(fake_netbox,hosts,config,confirmed=True)
    assert fake_netbox.mutations==[]


def test_missing_disks_are_retained(fake_netbox):
    _,config,hosts,_,_=_managed_setup(fake_netbox)
    apply_virtual_disks(fake_netbox,hosts,config,confirmed=True)
    count=len(fake_netbox.virtualization.virtual_disks.all())
    hosts[0].virtual_machines[0].disks=[]
    fake_netbox.clear_mutations()
    apply_virtual_disks(fake_netbox,hosts,config,confirmed=True)
    assert len(fake_netbox.virtualization.virtual_disks.all())==count
    assert fake_netbox.mutations==[]


def test_esxi_collector_accepts_byte_only_disk_capacity():
    from tests.fakes.esxi import fake_esxi_service
    from tests.test_esxi_network_bootstrap import _config
    from netbox_sync.esxi_discovery import discover_hosts
    service=fake_esxi_service()
    disk=service.host.vm[0].config.hardware.device[0]
    del disk.capacityInKB
    disk.capacityInBytes=123456789
    hosts=discover_hosts(service,_config())
    assert hosts[0].virtual_machines[0].disks[0].size_bytes==123456789
