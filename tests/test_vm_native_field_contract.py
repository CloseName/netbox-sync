"""VM native updates preserve coercion, authority and ordered rendering."""

from types import SimpleNamespace as NS
import pytest
from netbox_sync import netbox_vm_apply as apply
from netbox_sync import netbox_vm_planner as planner
from netbox_sync.proxmox_discovery import discover_hosts
from tests.fakes import FakeProxmox
from tests.sample_data import proxmox_responses, sample_source_config


def guest():
    return discover_hosts(FakeProxmox(proxmox_responses()), sample_source_config())[0].virtual_machines[0]


@pytest.mark.parametrize("protected", [False, True])
def test_changes_keep_order_coercion_and_authority(protected):
    vm = guest()
    vm.description = "First\nSecond"
    cf = {"selectel_refs": [1], "selectel_inventory": {"native_fields": ["name", "vcpus"]}} if protected else {}
    data = dict(
        name="old",
        cluster={"id": -1},
        status={"value": "other"},
        vcpus="99.0",
        memory="99.0",
        disk="99.0",
        start_on_boot={"value": "other"},
        custom_fields=cf,
    )
    result = apply._vm_changes(NS(serialize=lambda: data), vm, NS(id=123), {"manual": "keep"}, ["field"])
    expected = dict(
        description="First Second",
        comments="First\nSecond",
        name=apply.netbox_vm_name(vm),
        cluster=123,
        status=apply._desired_status(vm),
        vcpus=int(vm.vcpus),
        memory=apply._desired_memory(vm),
        disk=apply._desired_disk(vm),
        start_on_boot=apply._desired_start_on_boot(vm),
        custom_fields={"manual": "keep"},
    )
    if protected:
        del expected["name"]
        del expected["vcpus"]
    assert list(result.items()) == list(expected.items())


def test_vm_report_metadata_failure_follows_resource_output(monkeypatch, capsys):
    vm = guest()

    def fail(*args):
        raise ValueError("metadata failed")

    monkeypatch.setattr(planner, "build_vm_custom_fields", fail)
    with pytest.raises(ValueError, match="metadata failed"):
        planner._print_desired_vm(vm, NS(name="target"))
    output = capsys.readouterr().out
    assert output.startswith("      cluster=target\n")
    assert "      disks=" in output
    assert "managed_custom_fields:" not in output


def test_vm_report_custom_fields_keep_order_unicode_and_json(monkeypatch, capsys):
    vm = guest()
    monkeypatch.setattr(planner, "MANAGED_VM_CUSTOM_FIELDS", ["keep", "change"])
    monkeypatch.setattr(
        planner, "build_vm_custom_fields", lambda *args: {"keep": "same", "change": {"z": 1, "a": "текст"}}
    )
    planner._print_desired_vm(vm, NS(name="target"), NS(custom_fields={"keep": "same", "change": None}))
    assert capsys.readouterr().out.endswith(
        '      managed_custom_fields:\n        KEEP keep="same"\n        SET change={"a": "текст", "z": 1}\n'
    )
