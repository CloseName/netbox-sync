"""Standalone ESXi adapter, discovery, identity, and executor tests."""

from copy import deepcopy
from dataclasses import replace

import pytest

import netbox_sync.esxi_client as esxi_client
from netbox_sync.esxi_client import (
    EsxiClient,
    EsxiConnectionError,
    test_source_connection as check_source_connection,
)
from netbox_sync.esxi_discovery import discover_hosts
from netbox_sync.esxi_executor import execute_esxi_source
from netbox_sync.orchestrator import run_sources
from netbox_sync.source_config import SecretReference, SourceCredentials
from netbox_sync.source_executor import SourceExecutorDispatch
from netbox_sync.source_identity import (
    host_source_identity,
    virtual_machine_nic_source_identity,
    virtual_machine_source_identity,
)

from tests.fakes.esxi import fake_esxi_service, ns
from tests.sample_data import sample_source_config


class FakeResolver:
    """Secret resolver returning an injected ephemeral value."""

    def __init__(self, value='fake-password'):
        self.value = value
        self.references = []

    def resolve(self, reference):
        self.references.append(reference)
        return self.value


class MappingResolver:
    """Resolve distinct opaque references without exposing them in results."""

    def __init__(self, values):
        self.values = values
        self.references = []

    def resolve(self, reference):
        self.references.append(reference)
        return self.values[reference.key]


def esxi_config(source_id='esxi-a', password_key='ESXI_A_PASSWORD'):
    """Return one valid password-reference-only ESXi SourceConfig."""

    password = SecretReference(provider='env', key=password_key)
    return replace(
        sample_source_config(address=f'{source_id}.example.test'),
        id=source_id,
        source_instance=source_id,
        source_type='esxi',
        legacy_identity_owner=False,
        credentials=SourceCredentials.for_password('root', password),
    )


def test_esxi_host_vm_datastore_disk_nic_and_tools_ip_mapping():
    host = discover_hosts(fake_esxi_service(), esxi_config())[0]
    vm = host.virtual_machines[0]

    assert host.source == 'esxi'
    assert host.source_instance == 'esxi-a'
    assert host.source_id == '420f37d2-7a3b-4c1d-8e9f-001122334455'
    assert host.management_ip == '192.0.2.10'
    assert host.hypervisor == 'VMware ESXi'
    assert host.hypervisor_version == '8.0.3 build-24022510'
    assert (host.cpu.sockets, host.cpu.cores, host.cpu.logical_cpus) == (2, 16, 32)
    assert host.memory_bytes == 128 * 1024**3
    assert host.interfaces[0].name == 'vmnic0'
    assert host.disks[0].serial == 'FAKE-SERIAL'
    assert host.storages[0].name == 'datastore1'
    assert host.storages[0].used_bytes == 300 * 1024**3
    assert vm.status == 'running'
    assert vm.vcpus == 4
    assert vm.memory_bytes == 8192 * 1024**2
    assert vm.autostart is True
    assert vm.disks[0].storage == 'datastore1'
    assert vm.interfaces[0].external_id == '4000'
    assert vm.interfaces[0].vlan_id == 120
    assert vm.interfaces[0].ip_addresses == ['192.0.2.50/24']


def _esxi_67_inventory(host, vm_folder_children=()):
    compute_resource = ns(
        _moId='ha-compute-res',
        name=host.name,
        host=[host],
    )
    host_folder = ns(
        _moId='ha-folder-host',
        name='host',
        childEntity=[compute_resource],
    )
    vm_folder = ns(
        _moId='ha-folder-vm',
        name='vm',
        childEntity=list(vm_folder_children),
    )
    datacenter = ns(
        _moId='ha-datacenter',
        name='ha-datacenter',
        hostFolder=host_folder,
        vmFolder=vm_folder,
    )
    root = ns(
        _moId='ha-folder-root',
        name='root',
        childEntity=[datacenter],
    )
    return ns(RetrieveContent=lambda: ns(rootFolder=root))


def test_standalone_esxi_67_host_folder_inventory_is_discovered():
    host = fake_esxi_service().host

    discovered = discover_hosts(_esxi_67_inventory(host), esxi_config())

    assert len(discovered) == 1
    assert discovered[0].original_name == 'esxi-a.example.test'
    assert discovered[0].source_id == '420f37d2-7a3b-4c1d-8e9f-001122334455'


def test_vm_folder_objects_are_not_interpreted_as_hosts():
    host = fake_esxi_service().host
    decoy = fake_esxi_service().host
    decoy.name = 'vm-folder-decoy.example.test'
    decoy.hardware.systemInfo.uuid = 'vm-folder-decoy-uuid'

    discovered = discover_hosts(
        _esxi_67_inventory(host, vm_folder_children=[decoy]),
        esxi_config(),
    )

    assert [item.source_id for item in discovered] == [
        '420f37d2-7a3b-4c1d-8e9f-001122334455'
    ]


