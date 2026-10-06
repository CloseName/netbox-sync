from copy import deepcopy
from dataclasses import replace
import socket
import pytest
from netbox_sync.host_primary_ip import select_endpoint, apply_esxi_primary
from netbox_sync.esxi_runtime import execute_esxi_runtime
from netbox_sync.application.runtime_plan import build_runtime_plan
from netbox_sync.discovery import DiscoveredHostInterface
from tests.test_esxi_runtime import _setup, _config


def prepared(api):
    hosts, _, _ = _setup(api, review=False)
    hosts[0].esxi_host_network['vmkernel'] = [
        {'name':'vmk1','ipv4':'192.0.2.20','subnet_mask':'255.255.255.0'},
        {'name':'vmk0','ipv4':'198.51.100.10','subnet_mask':'255.255.255.128'}]
    config = replace(_config(), address='198.51.100.10')
    select_endpoint(hosts, config)
    return hosts, config


def test_endpoint_not_first_vmknic_and_idempotent_native_assignment(fake_netbox):
    hosts, config = prepared(fake_netbox)
    device = fake_netbox.dcim.devices.all()[0]
    before = deepcopy(device.custom_fields)
    plan = build_runtime_plan(fake_netbox, hosts, config)
    assert plan.apply_allowed
    assert fake_netbox.mutations == []
    execute_esxi_runtime(fake_netbox, hosts, config, confirmed=True)
    nic = fake_netbox.dcim.interfaces.all()[0]
    ip = fake_netbox.ipam.ip_addresses.get(id=device.primary_ip4)
    assert nic.name == 'vmk0' and nic.type == 'virtual'
    assert ip.address == '198.51.100.10/25'
    assert ip.assigned_object_type == 'dcim.interface' and ip.assigned_object_id == nic.id
    assert device.custom_fields['sync_identities'] == before['sync_identities']
    fake_netbox.clear_mutations()
    execute_esxi_runtime(fake_netbox, hosts, config, confirmed=True)
    assert fake_netbox.mutations == []


def test_dns_address_recorded_on_native_ip(fake_netbox):
    hosts, config = prepared(fake_netbox)
    hosts[0].connection_management = None
    config = replace(config, address='esxi.example.test')
    resolver = lambda *args: [(socket.AF_INET,socket.SOCK_STREAM,6,'',('198.51.100.10',443))]
    select_endpoint(hosts, config, resolver)
    apply_esxi_primary(fake_netbox, hosts)
    assert fake_netbox.ipam.ip_addresses.all()[0].dns_name == 'esxi.example.test'


@pytest.mark.parametrize('mode', ['nat', 'multiple_a', 'missing_mask', 'multiple_hosts', 'dns_error'])
def test_ambiguous_or_unproven_endpoint_never_assigned(fake_netbox, mode):
    hosts, config = prepared(fake_netbox)
    hosts[0].connection_management = None
    resolver = None
    if mode == 'nat': config=replace(config,address='203.0.113.5')
    if mode == 'missing_mask': hosts[0].esxi_host_network['vmkernel'][1]['subnet_mask']=None
    if mode == 'multiple_hosts': hosts.append(deepcopy(hosts[0]))
    if mode in ('multiple_a', 'dns_error'):
        config=replace(config,address='esxi.example.test')
        def resolver(*args):
            if mode == 'dns_error': raise socket.gaierror()
            return [(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443)) for ip in ['198.51.100.10','192.0.2.20']]
    select_endpoint(hosts,config,resolver)
    apply_esxi_primary(fake_netbox,hosts)
    assert fake_netbox.mutations == []


@pytest.mark.parametrize('mode', ['manual_primary','foreign_ip','different_prefix','foreign_interface'])
def test_conflicts_block_entire_runtime_before_writes(fake_netbox, mode):
    hosts,config=prepared(fake_netbox)
    device=fake_netbox.dcim.devices.all()[0]
    if mode == 'manual_primary': device.primary_ip4=998
    elif mode == 'foreign_interface':
        fake_netbox.dcim.interfaces.add(id=44,device=device.id,name='vmk0',custom_fields={})
    else:
        fake_netbox.ipam.ip_addresses.add(id=77,address='198.51.100.10/'+('24' if mode=='different_prefix' else '25'),
            assigned_object_type='dcim.interface',assigned_object_id=999,vrf=None)
    with pytest.raises(ValueError): execute_esxi_runtime(fake_netbox,hosts,config,confirmed=True)
    assert fake_netbox.mutations == []


def test_proxmox_endpoint_overrides_cluster_transport_address(fake_netbox):
    hosts,config=prepared(fake_netbox)
    host=hosts[0];host.source='proxmox';host.connection_management=None;host.management_ip='10.0.0.2'
    host.interfaces=[DiscoveredHostInterface(name='vmbr0',addresses=['198.51.100.10/25'])]
    select_endpoint(hosts,replace(config,source_type='proxmox'))
    assert host.management_ip=='198.51.100.10'
    assert host.connection_management['interface']=='vmbr0'


