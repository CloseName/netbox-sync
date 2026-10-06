from tests.test_esxi_network_bootstrap import _managed_setup
from tests.fakes import FakeRecord
from netbox_sync.virtual_disks import apply_virtual_disks
import pytest


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
