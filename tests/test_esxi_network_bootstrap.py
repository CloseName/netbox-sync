"""Controlled ESXi network bootstrap and target compatibility tests."""

from copy import deepcopy
from dataclasses import replace

import pytest

from netbox_sync.esxi_discovery import discover_hosts
from netbox_sync.esxi_migration import (
    ObjectMigrationClassification,
    build_esxi_migration_plan,
)
from netbox_sync.esxi_network_bootstrap import (
    EsxiNetworkBootstrapError,
    apply_esxi_managed_vm_network_bootstrap,
)
from netbox_sync.netbox_vm_interface_metadata import build_nic_custom_fields
from netbox_sync.netbox_vm_metadata import build_vm_custom_fields
from netbox_sync.netbox_vm_network_apply import (
    VMNetworkApplyError,
    apply_vm_networks,
)
from netbox_sync.source_config import SecretReference, SourceCredentials

from tests.fakes import FakeRecord
from tests.fakes.esxi import fake_esxi_service
from tests.netbox_scenarios import add_target
from tests.sample_data import sample_source_config


def _config():
    password = SecretReference(provider='env', key='ESXI_TEST_PASSWORD')
    return replace(
        sample_source_config(),
        id='esxi-infra-test',
        source_instance='esxi-infra-test',
        source_type='esxi',
        legacy_identity_owner=False,
        credentials=SourceCredentials.for_password('root', password),
    )


def _inventory(count=1):
    hosts = discover_hosts(fake_esxi_service(vm_name='APP-1'), _config())
    first = hosts[0].virtual_machines[0]
    first.interfaces[0].ip_addresses = ['192.0.2.51/24']
    if count > 1:
        second = deepcopy(first)
        second.external_id = '503c5ad7-aaaa-bbbb-cccc-0123456789ab'
        second.vmid = second.external_id
        second.source_id = f'esxi:{second.external_id}'
        second.original_name = 'APP-2'
        second.normalized_name = second.original_name
        second.interfaces[0].mac_address = '00:50:56:AA:BB:CD'
        second.interfaces[0].ip_addresses = ['192.0.2.52/24']
        hosts[0].virtual_machines.append(second)
    return hosts


def _add_vm(fake_netbox, cluster, discovered, record_id, *, managed=True):
    custom_fields = build_vm_custom_fields(discovered) if managed else {}
    return fake_netbox.virtualization.virtual_machines.add(FakeRecord(
        id=record_id,
        name=discovered.original_name,
        cluster=cluster,
        custom_fields=custom_fields,
        comments='operator note',
    ))


def _managed_setup(fake_netbox, *, count=1):
    _, _, cluster, legacy_target = add_target(fake_netbox)
    hosts = _inventory(count)
    records = [
        _add_vm(fake_netbox, cluster, vm, 10 + index)
        for index, vm in enumerate(hosts[0].virtual_machines)
    ]
    plan = build_esxi_migration_plan(fake_netbox, hosts, _config())
    return cluster, legacy_target, hosts, records, plan


def _network_records(fake_netbox, vm, discovered, interface_id=20):
    nic = discovered.interfaces[0]
    fields = build_nic_custom_fields(vm=discovered, nic=nic)
    fields['operator_key'] = 'keep'
    interface = fake_netbox.virtualization.interfaces.add(FakeRecord(
        id=interface_id,
        name=nic.name,
        virtual_machine=vm,
        enabled=True,
        custom_fields=fields,
        description='manual description',
    ))
    mac = fake_netbox.dcim.mac_addresses.add(FakeRecord(
        id=1000 + interface_id,
        mac_address=nic.mac_address,
        assigned_object_type='virtualization.vminterface',
        assigned_object_id=interface.id,
    ))
    interface.primary_mac_address = mac
    ip = fake_netbox.ipam.ip_addresses.add(FakeRecord(
        id=2000 + interface_id,
        address=nic.ip_addresses[0],
        assigned_object_type='virtualization.vminterface',
        assigned_object_id=interface.id,
    ))
    vm.primary_ip4 = ip
    return interface, mac, ip


