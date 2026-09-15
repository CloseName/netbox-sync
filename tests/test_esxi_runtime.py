"""Normal migration-aware ESXi runtime tests."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

import netbox_sync
from netbox_sync.esxi_discovery import discover_hosts
from netbox_sync.esxi_migration import ObjectMigrationClassification
from netbox_sync.esxi_runtime import execute_esxi_runtime
from netbox_sync.netbox_metadata import build_device_custom_fields
from netbox_sync.netbox_vm_metadata import build_vm_custom_fields
from netbox_sync.netbox_vm_network_apply import VMNetworkApplyError
from netbox_sync.source_config import SecretReference, SourceCredentials

from tests.fakes import FakeRecord
from tests.fakes.esxi import fake_esxi_service
from tests.netbox_scenarios import add_target
from tests.sample_data import sample_source_config


def _config():
    password = SecretReference(
        provider='file', key='esxi_infra_sync_password',
    )
    return replace(
        sample_source_config(),
        id='esxi-infra-test',
        source_instance='esxi-infra-test',
        source_type='esxi',
        legacy_identity_owner=False,
        credentials=SourceCredentials.for_password('netbox-sync', password),
    )


def _inventory(count=2):
    hosts = discover_hosts(fake_esxi_service(vm_name='MANAGED'), _config())
    hosts[0].virtual_machines[0].interfaces[0].ip_addresses = ['192.0.2.51/24']
    if count == 2:
        review = deepcopy(hosts[0].virtual_machines[0])
        review.external_id = '503c5ad7-aaaa-bbbb-cccc-0123456789ab'
        review.vmid = review.external_id
        review.source_id = f'esxi:{review.external_id}'
        review.original_name = 'REVIEW'
        review.normalized_name = 'REVIEW'
        review.interfaces[0].mac_address = '00:50:56:AA:BB:CD'
        review.interfaces[0].ip_addresses = []
        hosts[0].virtual_machines.append(review)
    return hosts


def _setup(fake_netbox, *, review=True):
    site, _, cluster, _ = add_target(fake_netbox)
    hosts = _inventory(2 if review else 1)
    host = hosts[0]
    fake_netbox.dcim.devices.add(FakeRecord(
        id=5,
        name=host.original_name,
        site=site,
        cluster=cluster,
        custom_fields=build_device_custom_fields(host),
    ))
    managed = host.virtual_machines[0]
    managed_record = fake_netbox.virtualization.virtual_machines.add(FakeRecord(
        id=10,
        name=managed.original_name,
        cluster=cluster,
        status='offline',
        vcpus=1,
        memory=1,
        disk=1,
        start_on_boot='off',
        custom_fields={
            **build_vm_custom_fields(managed),
            'operator_note': 'keep',
        },
    ))
    review_record = None
    if review:
        review_record = fake_netbox.virtualization.virtual_machines.add(
            FakeRecord(
                id=11,
                name='review',
                cluster=cluster,
                comments='legacy review object',
                custom_fields={'operator_note': 'untouched'},
            )
        )
    return hosts, managed_record, review_record


def _manual_primary(fake_netbox, vm, address='198.51.100.10/24'):
    interface = fake_netbox.virtualization.interfaces.add(FakeRecord(
        id=146,
        name='manual-primary',
        virtual_machine=vm,
        enabled=True,
        custom_fields={'operator_owned': True},
    ))
    ip = fake_netbox.ipam.ip_addresses.add(FakeRecord(
        id=192,
        address=address,
        assigned_object_type='virtualization.vminterface',
        assigned_object_id=interface.id,
    ))
    vm.primary_ip4 = ip
    return interface, ip


def test_runtime_preflight_matches_host_and_writes_nothing(fake_netbox, capsys):
    hosts, _, _ = _setup(fake_netbox)

    plan = execute_esxi_runtime(fake_netbox, hosts, _config())

    output = capsys.readouterr().out
    assert plan.hosts[0].classification == ObjectMigrationClassification.MANAGED
    assert 'HOST MANAGED' in output
    assert 'host_networking=UNSUPPORTED_REPORT_ONLY' in output
    assert 'VM REVIEW_REQUIRED' in output
    assert fake_netbox.mutations == []


def test_runtime_reconciles_managed_vm_and_nic_but_not_review(fake_netbox):
    hosts, managed, review = _setup(fake_netbox)
    review_before = review.serialize()

    execute_esxi_runtime(fake_netbox, hosts, _config(), confirmed=True)

    assert managed.status == 'active'
    assert managed.vcpus == 4
    assert managed.custom_fields['operator_note'] == 'keep'
    interfaces = fake_netbox.virtualization.interfaces.all()
    assert len(interfaces) == 1
    assert interfaces[0].virtual_machine == managed.id
    assert interfaces[0].custom_fields['sync_identities'][0]['kind'] == 'vm-nic'
    assert fake_netbox.dcim.interfaces.all() == []
    assert review.serialize() == review_before

    fake_netbox.clear_mutations()
    execute_esxi_runtime(fake_netbox, hosts, _config(), confirmed=True)
    assert fake_netbox.mutations == []


def test_runtime_creates_truly_new_vm_without_adopting_legacy(fake_netbox):
    hosts, _, review = _setup(fake_netbox)
    fake_netbox.virtualization.virtual_machines.records.remove(review)

    plan = execute_esxi_runtime(fake_netbox, hosts, _config(), confirmed=True)

    classifications = {
        item.discovered_name: item.classification
        for item in plan.virtual_machines
    }
    assert classifications['REVIEW'] == ObjectMigrationClassification.NEW
    assert fake_netbox.virtualization.virtual_machines.get(name='REVIEW') is not None
    assert any(
        item.virtual_machine == fake_netbox.virtualization.virtual_machines.get(name='REVIEW').id
        for item in fake_netbox.virtualization.interfaces.all()
    )


def test_runtime_preserves_same_vm_manual_primary(fake_netbox):
    hosts, managed, _ = _setup(fake_netbox, review=False)
    interface, primary = _manual_primary(fake_netbox, managed)

    execute_esxi_runtime(fake_netbox, hosts, _config(), confirmed=True)

    assert managed.primary_ip4.id == primary.id == 192
    assert interface.id == 146
    managed_interface = next(
        item
        for item in fake_netbox.virtualization.interfaces.all()
        if item.id != interface.id
    )
    discovered_ip = fake_netbox.ipam.ip_addresses.get(address='192.0.2.51/24')
    assert discovered_ip.assigned_object_id == managed_interface.id


def test_runtime_foreign_primary_fails_before_any_write(fake_netbox):
    hosts, managed, _ = _setup(fake_netbox, review=False)
    foreign = fake_netbox.virtualization.virtual_machines.add(FakeRecord(
        id=99,
        name='FOREIGN',
        cluster=managed.cluster,
        custom_fields={},
    ))
    _, primary = _manual_primary(fake_netbox, foreign)
    managed.primary_ip4 = primary

    with pytest.raises(VMNetworkApplyError, match='primary IPv4 conflicts'):
        execute_esxi_runtime(fake_netbox, hosts, _config(), confirmed=True)
    assert fake_netbox.mutations == []


def test_normal_dispatch_plan_routes_esxi_to_zero_write_runtime(
        fake_netbox,
        monkeypatch,
):
    hosts, _, _ = _setup(fake_netbox)
    calls = []
    monkeypatch.setattr(netbox_sync.pynetbox, 'api', lambda **_kwargs: fake_netbox)
    monkeypatch.setattr(
        netbox_sync,
        'execute_esxi_runtime',
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    monkeypatch.setenv('NB_API_URL', 'https://netbox.invalid')
    monkeypatch.setenv('NB_API_TOKEN', 'read-token')

    netbox_sync.execute_discovered_source(_config(), hosts, 'plan')

    assert calls[0][0] == (fake_netbox, hosts, _config())
    assert calls[0][1] == {'confirmed': False}
    assert fake_netbox.mutations == []


def test_normal_source_dispatch_selects_each_adapter(monkeypatch):
    calls = []
    proxmox = sample_source_config()
    esxi = _config()
    monkeypatch.setattr(
        netbox_sync,
        'execute_proxmox_source',
        lambda config, mode: calls.append(('proxmox', config.id, mode)),
    )
    monkeypatch.setattr(
        netbox_sync,
        'execute_esxi_source',
        lambda config, mode, reconcile: calls.append(
            ('esxi', config.id, mode, reconcile)
        ),
    )

    dispatch = netbox_sync._source_dispatch('plan')
    dispatch.execute(proxmox)
    dispatch.execute(esxi)

    assert calls == [
        ('proxmox', proxmox.id, 'plan'),
        ('esxi', esxi.id, 'plan', netbox_sync.execute_discovered_source),
    ]


def test_esxi_password_is_only_an_opaque_logical_reference():
    config = _config()

    assert config.credentials.password_reference == SecretReference(
        provider='file', key='esxi_infra_sync_password',
    )
    assert 'password=' not in repr(config)


def test_compose_mounts_esxi_password_at_fixed_runtime_path():
    compose = Path('compose.yml').read_text(encoding='utf-8')

    assert (
        '../secrets/esxi_infra_sync_password:'
        '/run/secrets/netbox-sync/esxi_infra_sync_password:ro'
    ) in compose
