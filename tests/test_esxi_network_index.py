"""Bounded network correlation work and ownership isolation for adoption."""

from collections import Counter
from types import SimpleNamespace
from dataclasses import replace

from netbox_sync.esxi_adoption import _NetworkIndex
from tests.fakes import FakeRecord


def test_adoption_reuses_candidate_networks_without_changing_ambiguity(fake_netbox, monkeypatch):
    from netbox_sync.esxi_adoption import build_esxi_adoption_plan, AdoptionClassification
    from tests.test_esxi_adoption import _config, _inventory, _target, _add_vm

    _, cluster = _target(fake_netbox)
    host = _inventory()[0]
    vms = tuple(replace(host.virtual_machines[0], external_id=f"vm-{i}", original_name=f"VM-{i}") for i in range(24))
    for i in range(24):
        _add_vm(fake_netbox, cluster, record_id=i + 1, name=f"VM-{i}", ip_address="192.0.2.50/24")
        fake_netbox.virtualization.interfaces.add(FakeRecord(id=i + 1, virtual_machine=i + 1))
    calls = Counter()
    original = FakeRecord.serialize

    def counted(record):
        if hasattr(record, "virtual_machine"):
            calls[id(record)] += 1
        return original(record)

    monkeypatch.setattr(FakeRecord, "serialize", counted)
    plan = build_esxi_adoption_plan(fake_netbox, [replace(host, virtual_machines=vms)], _config())
    items = [item for item in plan.items if item.object_kind == "vm"]
    assert len(items) == 24
    assert all(item.classification == AdoptionClassification.AMBIGUOUS for item in items)
    assert all(len(item.candidates) == 24 for item in items)
    assert max(calls.values()) == 1


def test_large_review_serializes_network_rows_once(fake_netbox, monkeypatch):
    count = 256
    records = []
    for number in range(1, count + 1):
        records.append(FakeRecord(id=number))
        fake_netbox.virtualization.interfaces.add(
            FakeRecord(id=number, virtual_machine=number, primary_mac_address=None)
        )
        fake_netbox.ipam.ip_addresses.add(
            FakeRecord(
                id=number,
                address=f"10.0.{number // 256}.{number % 256}/24",
                assigned_object_type="virtualization.vminterface",
                assigned_object_id=number,
            )
        )
    calls = Counter()
    original = FakeRecord.serialize

    def counted(record):
        calls[id(record)] += 1
        return original(record)

    monkeypatch.setattr(FakeRecord, "serialize", counted)
    index = _NetworkIndex(fake_netbox)
    for _ in range(3):
        for record in records:
            ips, macs = index.for_object("vm", record)
            assert ips == {f"10.0.{record.id // 256}.{record.id % 256}"}
            assert not macs
    assert max(calls.values()) <= 1


def test_network_index_keeps_types_and_primary_addresses_separate(fake_netbox):
    fake_netbox.dcim.interfaces.add(FakeRecord(id=7, device=1, primary_mac_address=9))
    fake_netbox.virtualization.interfaces.add(FakeRecord(id=7, virtual_machine=1))
    fake_netbox.dcim.mac_addresses.add(
        FakeRecord(
            id=9,
            mac_address="00-11-22-33-44-55",
            assigned_object_type="dcim.interface",
            assigned_object_id=7,
        )
    )
    fake_netbox.ipam.ip_addresses.add(
        FakeRecord(
            id=8,
            address="192.0.2.8/24",
            assigned_object_type="virtualization.vminterface",
            assigned_object_id=7,
        )
    )
    fake_netbox.ipam.ip_addresses.add(
        FakeRecord(
            id=10,
            address="127.0.0.1/8",
            assigned_object_type="virtualization.vminterface",
            assigned_object_id=7,
        )
    )
    index = _NetworkIndex(fake_netbox)
    host = SimpleNamespace(id=1, primary_ip4={"address": "192.0.2.1/24"})
    vm = SimpleNamespace(id=1)
    assert index.for_object("host", host) == ({"192.0.2.1"}, {"00:11:22:33:44:55"})
    assert index.for_object("vm", vm) == ({"192.0.2.8"}, set())
    fake_netbox.ipam.ip_addresses.add(
        FakeRecord(
            id=11,
            address="192.0.2.11/24",
            assigned_object_type="virtualization.vminterface",
            assigned_object_id=7,
        )
    )
    assert index.for_object("vm", vm)[0] == {"192.0.2.8"}
    assert _NetworkIndex(fake_netbox).for_object("vm", vm)[0] == {"192.0.2.8", "192.0.2.11"}
