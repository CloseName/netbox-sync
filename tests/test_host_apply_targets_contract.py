"""Target preparation contracts before extracting host apply setup."""
from types import SimpleNamespace
import pytest
from tests.fakes import FakeRecord
from tests.netbox_scenarios import add_target
import netbox_sync.netbox_apply as module


def setup(api, mapped=False):
    site, kind, cluster, config = add_target(api)
    role = api.dcim.device_roles.add(FakeRecord(id=4, slug='server', name='Server'))
    platform = api.dcim.platforms.add(FakeRecord(id=5, slug='proxmox', name='Proxmox'))
    dtype = api.dcim.device_types.add(FakeRecord(id=6, slug='generic', model='Generic'))
    host = SimpleNamespace(source_id='host-a')
    config = SimpleNamespace(**vars(config))
    if mapped:
        refs = {key: {'id': row.id, 'name': row.name, 'slug': getattr(row, 'slug', '')}
                for key, row in [('site', site), ('device_role', role), ('platform', platform),
                                 ('cluster_type', kind), ('cluster', cluster)]}
        choice = {'id': dtype.id, 'name': dtype.model, 'slug': dtype.slug}
        config.onboarding_mapping = {'references': refs, 'host_types': {'host-a': choice},
                                     'hosts': [{'id': 'host-a'}]}
        config.site_slug = config.device_role_slug = config.platform_slug = 'stale-slug'
        config.cluster_type_slug = config.device_type_slug = 'stale-slug'
        config.cluster_name = 'stale-name'
    return config, host, site, cluster


@pytest.mark.parametrize('mapped', [False, True])
def test_target_order_and_explicit_selection(fake_netbox, monkeypatch, capsys, mapped):
    config, host, site, cluster = setup(fake_netbox, mapped)
    calls = []
    endpoints = [('site', fake_netbox.dcim.sites), ('role', fake_netbox.dcim.device_roles),
                 ('platform', fake_netbox.dcim.platforms), ('type', fake_netbox.dcim.device_types),
                 ('cluster_type', fake_netbox.virtualization.cluster_types),
                 ('cluster', fake_netbox.virtualization.clusters)]
    for name, endpoint in endpoints:
        method = 'filter' if name == 'cluster' else 'get'
        original = getattr(endpoint, method)
        def read(*args, _name=name, _original=original, **kwargs):
            calls.append((_name, kwargs))
            return _original(*args, **kwargs)
        monkeypatch.setattr(endpoint, method, read)
    stop = RuntimeError('reached host preflight')
    def preflight(api, actual_host, actual_site, **kwargs):
        assert actual_host is host and actual_site is site
        raise stop
    monkeypatch.setattr(module, '_preflight_host', preflight)
    capsys.readouterr()
    with pytest.raises(RuntimeError) as caught:
        module.apply_hosts(fake_netbox, [host], config, confirmed=True)
    assert caught.value is stop
    tail = calls[-6:]
    assert [name for name, _ in tail] == ['site', 'role', 'platform', 'type', 'cluster_type', 'cluster']
    assert tail[-1][1] == ({'id': cluster.id} if mapped else {'name': cluster.name})
    assert all(('id' if mapped else 'slug') in filters for _, filters in tail[:-1])
    assert fake_netbox.mutations == []
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('failure', ['site', 'role', 'platform', 'type', 'cluster_type', 'cluster', 'scope', 'kind', 'duplicate'])
def test_target_refusal_precedes_host_checks_and_writes(fake_netbox, monkeypatch, capsys, failure):
    config, host, _, cluster = setup(fake_netbox)
    endpoints = {'site': fake_netbox.dcim.sites, 'role': fake_netbox.dcim.device_roles,
                 'platform': fake_netbox.dcim.platforms, 'type': fake_netbox.dcim.device_types,
                 'cluster_type': fake_netbox.virtualization.cluster_types, 'cluster': fake_netbox.virtualization.clusters}
    if failure in endpoints:
        endpoints[failure].records.clear()
    elif failure == 'scope':
        cluster.scope_id = 999
    elif failure == 'kind':
        cluster.type = 999
    else:
        fake_netbox.virtualization.clusters.add(FakeRecord(**{**cluster.serialize(), 'id': 99}))
    def forbidden(*args, **kwargs):
        pytest.fail('host checks must not run after target refusal')
    monkeypatch.setattr(module, '_preflight_host', forbidden)
    capsys.readouterr()
    with pytest.raises(module.HostApplyError):
        module.apply_hosts(fake_netbox, [host], config, confirmed=True)
    assert fake_netbox.mutations == []
    assert capsys.readouterr().out == ''