def _manual_primary(
        fake_netbox,
        vm,
        *,
        interface_id=146,
        ip_id=192,
        address='10.10.3.2/24',
):
    interface = fake_netbox.virtualization.interfaces.add(FakeRecord(
        id=interface_id,
        name='secondary-10-10-3-2',
        virtual_machine=vm,
        enabled=True,
        custom_fields={'operator_owned': True},
    ))
    ip = fake_netbox.ipam.ip_addresses.add(FakeRecord(
        id=ip_id,
        address=address,
        assigned_object_type='virtualization.vminterface',
        assigned_object_id=interface.id,
    ))
    vm.primary_ip4 = ip
    return interface, ip


def _apply(fake_netbox, hosts, plan):
    return apply_esxi_managed_vm_network_bootstrap(
        fake_netbox, hosts, _config(), plan, confirmed=True,
    )


def test_source_config_creates_network_and_second_run_is_idempotent(fake_netbox):
    _, _, hosts, records, plan = _managed_setup(fake_netbox)

    _apply(fake_netbox, hosts, plan)

    interface = fake_netbox.virtualization.interfaces.all()[0]
    mac = fake_netbox.dcim.mac_addresses.all()[0]
    ip = fake_netbox.ipam.ip_addresses.all()[0]
    assert interface.virtual_machine == records[0].id
    assert interface.name == 'VM Network'
    assert interface.custom_fields['sync_identities'][0]['kind'] == 'vm-nic'
    assert mac.assigned_object_id == interface.id
    assert interface.primary_mac_address == mac.id
    assert ip.assigned_object_id == interface.id
    assert records[0].primary_ip4 == ip.id

    fake_netbox.clear_mutations()
    fresh = build_esxi_migration_plan(fake_netbox, hosts, _config())
    _apply(fake_netbox, hosts, fresh)
    assert fake_netbox.mutations == []


def test_legacy_flat_target_config_remains_supported(fake_netbox):
    _, legacy_target, hosts, _, _ = _managed_setup(fake_netbox)

    apply_vm_networks(
        fake_netbox, hosts, legacy_target, confirmed=True,
    )

    assert len(fake_netbox.virtualization.interfaces.all()) == 1


def test_review_required_vm_is_completely_excluded(fake_netbox):
    _, _, hosts, records, _ = _managed_setup(fake_netbox, count=2)
    review_vm = hosts[0].virtual_machines[1]
    records[1].custom_fields = {}
    plan = build_esxi_migration_plan(fake_netbox, hosts, _config())

    assert [item.classification for item in plan.virtual_machines] == [
        ObjectMigrationClassification.MANAGED,
        ObjectMigrationClassification.REVIEW_REQUIRED,
    ]
    _apply(fake_netbox, hosts, plan)

    interfaces = fake_netbox.virtualization.interfaces.all()
    assert len(interfaces) == 1
    assert interfaces[0].virtual_machine == records[0].id
    assert not hasattr(records[1], 'primary_ip4')
    assert review_vm.original_name == records[1].name
    assert len(fake_netbox.dcim.mac_addresses.all()) == 1
    assert len(fake_netbox.ipam.ip_addresses.all()) == 1


def test_stale_managed_classification_blocks_all_writes(fake_netbox):
    _, _, hosts, records, plan = _managed_setup(fake_netbox, count=2)
    records[1].custom_fields = {}

    with pytest.raises(EsxiNetworkBootstrapError, match='stale'):
        _apply(fake_netbox, hosts, plan)
    assert fake_netbox.mutations == []


def test_existing_interface_is_updated_in_place_and_records_reused(fake_netbox):
    _, _, hosts, records, _ = _managed_setup(fake_netbox)
    interface, mac, ip = _network_records(
        fake_netbox, records[0], hosts[0].virtual_machines[0],
    )
    interface.enabled = False
    interface.custom_fields['source_bridge'] = 'old-bridge'
    plan = build_esxi_migration_plan(fake_netbox, hosts, _config())

    _apply(fake_netbox, hosts, plan)

    assert interface.id == 20
    assert interface.enabled is True
    assert interface.custom_fields['source_bridge'] == 'VM Network'
    assert interface.custom_fields['operator_key'] == 'keep'
    assert interface.description == 'manual description'
    assert mac.id == 1020
    assert ip.id == 2020
    assert len(fake_netbox.virtualization.interfaces.all()) == 1