def test_new_host_primary_through_http_api(fake_netbox):
    from tests.test_first_sync import target
    from tests.fakes.netbox_http import netbox_http
    from tests.fakes.esxi import fake_esxi_service
    from netbox_sync.esxi_discovery import discover_hosts
    config = target(fake_netbox, replace(_config(), address='198.51.100.10'))
    hosts = discover_hosts(fake_esxi_service(), config)
    hosts[0].esxi_host_network['vmkernel'] = [
        {'name': 'vmk0', 'ipv4': '198.51.100.10', 'subnet_mask': '255.255.255.128'}]
    select_endpoint(hosts, config)
    with netbox_http(fake_netbox) as (api, rows, writes):
        plan = build_runtime_plan(api, hosts, config)
        assert plan.apply_allowed and writes == []
        execute_esxi_runtime(api, hosts, config, confirmed=True)
        device = next(iter(rows['dcim.devices'].values()))
        ip = rows['ipam.ip_addresses'][device['primary_ip4']]
        assert ip['address'] == '198.51.100.10/25'
        nic = rows['dcim.interfaces'][ip['assigned_object_id']]
        assert nic['name'] == 'vmk0' and nic['device'] == device['id']
        assert not [r for r in build_runtime_plan(api, hosts, config).items
                    if r.action.value in ('CREATE', 'UPDATE')]


def test_conflict_has_actionable_public_diagnostic():
    from netbox_sync.host_primary_ip import HostPrimaryIPConflict
    from netbox_sync.worker_failure import classify
    assert classify(HostPrimaryIPConflict('internal detail'), 'planning') == 'HOST_PRIMARY_IP_CONFLICT'


@pytest.mark.parametrize("use_hostname", [False, True])
def test_scheduled_esxi_executor_selects_endpoint_before_reconciliation(fake_netbox, monkeypatch, use_hostname):
    from contextlib import contextmanager
    from netbox_sync import esxi_executor
    hosts, config = prepared(fake_netbox)
    hosts[0].connection_management = None
    if use_hostname:
        config = replace(config, address='esxi.internal.test')
        monkeypatch.setattr(socket, 'getaddrinfo', lambda *args:
            [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('198.51.100.10', 443))])
    class Client:
        @contextmanager
        def session(self, config):
            yield object()
    monkeypatch.setattr(esxi_executor, 'discover_hosts', lambda *args: hosts)
    def reconcile(config, discovered, mode):
        assert discovered[0].connection_management['address'] == '198.51.100.10/25'
        execute_esxi_runtime(fake_netbox, discovered, config, confirmed=True)
        device = fake_netbox.dcim.devices.all()[0]
        assert fake_netbox.ipam.ip_addresses.get(id=device.primary_ip4).address == '198.51.100.10/25'
    esxi_executor.execute_esxi_source(config, 'apply', reconcile, client=Client())


def test_scheduled_proxmox_executor_selects_endpoint(monkeypatch, fake_netbox):
    import netbox_sync as runtime
    from types import SimpleNamespace
    hosts, config = prepared(fake_netbox)
    host = hosts[0]
    host.source = 'proxmox'
    host.management_ip = '10.0.0.2'
    host.interfaces = [DiscoveredHostInterface(name='vmbr0', addresses=['198.51.100.10/25'])]
    monkeypatch.setattr(runtime.FileSecretResolver, 'resolve_credentials', lambda *args:
        SimpleNamespace(username='sync@pve', token_id='sync', token_secret='test'))
    monkeypatch.setattr(runtime, 'ProxmoxAPI', lambda **kwargs: object())
    monkeypatch.setattr('netbox_sync.source_tls.configure_proxmox', lambda *args: None)
    monkeypatch.setattr(runtime, 'discover_hosts', lambda *args: hosts)
    seen = []
    monkeypatch.setattr(runtime, 'execute_discovered_source', lambda config, hosts, mode, **kwargs:
        seen.append(hosts[0].management_ip))
    runtime.execute_proxmox_source(replace(config, source_type='proxmox'), 'apply')
    assert seen == ['198.51.100.10']


@pytest.mark.parametrize('names', [('AM - Docker 14', 'AM - Docker 14'),
    ('Same', 'same'), ('x' * 64 + 'A', 'x' * 64 + 'B')])
def test_duplicate_vm_names_have_blocked_plan_without_writes(fake_netbox, names):
    from tests.test_esxi_runtime import _inventory
    from tests.test_first_sync import target
    hosts = _inventory(2)
    config = target(fake_netbox, _config())
    for vm, name in zip(hosts[0].virtual_machines, names):
        vm.original_name = name
        vm.normalized_name = name
    plan = build_runtime_plan(fake_netbox, hosts, config)
    assert not plan.apply_allowed
    assert plan.items[0].reason_code == 'DUPLICATE_VM_NAME'
    assert fake_netbox.mutations == []


def test_duplicate_names_reproduce_native_writer_failure(fake_netbox):
    from tests.test_esxi_runtime import _inventory
    from tests.test_first_sync import target
    hosts = _inventory(2)
    config = target(fake_netbox, _config())
    for vm in hosts[0].virtual_machines:
        vm.original_name = vm.normalized_name = 'AM - Docker 14'
    with pytest.raises(RuntimeError, match='Duplicate discovered VM names'):
        execute_esxi_runtime(fake_netbox, hosts, config, confirmed=True)
    assert fake_netbox.mutations == []
