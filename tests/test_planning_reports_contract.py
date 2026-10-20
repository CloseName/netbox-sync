"""Read-only planner and disappearance output contracts."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.fakes import FakeProxmox, FakeRecord
from tests.netbox_scenarios import add_target
from tests.sample_data import proxmox_responses, sample_source_config
from netbox_sync.proxmox_discovery import discover_hosts
from netbox_sync.netbox_lxc_planner import plan_lxc_containers
from netbox_sync.netbox_disappearance import report_missing_managed_objects
from netbox_sync.netbox_lxc_metadata import build_lxc_custom_fields


def scenario(api, kind):
    _, _, cluster, config = add_target(api)
    hosts = discover_hosts(FakeProxmox(proxmox_responses()), sample_source_config())
    container = hosts[0].containers[0]
    if kind.startswith('lxc-'):
        mode = kind[4:]
        if mode != 'create':
            cf = build_lxc_custom_fields(container, {}) if mode in ('match', 'duplicate-identity') else {}
            count = 2 if mode.startswith('duplicate') else 1
            for i in range(count):
                api.virtualization.virtual_machines.add(FakeRecord(
                    id=50+i, name=container.original_name.upper(), cluster=cluster,
                    tenant=object() if mode == 'tenant' else None, custom_fields=deepcopy(cf)))
        return lambda: plan_lxc_containers(api, hosts[0], cluster)
    if kind != 'clean':
        # A missing guest suppresses warnings for its interfaces.
        for ident, source_id in [(50, 'node-a:999'), (51, 'node-a:100')]:
            api.virtualization.virtual_machines.add(FakeRecord(id=ident, name=f'vm-{ident}', cluster=cluster,
                custom_fields={'sync_identities': [{'source': 'proxmox', 'source_id': source_id}]}))
            api.virtualization.interfaces.add(FakeRecord(id=ident+100, name='missing-nic', virtual_machine=ident,
                custom_fields={'sync_identities': [{'source': 'proxmox', 'source_id': source_id+':net99'}]}))
    return lambda: report_missing_managed_objects(api, hosts, config)


@pytest.mark.parametrize('kind', ['lxc-create', 'lxc-match', 'lxc-adopt', 'lxc-duplicate-identity', 'lxc-duplicate-name', 'lxc-tenant', 'clean', 'missing'])
def test_read_only_output(fake_netbox, capsys, kind):
    run = scenario(fake_netbox, kind)
    capsys.readouterr()
    run()
    actual = capsys.readouterr().out
    fixture = Path(__file__).parent / 'fixtures' / 'planning_reports' / (kind+'.txt')
    assert actual == fixture.read_text(encoding='utf-8')
    assert fake_netbox.mutations == []
    if kind == 'missing':
        assert actual.count('WARNING MISSING GUEST') == 1
        assert actual.count('WARNING MISSING INTERFACE') == 1
    if kind.startswith('lxc-duplicate'):
        assert 'conflict=1' in actual


@pytest.mark.parametrize('failure', ['site', 'cluster', 'ambiguous_identity'])
def test_disappearance_refusal_does_not_write_or_print(fake_netbox, capsys, failure):
    run = scenario(fake_netbox, 'missing')
    if failure == 'site':
        fake_netbox.dcim.sites.records.clear()
    elif failure == 'cluster':
        fake_netbox.virtualization.clusters.records.clear()
    else:
        record = fake_netbox.virtualization.virtual_machines.records[0]
        record.custom_fields['sync_identities'].append({'source': 'proxmox', 'source_id': 'node-a:998'})
    capsys.readouterr()
    with pytest.raises(RuntimeError): run()
    assert capsys.readouterr().out == ''
    assert fake_netbox.mutations == []

@pytest.mark.parametrize('missing_cluster', [False, True])
def test_host_plan_output_is_read_only(fake_netbox, capsys, missing_cluster):
    from tests.test_host_apply_preflight_contract import prepared
    from netbox_sync.netbox_planner import plan_hosts
    config, hosts = prepared(fake_netbox)
    hosts = hosts[:1]
    hosts[0].hardware_identity['observed_at'] = '2026-01-01T00:00:00+00:00'
    if missing_cluster:
        fake_netbox.virtualization.clusters.records.clear()
    capsys.readouterr()
    assert plan_hosts(fake_netbox, {'devices': {}}, hosts, config) is None
    actual = {'output': capsys.readouterr().out, 'error': None}
    fixture = Path(__file__).parent / 'fixtures' / 'planning_reports' / f'host-{missing_cluster}.json'
    assert actual == json.loads(fixture.read_text(encoding='utf-8'))
    assert fake_netbox.mutations == []