def test_valid_esxi_host_hardware_uuid_is_used():
    discovered = discover_hosts(fake_esxi_service(), esxi_config())[0]

    assert discovered.source_id == '420f37d2-7a3b-4c1d-8e9f-001122334455'


def test_host_rename_preserves_hardware_identity():
    before = fake_esxi_service()
    after = fake_esxi_service()
    after.host.name = 'renamed-esxi.example.test'

    first = discover_hosts(before, esxi_config())[0]
    second = discover_hosts(after, esxi_config())[0]

    assert first.original_name != second.original_name
    assert host_source_identity(first) == host_source_identity(second)


def test_host_uuid_is_canonicalized_across_case_braces_and_whitespace():
    service = fake_esxi_service()
    service.host.hardware.systemInfo.uuid = (
        ' {420F37D2-7A3B-4C1D-8E9F-001122334455} '
    )

    discovered = discover_hosts(service, esxi_config())[0]

    assert discovered.source_id == '420f37d2-7a3b-4c1d-8e9f-001122334455'


@pytest.mark.parametrize(
    'hardware_uuid',
    (
        '',
        '00000000-0000-0000-0000-000000000000',
        '00000000-0000-0000-0000-ac1f6b021cb0',
        'not-a-uuid',
    ),
)
def test_unusable_esxi_host_hardware_uuid_falls_back_to_managed_id(
        hardware_uuid,
):
    service = fake_esxi_service()
    service.host.hardware.systemInfo.uuid = hardware_uuid
    service.host._moId = 'ha-host'

    discovered = discover_hosts(service, esxi_config())[0]

    assert discovered.source_id == 'ha-host'


def test_same_managed_host_id_is_isolated_by_source_instance():
    first_service = fake_esxi_service()
    second_service = fake_esxi_service()
    for service in (first_service, second_service):
        service.host.hardware.systemInfo.uuid = (
            '00000000-0000-0000-0000-ac1f6b021cb0'
        )
        service.host._moId = 'ha-host'

    first = discover_hosts(first_service, esxi_config('esxi-a'))[0]
    second = discover_hosts(second_service, esxi_config('esxi-b'))[0]

    assert first.source_id == second.source_id == 'ha-host'
    assert host_source_identity(first) != host_source_identity(second)


def test_host_uuid_validation_does_not_change_vm_identity():
    service = fake_esxi_service()
    service.host.hardware.systemInfo.uuid = (
        '00000000-0000-0000-0000-ac1f6b021cb0'
    )
    service.host._moId = 'ha-host'

    discovered = discover_hosts(service, esxi_config())[0]

    assert discovered.virtual_machines[0].external_id == (
        '503c5ad7-0000-1111-2222-0123456789ab'
    )


@pytest.mark.parametrize(
    ('power_state', 'expected'),
    (
        ('poweredOn', 'running'),
        ('poweredOff', 'stopped'),
        ('suspended', 'paused'),
        ('futureState', 'stopped'),
    ),
)
def test_esxi_power_state_mapping(power_state, expected):
    host = discover_hosts(
        fake_esxi_service(power_state=power_state),
        esxi_config(),
    )[0]

    assert host.virtual_machines[0].status == expected


def test_vm_uuid_priority_and_normalization():
    service = fake_esxi_service()
    vm = service.host.vm[0]
    vm.config.instanceUuid = ' {503C5AD7-0000-1111-2222-0123456789AB} '
    vm.config.uuid = '42000000-1111-2222-3333-0123456789ab'

    discovered = discover_hosts(service, esxi_config())[0].virtual_machines[0]

    assert discovered.external_id == '503c5ad7-0000-1111-2222-0123456789ab'


@pytest.mark.parametrize(
    ('instance_uuid', 'bios_uuid', 'managed_id', 'expected'),
    (
        ('not-a-uuid', '42000000-1111-2222-3333-0123456789ab', 'vm-42',
         '42000000-1111-2222-3333-0123456789ab'),
        ('not-a-uuid', '42 00 00 00 11 11 22 22-33 33 01 23 45 67 89 ab',
         'vm-42', '42000000-1111-2222-3333-0123456789ab'),
        ('00000000-0000-0000-0000-000000000000', 'bad-bios', 'vm-42', 'vm-42'),
        (None, None, 'vm-42', 'vm-42'),
    ),
)
def test_invalid_vm_uuid_falls_back_deterministically(
        instance_uuid, bios_uuid, managed_id, expected,
):
    service = fake_esxi_service()
    vm = service.host.vm[0]
    vm.config.instanceUuid = instance_uuid
    vm.config.uuid = bios_uuid
    vm._moId = managed_id

    discovered = discover_hosts(service, esxi_config())[0].virtual_machines[0]

    assert discovered.external_id == expected