@pytest.mark.parametrize(
    ('kind', 'address', 'message'),
    (
        ('mac', '00:50:56:AA:BB:CC', 'MAC .* already assigned'),
        ('ip', '192.0.2.51/24', 'IP .* already assigned'),
    ),
)
def test_foreign_network_ownership_blocks_before_write(
        fake_netbox,
        kind,
        address,
        message,
):
    _, _, hosts, _, plan = _managed_setup(fake_netbox)
    endpoint = (
        fake_netbox.dcim.mac_addresses
        if kind == 'mac'
        else fake_netbox.ipam.ip_addresses
    )
    field = 'mac_address' if kind == 'mac' else 'address'
    endpoint.add(FakeRecord(
        id=30,
        **{field: address},
        assigned_object_type='dcim.interface',
        assigned_object_id=999,
    ))

    with pytest.raises(VMNetworkApplyError, match=message):
        _apply(fake_netbox, hosts, plan)
    assert fake_netbox.mutations == []


@pytest.mark.parametrize('duplicate_kind', ['mac', 'ip'])
def test_duplicate_discovered_network_value_blocks_before_write(
        fake_netbox,
        duplicate_kind,
):
    _, _, hosts, _, plan = _managed_setup(fake_netbox, count=2)
    first, second = hosts[0].virtual_machines
    if duplicate_kind == 'mac':
        second.interfaces[0].mac_address = first.interfaces[0].mac_address
        message = 'Duplicate discovered MACs'
    else:
        second.interfaces[0].ip_addresses = first.interfaces[0].ip_addresses
        message = 'Duplicate discovered IPs'

    with pytest.raises(VMNetworkApplyError, match=message):
        _apply(fake_netbox, hosts, plan)
    assert fake_netbox.mutations == []


def test_unique_ipv4_is_set_but_multiple_ipv4_values_are_not(fake_netbox):
    _, _, hosts, records, plan = _managed_setup(fake_netbox, count=2)
    hosts[0].virtual_machines[1].interfaces[0].ip_addresses.append(
        '192.0.2.62/24'
    )

    _apply(fake_netbox, hosts, plan)

    assert hasattr(records[0], 'primary_ip4')
    assert not hasattr(records[1], 'primary_ip4')


def test_incompatible_manual_primary_ipv4_blocks_before_write(fake_netbox):
    _, _, hosts, records, plan = _managed_setup(fake_netbox)
    manual = fake_netbox.ipam.ip_addresses.add(FakeRecord(
        id=99,
        address='198.51.100.99/24',
        assigned_object_type=None,
        assigned_object_id=None,
    ))
    records[0].primary_ip4 = manual

    with pytest.raises(VMNetworkApplyError, match='primary IPv4 conflicts'):
        _apply(fake_netbox, hosts, plan)
    assert fake_netbox.mutations == []


def test_same_vm_manual_primary_is_preserved_while_bootstrap_continues(
        fake_netbox,
        capsys,
):
    _, _, hosts, records, _ = _managed_setup(fake_netbox, count=2)
    gate = records[0]
    discovered_gate = hosts[0].virtual_machines[0]
    managed_interface, managed_mac, managed_ip = _network_records(
        fake_netbox, gate, discovered_gate, interface_id=147,
    )
    managed_ip.id = 193
    legacy_interface, legacy_ip = _manual_primary(fake_netbox, gate)
    plan = build_esxi_migration_plan(fake_netbox, hosts, _config())

    _apply(fake_netbox, hosts, plan)

    output = capsys.readouterr().out
    assert 'PRIMARY IPv4 PRESERVE' in output
    assert 'reason=same-vm-existing-primary' in output
    assert 'primary_preserve_manual=1' in output
    assert gate.primary_ip4.id == 192
    assert legacy_interface.id == 146
    assert legacy_ip.id == 192
    assert legacy_ip.assigned_object_id == legacy_interface.id
    assert managed_interface.id == 147
    assert managed_ip.id == 193
    assert managed_ip.assigned_object_id == managed_interface.id
    assert managed_mac.assigned_object_id == managed_interface.id
    assert len(fake_netbox.virtualization.interfaces.all()) == 3

    fake_netbox.clear_mutations()
    fresh = build_esxi_migration_plan(fake_netbox, hosts, _config())
    _apply(fake_netbox, hosts, fresh)
    assert fake_netbox.mutations == []


