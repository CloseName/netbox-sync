"""Legacy read-only reports and catalog indexing contracts."""
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as Row
import pytest
import netbox_sync as runtime
from netbox_sync.proxmox_discovery import discover_hosts
from tests.fakes import FakeProxmox
from tests.sample_data import sample_source_config, proxmox_responses


@pytest.mark.parametrize('populated', [False, True])
def test_inventory_exact_output_and_unchanged_input(capsys, populated):
    objects = {key: {} for key in ('devices', 'virtual_machines', 'ip_addresses', 'prefixes', 'vlans')}
    hosts = discover_hosts(FakeProxmox(proxmox_responses()), sample_source_config()) if populated else []
    before = deepcopy(hosts)
    runtime._run_inventory(objects, hosts)
    expected = Path(__file__).with_name('fixtures') / ('legacy-inventory-populated.json' if populated else 'legacy-inventory-empty.json')
    assert capsys.readouterr().out == ''.join(json.loads(expected.read_text(encoding='utf-8')))
    assert hosts == before
    assert all(not rows for rows in objects.values())


def test_plan_reports_all_outcomes_without_mutating_records(capsys):
    responses = {('nodes',): [{'node': 'missing'}, {'node': 'present'}],
                 ('nodes', 'missing', 'qemu'): [{'vmid': 1}],
                 ('nodes', 'present', 'qemu'): [dict(vmid=i, name=f'vm{i}', status='running') for i in (2, 3, 4)]}
    for i in (2, 3, 4):
        responses[('nodes', 'present', 'qemu', i, 'config')] = dict(cores=2, sockets=1, memory=1024)
    device = Row(id=10)
    changed = Row(name='old', vcpus='invalid', memory=None, status='offline', device=None)
    same = Row(name='vm4', vcpus='2.0', memory='1024', status=Row(value='active'), device=device)
    objects = {'devices': {'present': device}, 'virtual_machines': {'3': changed, '4': same}}
    before = deepcopy(objects)
    runtime._run_plan(FakeProxmox(responses), objects)
    assert capsys.readouterr().out == (
        '=== SAFE PLAN MODE ===\nNo changes will be written to NetBox.\n\n'
        'BLOCKED node=missing: NetBox device with matching name was not found\n  BLOCKED vmid=1 name=-\n'
        'NODE node=present netbox_device_id=10\n'
        '  CREATE vmid=2 name=vm2 vcpus=2 memory=1024 status=active\n'
        '  UPDATE vmid=3 name=vm3 name:old->vm3 vcpus:None->2 memory:None->1024 status:offline->active device:None->10\n'
        '  SKIP vmid=4 name=vm4 reason=no-change\n\n'
        'Plan summary:\n  CREATE:  1\n  UPDATE:  1\n  SKIP:    1\n  BLOCKED: 1\n')
    assert objects == before


def test_catalog_read_order_and_index_keys():
    calls = []
    data = [
        ('devices', [Row(name='HOST'), Row(name='Host')]),
        ('virtual_machines', [Row(serial='42')]),
        ('interfaces', [Row(virtual_machine=Row(id=7), name='eth0')]),
        ('mac_addresses', [Row(mac_address='AA:BB')]),
        ('prefixes', [Row(prefix='10.0.0.0/24')]),
        ('ip_addresses', [{'address': '10.0.0.1/24'}]),
        ('vlans', [Row(vid=12)]),
        ('virtual_disks', [Row(virtual_machine=Row(id=7), name='disk0')]),
        ('tags', [Row(name='managed')]),
    ]
    def endpoint(name, rows):
        def all_rows():
            calls.append(name)
            return rows
        return Row(all=all_rows)  # No write methods available.
    endpoints = {name: endpoint(name, rows) for name, rows in data}
    api = Row(dcim=Row(**{n: endpoints[n] for n in ('devices', 'mac_addresses')}),
              virtualization=Row(**{n: endpoints[n] for n in ('virtual_machines', 'interfaces', 'virtual_disks')}),
              ipam=Row(**{n: endpoints[n] for n in ('prefixes', 'ip_addresses', 'vlans')}),
              extras=Row(tags=endpoints['tags']))
    result = runtime._load_nb_objects(api)
    assert calls == [name for name, _ in data]
    assert result == dict(devices={'host': data[0][1][-1]}, virtual_machines={'42': data[1][1][0]},
        virtual_machines_interfaces={7: {'eth0': data[2][1][0]}}, mac_addresses={'AA:BB': data[3][1][0]},
        prefixes={'10.0.0.0/24': data[4][1][0]}, ip_addresses={'10.0.0.1/24': data[5][1][0]},
        vlans={'12': data[6][1][0]}, disks={7: {'disk0': data[7][1][0]}}, tags={'managed': data[8][1][0]})
    assert result['devices']['host'] is data[0][1][-1]
