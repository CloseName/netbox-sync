"""Observed host networking must never become inferred NetBox network writes."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest
from netbox_sync.esxi_host_network import collect_host_network, HostNetworkPrerequisiteError
from netbox_sync.esxi_discovery import discover_hosts
from netbox_sync.esxi_runtime import execute_esxi_runtime
from netbox_sync.application.runtime_plan import build_runtime_plan
from netbox_sync.prerequisites import definition, reconcile
from tests.fakes.esxi import fake_esxi_service, ns
from tests.test_esxi_runtime import _config, _setup
from tests.test_first_sync import target
from tests.fakes.netbox_http import netbox_http


def test_standard_topology_and_vm_bridge_share_provider_name():
    service = fake_esxi_service()
    network = service.host.config.network
    network.pnic[0].driver = 'ixgben'
    network.pnic[0].linkSpeed.duplex = True
    network.vswitch[0].mtu = 9000
    network.vnic[0].device = 'vmk0'
    network.vnic[0].spec.ip.subnetMask = '255.255.255.0'
    host = discover_hosts(service, _config())[0]
    facts = host.esxi_host_network
    assert facts['physical_nics'][0]['switches'] == ['vSwitch0']
    assert facts['physical_nics'][0]['speed_mbps'] == 1000
    assert facts['switches'][0]['uplinks'] == ['vmnic0']
    assert facts['switches'][0]['mtu'] == 9000
    assert {g['vlan_id'] for g in facts['port_groups']} == {0, 120}
    assert host.virtual_machines[0].interfaces[0].bridge in facts['switches'][0]['port_groups']
    assert facts['vmkernel'][0]['name'] == 'vmk0'
    assert facts['vmkernel'][0]['ipv4'] == '192.0.2.10'
    assert facts['vmkernel'][0]['subnet_mask'] == '255.255.255.0'


def test_missing_and_empty_are_distinct_and_sdk_objects_never_escape():
    import json
    assert collect_host_network(ns()) == {'version': 1, 'available': False}
    assert collect_host_network(ns(config=ns(network=ns())))['available'] is True
    service = fake_esxi_service()
    del service.host.config.network.pnic[0].linkSpeed
    service.host.config.network.secret = 'not copied'
    result = collect_host_network(service.host)
    assert result['physical_nics'][0]['link_up'] is False
    assert result['physical_nics'][0]['speed_mbps'] is None
    assert 'not copied' not in json.dumps(result)


def test_ordering_and_distributed_connections_are_explicit():
    service = fake_esxi_service()
    network = service.host.config.network
    network.proxySwitch = [ns(dvsName='DVS')]
    network.vnic[0].portgroup = None
    network.vnic[0].spec.portgroup = None
    network.vnic[0].spec.distributedVirtualPort = ns(
        switchUuid='dvs-uuid', portgroupKey='pg-42', portKey='12')
    network.vnic[0].spec.ip.ipV6Config = ns(ipV6Address=[ns(ipAddress='2001:db8::1', prefixLength=64)])
    before = collect_host_network(service.host)
    network.portgroup.reverse()
    assert collect_host_network(service.host) == before
    assert before['distributed_switch_count'] == 1
    assert before['vmkernel'][0]['distributed_switch_uuid'] == 'dvs-uuid'
    assert before['vmkernel'][0]['port_group'] is None
    assert before['vmkernel'][0]['ipv6'] == ['2001:db8::1/64']


def test_legacy_managed_device_receives_snapshot_without_network_objects(fake_netbox):
    hosts, vm, _ = _setup(fake_netbox, review=False)
    device = fake_netbox.dcim.devices.all()[0]
    device.custom_fields.pop('esxi_host_network')
    device.custom_fields['operator_field'] = 'keep'
    original_name = device.name
    execute_esxi_runtime(fake_netbox, hosts, _config(), confirmed=True)
    assert device.custom_fields['esxi_host_network'] == hosts[0].esxi_host_network
    assert device.custom_fields['operator_field'] == 'keep'
    assert device.name == original_name
    assert fake_netbox.dcim.interfaces.all() == []
    assert all(r.assigned_object_type == 'virtualization.vminterface'
               for r in fake_netbox.ipam.ip_addresses.all())
    fake_netbox.clear_mutations()
    execute_esxi_runtime(fake_netbox, hosts, _config(), confirmed=True)
    assert fake_netbox.mutations == []
    hosts[0].esxi_host_network['physical_nics'][0]['speed_mbps'] = 10000
    execute_esxi_runtime(fake_netbox, hosts, _config(), confirmed=True)
    assert len(fake_netbox.mutations) == 1
    assert fake_netbox.mutations[0][1] == 'dcim.devices'


def test_new_host_roundtrip_and_readonly_plan(fake_netbox):
    config = target(fake_netbox, _config())
    hosts = discover_hosts(fake_esxi_service(), config)
    with netbox_http(fake_netbox) as (api, rows, writes):
        plan = build_runtime_plan(api, hosts, config)
        assert plan.apply_allowed and writes == []
        execute_esxi_runtime(api, hosts, config, confirmed=True)
        device = next(iter(rows['dcim.devices'].values()))
        assert device['custom_fields']['esxi_host_network'] == hosts[0].esxi_host_network
        assert rows['dcim.interfaces'] == {}
        assert not [r for r in build_runtime_plan(api, hosts, config).items
                    if r.action.value in ('CREATE', 'UPDATE')]


@pytest.mark.parametrize('mode', ['missing', 'wrong_type', 'provisioning'])
def test_field_preparation_blocks_before_any_writes(fake_netbox, mode):
    config = target(fake_netbox, _config())
    hosts = discover_hosts(fake_esxi_service(), config)
    field = fake_netbox.extras.custom_fields.filter(name='esxi_host_network')[0]
    if mode == 'missing':
        fake_netbox.extras.custom_fields.records.remove(field)
    elif mode == 'wrong_type':
        field.type = 'text'
    else:
        field.status = 'provisioning'
    plan = build_runtime_plan(fake_netbox, hosts, config)
    assert not plan.apply_allowed
    assert any(r.reason_code == 'HOST_NETWORK_FIELD_REQUIRED' for r in plan.items)
    with pytest.raises(HostNetworkPrerequisiteError):
        execute_esxi_runtime(fake_netbox, hosts, config, confirmed=True)
    assert fake_netbox.mutations == []


def test_table_rendering_escapes_names_and_keeps_zero_vlan():
    pytest.importorskip('django')
    from django.template import Engine, Context
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('network_display', root / 'deploy/netbox_guard/network_display.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    service = fake_esxi_service()
    service.host.config.network.portgroup[0].spec.name = '<script>test</script>'
    data = collect_host_network(service.host)
    before = deepcopy(data)
    panel = module.network_panel(data)
    assert data == before
    engine = Engine(dirs=[str(root / 'deploy/netbox_guard/templates')])
    html = engine.get_template('netbox_guard/esxi_network.html').render(Context({'network_panel': panel}))
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert 'vmnic0' in html and 'vSwitch0' in html and '192.0.2.10' in html
    assert any('0' in row for table in panel['tables'] for row in table['rows'])
    assert module.network_panel(None) is None
    assert module.network_panel({'version': 1, 'available': False})['tables'] == []