def test_primary_owned_by_interface_on_foreign_vm_blocks(fake_netbox):
    cluster, _, hosts, records, plan = _managed_setup(fake_netbox)
    foreign_vm = fake_netbox.virtualization.virtual_machines.add(FakeRecord(
        id=99, name='FOREIGN', cluster=cluster, custom_fields={},
    ))
    _, foreign_ip = _manual_primary(fake_netbox, foreign_vm)
    records[0].primary_ip4 = foreign_ip

    with pytest.raises(VMNetworkApplyError, match='primary IPv4 conflicts'):
        _apply(fake_netbox, hosts, plan)
    assert fake_netbox.mutations == []


@pytest.mark.parametrize(
    ('assigned_type', 'assigned_id'),
    (
        (None, None),
        ('dcim.interface', 146),
        ('virtualization.vminterface', 999),
    ),
)
def test_unverifiable_primary_ownership_blocks(
        fake_netbox,
        assigned_type,
        assigned_id,
):
    _, _, hosts, records, plan = _managed_setup(fake_netbox)
    primary = fake_netbox.ipam.ip_addresses.add(FakeRecord(
        id=192,
        address='10.10.3.2/24',
        assigned_object_type=assigned_type,
        assigned_object_id=assigned_id,
    ))
    records[0].primary_ip4 = primary

    with pytest.raises(VMNetworkApplyError, match='primary IPv4 conflicts'):
        _apply(fake_netbox, hosts, plan)
    assert fake_netbox.mutations == []


def test_late_network_conflict_blocks_every_context_before_write(fake_netbox):
    _, _, hosts, _, plan = _managed_setup(fake_netbox, count=2)
    fake_netbox.ipam.ip_addresses.add(FakeRecord(
        id=99,
        address='192.0.2.52/24',
        assigned_object_type='dcim.interface',
        assigned_object_id=999,
    ))

    with pytest.raises(VMNetworkApplyError, match='already assigned'):
        _apply(fake_netbox, hosts, plan)
    assert fake_netbox.mutations == []


def test_unconfirmed_bootstrap_writes_nothing(fake_netbox):
    _, _, hosts, _, plan = _managed_setup(fake_netbox)

    with pytest.raises(EsxiNetworkBootstrapError, match='confirmation'):
        apply_esxi_managed_vm_network_bootstrap(
            fake_netbox, hosts, _config(), plan,
        )
    assert fake_netbox.mutations == []


@pytest.mark.parametrize('reuse', [False, True])
def test_managed_nic_mac_change_preserves_old_record_and_is_idempotent(fake_netbox, reuse):
    _, _, hosts, records, _ = _managed_setup(fake_netbox)
    vm = hosts[0].virtual_machines[0]
    interface, old_mac, _ = _network_records(fake_netbox, records[0], vm)
    old_value = old_mac.mac_address
    vm.interfaces[0].mac_address = '00:50:56:AA:CC:DD'
    if reuse:
        fake_netbox.dcim.mac_addresses.add(FakeRecord(id=9000,
            mac_address=vm.interfaces[0].mac_address,
            assigned_object_type=None, assigned_object_id=None))
    apply_vm_networks(fake_netbox, hosts, _config(), confirmed=True)
    assert interface.primary_mac_address != old_mac.id
    assert old_mac.mac_address == old_value
    assert old_mac.assigned_object_id == interface.id
    assert len(fake_netbox.dcim.mac_addresses.all()) == 2
    fake_netbox.clear_mutations()
    apply_vm_networks(fake_netbox, hosts, _config(), confirmed=True)
    assert fake_netbox.mutations == []


def test_changed_mac_cannot_take_another_interfaces_assignment(fake_netbox):
    _, _, hosts, records, _ = _managed_setup(fake_netbox)
    vm = hosts[0].virtual_machines[0]
    interface, old_mac, _ = _network_records(fake_netbox, records[0], vm)
    vm.interfaces[0].mac_address = '00:50:56:AA:CC:DD'
    fake_netbox.dcim.mac_addresses.add(FakeRecord(id=9000,
        mac_address=vm.interfaces[0].mac_address,
        assigned_object_type='virtualization.vminterface', assigned_object_id=999))
    fake_netbox.clear_mutations()
    with pytest.raises(VMNetworkApplyError, match='already assigned'):
        apply_vm_networks(fake_netbox, hosts, _config(), confirmed=True)
    assert fake_netbox.mutations == []
    assert interface.primary_mac_address == old_mac