def test_malformed_vm_refuses_partial_inventory():
    service = fake_esxi_service()
    malformed = deepcopy(service.host.vm[0])
    malformed.config.instanceUuid = 'invalid'
    malformed.config.uuid = 'invalid'
    malformed._moId = None
    service.host.vm.insert(0, malformed)

    with pytest.raises(ValueError, match='stable external identifier'):
        discover_hosts(service, esxi_config())


def test_malformed_nic_fails_complete_inventory():
    service = fake_esxi_service()
    service.host.vm[0].config.hardware.device[-1].key = None
    with pytest.raises(ValueError, match='stable device key'):
        discover_hosts(service, esxi_config())


def test_missing_vmware_tools_and_optional_hardware_are_safe():
    host = discover_hosts(
        fake_esxi_service(
            tools_available=False,
            optional_hardware=False,
        ),
        esxi_config(),
    )[0]

    assert host.cpu.model is None
    assert host.cpu.sockets == 0
    assert host.virtual_machines[0].interfaces[0].ip_addresses == []


def test_vm_rename_preserves_uuid_and_nic_identity():
    before = discover_hosts(fake_esxi_service(vm_name='OLD'), esxi_config())[0]
    after = discover_hosts(fake_esxi_service(vm_name='NEW'), esxi_config())[0]
    before_vm = before.virtual_machines[0]
    after_vm = after.virtual_machines[0]

    assert before_vm.original_name != after_vm.original_name
    assert before_vm.external_id == '503c5ad7-0000-1111-2222-0123456789ab'
    assert virtual_machine_source_identity(before_vm) == (
        virtual_machine_source_identity(after_vm)
    )
    assert virtual_machine_source_identity(before_vm).kind == 'vm'
    assert virtual_machine_nic_source_identity(
        before_vm, before_vm.interfaces[0],
    ) == virtual_machine_nic_source_identity(
        after_vm, after_vm.interfaces[0],
    )
    assert virtual_machine_nic_source_identity(
        before_vm, before_vm.interfaces[0],
    ).kind == 'vm-nic'


def test_power_and_network_changes_do_not_change_vm_or_nic_identity():
    before_service = fake_esxi_service(power_state='poweredOn')
    after_service = fake_esxi_service(power_state='poweredOff')
    after_nic = after_service.host.vm[0].config.hardware.device[-1]
    after_nic.deviceInfo.label = 'Renamed adapter'
    after_nic.backing.deviceName = 'Different Portgroup'
    after_nic.macAddress = '00:50:56:AA:BB:DD'

    before = discover_hosts(before_service, esxi_config())[0].virtual_machines[0]
    after = discover_hosts(after_service, esxi_config())[0].virtual_machines[0]

    assert virtual_machine_source_identity(before) == virtual_machine_source_identity(after)
    assert virtual_machine_nic_source_identity(
        before, before.interfaces[0],
    ) == virtual_machine_nic_source_identity(after, after.interfaces[0])


def test_three_nics_with_duplicate_labels_have_distinct_device_key_identities():
    service = fake_esxi_service()
    vm = service.host.vm[0]
    original = vm.config.hardware.device[-1]
    for key, mac in ((4001, '00:50:56:AA:BB:CD'), (4002, '00:50:56:AA:BB:CE')):
        nic = deepcopy(original)
        nic.key = key
        nic.macAddress = mac
        vm.config.hardware.device.append(nic)

    discovered = discover_hosts(service, esxi_config())[0].virtual_machines[0]
    identities = {
        virtual_machine_nic_source_identity(discovered, nic)
        for nic in discovered.interfaces
    }

    assert len(discovered.interfaces) == 3
    assert len(identities) == 3


def test_duplicate_vm_names_across_sources_keep_distinct_unmodified_identities():
    first_service = fake_esxi_service(vm_name='APP01')
    second_service = fake_esxi_service(vm_name='APP01')
    second_service.host.vm[0].config.instanceUuid = (
        '503c5ad7-aaaa-bbbb-cccc-0123456789ab'
    )

    first = discover_hosts(first_service, esxi_config('esxi-a'))[0].virtual_machines[0]
    second = discover_hosts(second_service, esxi_config('esxi-b'))[0].virtual_machines[0]

    assert first.original_name == second.original_name == 'APP01'
    assert virtual_machine_source_identity(first) != virtual_machine_source_identity(second)


def test_same_vm_uuid_is_isolated_by_source_instance():
    first = discover_hosts(fake_esxi_service(), esxi_config('esxi-a'))[0]
    second = discover_hosts(fake_esxi_service(), esxi_config('esxi-b'))[0]
    first_vm = first.virtual_machines[0]
    second_vm = second.virtual_machines[0]

    assert first_vm.external_id == second_vm.external_id
    assert virtual_machine_source_identity(first_vm) != (
        virtual_machine_source_identity(second_vm)
    )
    assert virtual_machine_nic_source_identity(
        first_vm, first_vm.interfaces[0],
    ) != virtual_machine_nic_source_identity(
        second_vm, second_vm.interfaces[0],
    )


