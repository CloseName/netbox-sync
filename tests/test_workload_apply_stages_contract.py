"""Behavioral baseline for separate VM/LXC preparation, reports and writes."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.fakes import FakeProxmox, FakeRecord
from tests.fakes.netbox import FakeEndpoint
from tests.netbox_scenarios import add_target
from tests.sample_data import proxmox_responses, sample_source_config
from netbox_sync.proxmox_discovery import discover_hosts
from netbox_sync.netbox_vm_apply import apply_virtual_machines
from netbox_sync.netbox_lxc_apply import apply_lxc_containers


def prepared(api, kind):
    _, _, cluster, config = add_target(api)
    hosts = discover_hosts(FakeProxmox(proxmox_responses()), sample_source_config())
    attribute = 'virtual_machines' if kind == 'vm' else 'containers'
    first = next(item for host in hosts for item in getattr(host, attribute))
    second = deepcopy(first)
    second.vmid = first.vmid + 1
    second.source_id = str(first.source_id) + ':second'
    second.original_name = 'second-workload'
    second.normalized_name = 'second-workload'
    for host in hosts:
        setattr(host, attribute, [])
    setattr(hosts[0], attribute, [second, first])
    apply = apply_virtual_machines if kind == 'vm' else apply_lxc_containers
    return config, cluster, hosts, apply


@pytest.mark.parametrize('kind', ['vm', 'lxc'])
@pytest.mark.parametrize('scenario', ['create', 'unconfirmed', 'update', 'replay'])
def test_complete_output_payloads_and_replay(fake_netbox, capsys, kind, scenario):
    config, cluster, hosts, apply = prepared(fake_netbox, kind)
    if scenario in ('update', 'replay'):
        apply(fake_netbox, hosts, config, confirmed=True)
        for record in fake_netbox.virtualization.virtual_machines.all():
            record.cluster = cluster
            if scenario == 'update':
                record.vcpus = 999
                record.memory = 1
        fake_netbox.clear_mutations()
    capsys.readouterr()
    apply(fake_netbox, hosts, config, confirmed=scenario != 'unconfirmed')
    actual = {'output': capsys.readouterr().out,
              'mutations': json.loads(json.dumps(fake_netbox.mutations))}
    snapshot = Path(__file__).parent / 'fixtures' / 'workload_apply' / f'{kind}-{scenario}.json'
    assert actual == json.loads(snapshot.read_text(encoding='utf-8'))
    if scenario in ('unconfirmed', 'replay'):
        assert fake_netbox.mutations == []
    else:
        assert len(fake_netbox.mutations) == 2
        assert {m[0] for m in fake_netbox.mutations} == {'create' if scenario == 'create' else 'update'}


@pytest.mark.parametrize('kind', ['vm', 'lxc'])
@pytest.mark.parametrize('failure_at', [1, 2])
@pytest.mark.parametrize('operation', ['create', 'update'])
def test_write_failure_preserves_prefix_and_stops(fake_netbox, monkeypatch, capsys, kind, failure_at, operation):
    config, cluster, hosts, apply = prepared(fake_netbox, kind)
    if operation == 'update':
        apply(fake_netbox, hosts, config, confirmed=True)
        for record in fake_netbox.virtualization.virtual_machines.all():
            record.cluster = cluster
            record.vcpus = 999
        fake_netbox.clear_mutations()
    capsys.readouterr()
    calls = []
    error = RuntimeError('write failure')
    cls = FakeEndpoint if operation == 'create' else FakeRecord
    original = getattr(cls, operation)
    def write(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == failure_at:
            raise error
        return original(self, *args, **kwargs)
    monkeypatch.setattr(cls, operation, write)
    with pytest.raises(RuntimeError) as caught:
        apply(fake_netbox, hosts, config, confirmed=True)
    assert caught.value is error
    assert len(fake_netbox.mutations) == failure_at - 1
    assert len(calls) == failure_at
    assert 'APPLY SUMMARY' not in capsys.readouterr().out


def test_native_vm_disks_prevent_aggregate_disk_update(fake_netbox, capsys):
    config, cluster, hosts, apply = prepared(fake_netbox, 'vm')
    apply(fake_netbox, hosts, config, confirmed=True)
    records = fake_netbox.virtualization.virtual_machines.all()
    for record in records:
        record.cluster = cluster
        record.disk = -1
    fake_netbox.virtualization.virtual_disks.add(FakeRecord(id=1, virtual_machine={'id': records[0].id}))
    fake_netbox.clear_mutations()
    capsys.readouterr()
    apply(fake_netbox, hosts, config, confirmed=True)
    assert records[0].disk == -1
    assert len(fake_netbox.mutations) == 1
    assert fake_netbox.mutations[0][2] == records[1].id
    assert set(fake_netbox.mutations[0][3]) == {'disk'}
