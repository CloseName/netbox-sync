"""Characterize disk validation before separating planning from writes."""

from copy import deepcopy

import pytest

from netbox_sync.source_identity import virtual_machine_source_identity
from netbox_sync.virtual_disks import apply_virtual_disks
from tests.test_esxi_network_bootstrap import _managed_setup


@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("problem", ["negative", "duplicate", "missing", "parent"])
def test_late_invalid_disk_prevents_all_writes(fake_netbox, confirmed, problem):
    _, config, hosts, records, _ = _managed_setup(fake_netbox, count=2)
    vm = hosts[0].virtual_machines[1]
    disk = vm.disks[0]
    if problem == "negative":
        disk.size_bytes = -1
        message = "Disk capacity cannot be negative"
    elif problem == "duplicate":
        vm.disks.append(deepcopy(disk))
        message = "Missing or duplicate provider disk identity"
    elif problem == "missing":
        disk.external_id = None
        disk.name = ""
        message = "Missing or duplicate provider disk identity"
    else:
        records[1].custom_fields = {}
        message = "Disk parent VM identity is not unique"
    fake_netbox.clear_mutations()
    with pytest.raises(ValueError, match=f"^{message}$"):
        apply_virtual_disks(fake_netbox, hosts, config, confirmed=confirmed)
    assert fake_netbox.mutations == []


@pytest.mark.parametrize("problem", ["duplicate", "owner", "name"])
def test_existing_disk_conflicts_precede_negative_capacity(fake_netbox, problem):
    _, config, hosts, records, _ = _managed_setup(fake_netbox)
    vm = hosts[0].virtual_machines[0]
    disk = vm.disks[0]
    identity = virtual_machine_source_identity(vm).to_record()
    wanted = {**identity, "kind": "vm-disk",
              "external_id": identity["external_id"] + ":" + str(disk.external_id or disk.name)}
    fields = {"name": disk.name, "virtual_machine": records[0].id, "size": 1,
              "custom_fields": {"sync_disk_identity": wanted}}
    if problem == "duplicate":
        fake_netbox.virtualization.virtual_disks.add(id=100, **fields)
        fake_netbox.virtualization.virtual_disks.add(id=101, **fields)
        message = "Duplicate NetBox disk identity"
    elif problem == "owner":
        fields["virtual_machine"] = 999
        fake_netbox.virtualization.virtual_disks.add(id=100, **fields)
        message = "Disk identity belongs to another VM"
    else:
        fields["custom_fields"] = {}
        fake_netbox.virtualization.virtual_disks.add(id=100, **fields)
        message = "Disk name is already used by an unmanaged or different disk"
    disk.size_bytes = -1
    fake_netbox.clear_mutations()
    with pytest.raises(ValueError, match=f"^{message}$"):
        apply_virtual_disks(fake_netbox, hosts, config, confirmed=True)
    assert fake_netbox.mutations == []


@pytest.mark.parametrize("size,expected", [(0, 0), (1, 1), (1000000, 1), (1000001, 2)])
def test_dry_run_and_decimal_megabyte_rounding(fake_netbox, size, expected):
    _, config, hosts, _, _ = _managed_setup(fake_netbox)
    hosts[0].virtual_machines[0].disks[0].size_bytes = size
    fake_netbox.clear_mutations()
    assert apply_virtual_disks(fake_netbox, hosts, config) is None
    assert fake_netbox.mutations == []
    apply_virtual_disks(fake_netbox, hosts, config, confirmed=True)
    row = fake_netbox.virtualization.virtual_disks.all()[0]
    assert row.size == expected
    row.custom_fields["operator_note"] = "preserve"
    hosts[0].virtual_machines[0].disks[0].size_bytes += 1000000
    apply_virtual_disks(fake_netbox, hosts, config, confirmed=True)
    assert row.custom_fields["operator_note"] == "preserve"
    assert row.size == expected + 1
