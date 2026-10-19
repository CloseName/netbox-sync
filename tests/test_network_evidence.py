"""Incomplete API responses and neighbor announcements must not become cable claims."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from pyVmomi import vim, vmodl

from netbox_sync.esxi_network_neighbors import collect_neighbors
from netbox_sync.proxmox_host_network import snapshot
from netbox_sync.proxmox_discovery import discover_hosts
from tests.fakes import FakeProxmox
from tests.sample_data import proxmox_responses, sample_source_config


spec = importlib.util.spec_from_file_location('network_display', Path(__file__).resolve().parents[1] / 'deploy/netbox_guard/network_display.py')
display = importlib.util.module_from_spec(spec)
spec.loader.exec_module(display)


def test_missing_references_are_deterministic_and_not_permission_verdicts():
    rows = [{'iface': 'tagged', 'type': 'vlan', 'vlan-raw-device': 'uplink'},
            {'iface': 'br-isolated', 'type': 'bridge', 'bridge_ports': ''},
            {'iface': 'team', 'type': 'bond', 'slaves': 'eth-a eth-b'},
            {'iface': 'eth-a', 'type': 'eth'}]
    result = snapshot(rows, ['guest-lan', 'br-isolated'])
    assert result == snapshot(rows[::-1], ['br-isolated', 'guest-lan'])
    assert {r['target'] for r in result['coverage']['missing_references']} == {'guest-lan', 'uplink', 'eth-b'}
    assert result['coverage']['status'] == 'missing_references'
    assert 'причина автоматически не подтверждена' in ' '.join(display.proxmox_panel(result)['notes'])
    assert snapshot([{'iface': 'empty', 'type': 'bridge'}])['coverage']['status'] == 'references_resolved'


def test_collector_checks_guest_references_without_extra_network_reads():
    host = discover_hosts(FakeProxmox(proxmox_responses()), sample_source_config())[0]
    bridges = {nic.bridge for guest in [*host.virtual_machines, *host.containers] for nic in guest.interfaces if nic.bridge}
    names = {r['name'] for r in host.proxmox_host_network['interfaces']}
    missing = host.proxmox_host_network['coverage']['missing_references']
    assert {r['target'] for r in missing if r['source'] == 'guest'} == bridges - names


def test_neighbor_observations_are_allowlisted_stable_and_not_cables():
    cdp = NS(ttl=100, samples=1, devId='other-hypervisor', systemName='other-hypervisor',
             portId='vmnic7', hardwarePlatform='VMware ESX', secret='SECRET')
    lldp = NS(timeToLive=120, chassisId='switch-id', portId='Gi1/1', parameter=['SECRET'])
    calls = []
    def query():
        calls.append(True)
        return [NS(device='nic-a', connectedSwitchPort=cdp, lldpInfo=lldp),
                NS(device='nic-b', connectedSwitchPort=None, lldpInfo=None)]
    host = NS(configManager=NS(networkSystem=NS(QueryNetworkHint=query)))
    result = collect_neighbors(host)
    assert len(calls) == 1
    assert result['status'] == 'collected'
    assert len(result['observations']) == 2
    assert result['provider_port_confirmed'] is False
    assert 'SECRET' not in str(result)
    cdp.ttl, cdp.samples, lldp.timeToLive = 90, 99, 110
    assert collect_neighbors(host) == result
    cdp.ttl, lldp.timeToLive = 0, 0
    assert collect_neighbors(host)['status'] == 'empty'
    panel = display.network_panel({'version': 1, 'available': True, 'neighbors': result})
    assert panel['tables'][-1]['rows'][0][0] == 'nic-a'
    assert 'не подтверждает' in ' '.join(panel['notes'])


@pytest.mark.parametrize('error,status', [(vim.fault.NoPermission(), 'denied'),
    (vmodl.fault.NotSupported(), 'unsupported'), (RuntimeError('SECRET'), 'error')])
def test_optional_neighbor_failure_is_explicit_and_sanitized(error, status):
    def query():
        raise error
    result = collect_neighbors(NS(configManager=NS(networkSystem=NS(QueryNetworkHint=query))))
    assert result['status'] == status
    assert result['observations'] == []
    assert 'SECRET' not in str(result)


def test_missing_network_system_is_unavailable():
    assert collect_neighbors(NS())['status'] == 'unavailable'
