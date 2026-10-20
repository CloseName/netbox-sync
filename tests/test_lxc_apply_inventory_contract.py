"""Lock down LXC preparation independently of VM preparation."""
from types import SimpleNamespace

import pytest

import netbox_sync.netbox_lxc_apply as module
from tests.fakes import FakeRecord
from tests.netbox_scenarios import add_target


@pytest.mark.parametrize('mapped', [False, True])
@pytest.mark.parametrize('membership', ['target', 'other', 'missing', 'none', 'dict'])
def test_lxc_selection_uses_single_inventory_and_object_cluster_id(fake_netbox, monkeypatch, capsys, mapped, membership):
    site, _, cluster, config = add_target(fake_netbox)
    config = SimpleNamespace(**vars(config))
    config.cluster_type_slug = 'unused-kind'
    cluster.type = 999  # LXC does not validate cluster type.
    if mapped:
        config.cluster_name = 'stale-name'
        config.onboarding_mapping = {'references': {'cluster': {'id': cluster.id}}}
    record = SimpleNamespace(name='MATCH')
    if membership != 'missing':
        record.cluster = {'target': cluster, 'other': SimpleNamespace(id=99),
                          'none': None, 'dict': {'id': cluster.id}}[membership]
    records = [record, SimpleNamespace(name='unrelated', cluster=cluster)]
    calls = []
    for label, endpoint, method in [('site', fake_netbox.dcim.sites, 'get'),
                                     ('cluster', fake_netbox.virtualization.clusters, 'filter')]:
        original = getattr(endpoint, method)
        def read(*args, _label=label, _original=original, **kwargs):
            calls.append((_label, kwargs))
            return _original(*args, **kwargs)
        monkeypatch.setattr(endpoint, method, read)
    def all_read():
        calls.append(('all', {}))
        return iter(records)
    monkeypatch.setattr(fake_netbox.virtualization.virtual_machines, 'all', all_read)
    def forbidden(*args, **kwargs):
        pytest.fail('LXC must not request a separate VM selection or cluster type')
    monkeypatch.setattr(fake_netbox.virtualization.virtual_machines, 'filter', forbidden)
    monkeypatch.setattr(fake_netbox.virtualization.cluster_types, 'get', forbidden)
    container = SimpleNamespace(source_id='lxc:1', original_name='match')
    def identity(actual, item):
        assert isinstance(actual, list) and actual == records
        assert item is container
        return []
    monkeypatch.setattr(module, '_find_identity_matches', identity)
    stop = RuntimeError('desired boundary')
    def desired(item, target, existing):
        assert item is container and target is cluster and existing is None
        raise stop
    monkeypatch.setattr(module, '_desired_fields', desired)
    with pytest.raises(RuntimeError) as caught:
        module.apply_lxc_containers(fake_netbox, [SimpleNamespace(containers=[container])], config, confirmed=True)
    if membership == 'target':
        assert type(caught.value) is module.LXCApplyError
        assert str(caught.value) == "LXC adoption candidate exists without sync identity: 'match'"
    else:
        assert caught.value is stop
    assert calls == [('site', {'slug': site.slug}),
                     ('cluster', {'id': cluster.id} if mapped else {'name': cluster.name}), ('all', {})]
    assert fake_netbox.mutations == []
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('failure', ['site', 'cluster', 'scope', 'scope_type', 'duplicate', 'read'])
def test_lxc_preparation_refuses_before_discovery(fake_netbox, monkeypatch, capsys, failure):
    _, _, cluster, config = add_target(fake_netbox)
    if failure == 'site':
        fake_netbox.dcim.sites.records.clear()
    elif failure == 'cluster':
        fake_netbox.virtualization.clusters.records.clear()
    elif failure == 'scope':
        cluster.scope_id = 99
    elif failure == 'scope_type':
        cluster.scope_type = 'dcim.region'
    elif failure == 'duplicate':
        fake_netbox.virtualization.clusters.add(FakeRecord(**{**cluster.serialize(), 'id': 99}))
    error = RuntimeError('inventory unavailable')
    def read():
        if failure == 'read':
            raise error
        pytest.fail('VM reads must not follow target failure')
    monkeypatch.setattr(fake_netbox.virtualization.virtual_machines, 'all', read)
    class UnreadHosts:
        def __iter__(self):
            pytest.fail('source must not be consumed after preparation failure')
    with pytest.raises(RuntimeError) as caught:
        module.apply_lxc_containers(fake_netbox, UnreadHosts(), config, confirmed=True)
    if failure == 'read':
        assert caught.value is error
    else:
        assert type(caught.value) is module.LXCApplyError
        assert str(caught.value) == ('Target site not found' if failure == 'site' else 'Expected exactly one target cluster')
    assert fake_netbox.mutations == []
    assert capsys.readouterr().out == ''
