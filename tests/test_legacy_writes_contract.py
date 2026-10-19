"""Exact local mutation traces for the retained legacy writer."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import netbox_sync as runtime
from tests.fakes import FakeNetBox, FakeProxmox


def scenario(existing=False):
    api = FakeNetBox()
    vm = {'vmid': 100, 'name': 'fixture-vm', 'status': 'running'}
    config = {'cores': 2, 'sockets': 1, 'memory': '2048', 'onboot': 1,
              'net0': 'virtio=AA:BB:CC:DD:EE:FF,tag=12', 'scsi0': 'local:vm-100-disk-0,size=8G,backup=0'}
    pve = FakeProxmox({('pools',): [{'poolid': 'PoolA'}],
        ('nodes', 'node-a', 'qemu', 100, 'config'): config,
        ('nodes', 'node-a', 'qemu', 100, 'agent', 'network-get-interfaces'):
            {'result': [{'name': 'eth0', 'ip-addresses': [{'ip-address': '10.0.0.5', 'prefix': 24}]}]}})
    device = SimpleNamespace(name='NODE-A', id=7, site=SimpleNamespace(id=3))
    objects = runtime._load_nb_objects(api)
    def run():
        assert runtime._process_pve_tags(pve, api, objects) is objects
        assert runtime._process_pve_virtual_machine(pve, api, objects, device,
            ['Pool/PoolA'], vm, True, False) is objects
    if existing:
        run()
        # Populate the same keys a subsequent legacy catalog read supplies.
        record = api.virtualization.virtual_machines.all()[0]
        objects['virtual_machines'][str(record.serial)] = record
        objects['disks'][record.id] = {disk.name: disk for disk in api.virtualization.virtual_disks.all()}
        objects['vlans'] = {str(vlan.vid): vlan for vlan in api.ipam.vlans.all()}
        api.mutations.clear()
        vm['name'] = 'renamed-vm'
    run()
    return api, objects


@pytest.mark.parametrize('existing', [False, True], ids=['create', 'update'])
def test_legacy_mutation_trace(monkeypatch, existing):
    monkeypatch.delenv('NB_CLUSTER_ID', raising=False)
    api, _ = scenario(existing)
    expected = Path(__file__).with_name('fixtures') / ('legacy-writes-update.json' if existing else 'legacy-writes-create.json')
    assert json.loads(json.dumps(api.mutations)) == json.loads(expected.read_text(encoding='utf-8'))
    vm = api.virtualization.virtual_machines.all()[0]
    assert vm.name == ('renamed-vm' if existing else 'fixture-vm')
    assert vm.custom_fields == {'autostart': True, 'replicated': True, 'ha': False}
    assert vm.primary_ip4
    assert api.virtualization.virtual_disks.all()[0].size == 8000


def test_failed_pool_write_propagates_without_cache_update(monkeypatch):
    api = FakeNetBox()
    objects = {'tags': {}}
    error = RuntimeError('fixture refusal')
    def fail(**kwargs):
        raise error
    monkeypatch.setattr(api.extras.tags, 'create', fail)
    with pytest.raises(RuntimeError) as caught:
        runtime._process_pve_tags(FakeProxmox({('pools',): [{'poolid': 'PoolA'}]}), api, objects)
    assert caught.value is error
    assert objects == {'tags': {}}
    assert not api.mutations


@pytest.mark.parametrize('value,expected', [('8M', 8), ('8G', 8000), ('2T', 2000000), ('8K', -1)])
def test_legacy_disk_units_remain_decimal(value, expected):
    assert runtime._process_pve_disk_size(value) == expected