def test_two_esxi_sources_resolve_only_their_own_password_references():
    resolver = MappingResolver({
        'ESXI_A_PASSWORD': 'secret-a',
        'ESXI_B_PASSWORD': 'secret-b',
    })
    connected = []
    client = EsxiClient(
        resolver=resolver,
        connector=lambda host, _user, password, _verify: connected.append(
            (host, password)
        ) or fake_esxi_service(),
        disconnecter=lambda _service: None,
    )

    for config in (esxi_config('esxi-a'), esxi_config('esxi-b', 'ESXI_B_PASSWORD')):
        with client.session(config):
            pass

    assert resolver.references == [
        SecretReference(provider='env', key='ESXI_A_PASSWORD'),
        SecretReference(provider='env', key='ESXI_B_PASSWORD'),
    ]
    assert connected == [
        ('esxi-a.example.test', 'secret-a'),
        ('esxi-b.example.test', 'secret-b'),
    ]


@pytest.mark.parametrize('verify_ssl', (True, False))
def test_esxi_client_honors_tls_flag_and_disconnects(verify_ssl):
    connected = []
    disconnected = []
    service = fake_esxi_service()
    config = replace(esxi_config(), verify_ssl=verify_ssl)
    client = EsxiClient(
        resolver=FakeResolver(),
        connector=lambda host, user, password, verify: connected.append(
            (host, user, password, verify)
        ) or service,
        disconnecter=disconnected.append,
    )

    with client.session(config) as session:
        assert session is service

    assert connected == [(
        config.address, 'root', 'fake-password', verify_ssl,
    )]
    assert disconnected == [service]


def test_default_esxi_connector_bounds_http_timeouts(monkeypatch):
    received = {}

    def connect(**values):
        received.update(values)
        return object()

    monkeypatch.setattr('pyVim.connect.SmartConnect', connect)

    esxi_client._pyvmomi_connect('esxi.test', 'reader', 'secret', True)

    assert received['httpConnectionTimeout'] == esxi_client.ESXI_IO_TIMEOUT == 15
    assert received['connectionPoolTimeout'] == 15


def test_esxi_connection_test_reports_success_and_disconnects():
    service = fake_esxi_service()
    disconnected = []
    client = EsxiClient(
        resolver=FakeResolver(),
        connector=lambda *_args: service,
        disconnecter=disconnected.append,
    )

    result = check_source_connection(esxi_config(), client=client)

    assert result.success is True
    assert result.summary == 'ESXi connection test succeeded'
    assert disconnected == [service]


def test_authentication_failure_is_safe_and_contains_no_password():
    secret = 'FAKE_ESXI_PASSWORD_MUST_NOT_APPEAR'
    client = EsxiClient(
        resolver=FakeResolver(secret),
        connector=lambda *_args: (_ for _ in ()).throw(
            RuntimeError(f'authentication failed for {secret}')
        ),
    )

    with pytest.raises(EsxiConnectionError) as error:
        with client.session(esxi_config()):
            pass

    assert secret not in repr(error.value)
    result = check_source_connection(esxi_config(), client=client)
    assert result.success is False
    assert secret not in repr(result)


def test_esxi_executor_dispatches_discovery_to_shared_reconciliation():
    service = fake_esxi_service()
    client = EsxiClient(
        resolver=FakeResolver(),
        connector=lambda *_args: service,
        disconnecter=lambda _service: None,
    )
    seen = []

    execute_esxi_source(
        esxi_config(),
        'plan',
        lambda config, hosts, mode: seen.append((config, hosts, mode)),
        client=client,
    )

    assert seen[0][0].source_type == 'esxi'
    assert seen[0][1][0].source == 'esxi'
    assert seen[0][2] == 'plan'


@pytest.mark.parametrize('failing_type', ('esxi', 'proxmox'))
def test_mixed_source_failure_isolation(failing_type):
    calls = []
    configs = (
        esxi_config(),
        replace(
            sample_source_config(),
            id='pve-a',
            source_instance='pve-a',
            legacy_identity_owner=False,
        ),
    )

    def executor(config):
        calls.append(config.id)
        if config.source_type == failing_type:
            raise RuntimeError('safe fake failure')

    dispatch = SourceExecutorDispatch({
        'esxi': executor,
        'proxmox': executor,
    })
    result = run_sources(configs, dispatch.execute)

    assert calls == ['esxi-a', 'pve-a']
    assert result.succeeded == 1
    assert result.failed == 1
