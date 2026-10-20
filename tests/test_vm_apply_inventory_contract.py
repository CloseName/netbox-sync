"""Characterize VM target reads before extracting preparation."""
from types import SimpleNamespace

import pytest

import netbox_sync.netbox_vm_apply as module
from tests.fakes import FakeRecord
from tests.netbox_scenarios import add_target


@pytest.mark.parametrize('mapped', [False, True])
def test_vm_reads_keep_order_and_independent_selections(fake_netbox, monkeypatch, capsys, mapped):
    site, kind, cluster, config = add_target(fake_netbox)
    config = SimpleNamespace(**vars(config))
    if mapped:
        config.cluster_name = 'stale-name'
        config.onboarding_mapping = {'references': {'cluster': {'id': cluster.id}}}
    calls = []
    for label, endpoint, method in [
        ('site', fake_netbox.dcim.sites, 'get'),
        ('kind', fake_netbox.virtualization.cluster_types, 'get'),
        ('cluster', fake_netbox.virtualization.clusters, 'filter'),
    ]:
        original = getattr(endpoint, method)
        def read(*args, _label=label, _original=original, **kwargs):
            calls.append((_label, kwargs))
            return _original(*args, **kwargs)
        monkeypatch.setattr(endpoint, method, read)
    all_records = [object(), object()]
    target_records = [object()]  # Deliberately not derived from all_records.
    endpoint = fake_netbox.virtualization.virtual_machines
    def all_read():
        calls.append(('all', {}))
        return iter(all_records)
    def target_read(**kwargs):
        calls.append(('target', kwargs))
        return iter(target_records)
    monkeypatch.setattr(endpoint, 'all', all_read)
    monkeypatch.setattr(endpoint, 'filter', target_read)
    vm = SimpleNamespace(node_source_id='node', vmid=1)
    monkeypatch.setattr(module, '_identity', lambda vm: 'identity')
    monkeypatch.setattr(module, 'netbox_vm_name', lambda vm: 'vm')
    stop = RuntimeError('preflight boundary')
    def preflight(actual_all, actual_target, actual_vm, actual_cluster):
        assert isinstance(actual_all, list) and isinstance(actual_target, list)
        assert actual_all == all_records and actual_target == target_records
        assert actual_vm is vm and actual_cluster is cluster
        raise stop
    monkeypatch.setattr(module, '_preflight_vm', preflight)
    with pytest.raises(RuntimeError) as caught:
        module.apply_virtual_machines(fake_netbox, [SimpleNamespace(virtual_machines=[vm])], config, confirmed=True)
    assert caught.value is stop
    assert calls == [('site', {'slug': site.slug}), ('kind', {'slug': kind.slug}),
                     ('cluster', {'id': cluster.id} if mapped else {'name': cluster.name}),
                     ('all', {}), ('target', {'cluster_id': cluster.id})]
    assert fake_netbox.mutations == []
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('failure', ['site', 'kind', 'cluster', 'scope', 'scope_type', 'type', 'duplicate', 'all', 'target'])
def test_preparation_errors_stop_before_discovery_and_writes(fake_netbox, monkeypatch, capsys, failure):
    _, _, cluster, config = add_target(fake_netbox)
    endpoints = {'site': fake_netbox.dcim.sites, 'kind': fake_netbox.virtualization.cluster_types,
                 'cluster': fake_netbox.virtualization.clusters}
    if failure in endpoints:
        endpoints[failure].records.clear()
    elif failure == 'scope':
        cluster.scope_id = 999
    elif failure == 'scope_type':
        cluster.scope_type = 'dcim.region'
    elif failure == 'type':
        cluster.type = 999
    elif failure == 'duplicate':
        fake_netbox.virtualization.clusters.add(FakeRecord(**{**cluster.serialize(), 'id': 99}))
    read_error = RuntimeError('read failed')
    if failure in ('all', 'target'):
        def broken(*args, **kwargs):
            raise read_error
        monkeypatch.setattr(fake_netbox.virtualization.virtual_machines,
                            'all' if failure == 'all' else 'filter', broken)
    class UnreadHosts:
        def __iter__(self):
            pytest.fail('discovery must not be consumed after preparation failure')
    with pytest.raises(RuntimeError) as caught:
        module.apply_virtual_machines(fake_netbox, UnreadHosts(), config, confirmed=True)
    if failure in ('all', 'target'):
        assert caught.value is read_error
    else:
        assert isinstance(caught.value, module.VMApplyError)
        if failure in ('site', 'kind'):
            description = 'site' if failure == 'site' else 'cluster type'
            slug = config.site_slug if failure == 'site' else config.cluster_type_slug
            assert str(caught.value) == f"NetBox prerequisite not found: {description} filters={{'slug': '{slug}'}}"
        else:
            count = 2 if failure == 'duplicate' else 0
            assert str(caught.value) == f'Expected exactly one target cluster {config.cluster_name!r}; found {count}'
    assert fake_netbox.mutations == []
    assert capsys.readouterr().out == ''
