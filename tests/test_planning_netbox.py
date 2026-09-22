"""Recording NetBox facade proves exact planning has zero external writes."""

from netbox_sync.application.planning_netbox import PlanningNetBox
from netbox_sync import netbox_full_apply
from netbox_sync.netbox_vm_apply import apply_virtual_machines
from netbox_sync.proxmox_discovery import discover_hosts
from netbox_sync.esxi_runtime import execute_esxi_runtime
from tests.fakes.netbox import FakeNetBox, FakeRecord
from tests.fakes import FakeProxmox
from tests.netbox_scenarios import add_target, vm_identity
from tests.sample_data import proxmox_responses, sample_source_config
from tests.test_esxi_runtime import _config as esxi_config, _setup as setup_esxi


def test_facade_records_create_and_update_without_touching_underlying_api():
    """All apparent writes stay in the in-memory plan."""
    api = FakeNetBox()
    api.dcim.devices.add(FakeRecord(id=10, name='before', custom_fields={'manual': 'keep'}))
    facade = PlanningNetBox(api)
    device = facade.dcim.devices.get(id=10)
    device.update({'name': 'after'})
    created = facade.virtualization.virtual_machines.create(name='new', cluster=1)
    assert created.id < 0
    assert api.dcim.devices.get(id=10).name == 'before'
    assert api.virtualization.virtual_machines.all() == []
    assert api.mutations == []
    assert [mutation.operation for mutation in facade.mutations] == ['update', 'create']


def test_facade_preserves_pynetbox_relation_objects_during_reads():
    """Serialized relation IDs must not replace relation objects used by planners."""
    api = FakeNetBox()
    cluster = FakeRecord(id=3, name='cluster')
    api.virtualization.virtual_machines.add(FakeRecord(id=10, name='vm', cluster=cluster))
    facade = PlanningNetBox(api)
    assert facade.virtualization.virtual_machines.get(id=10).cluster.id == 3


def test_facade_get_accepts_positional_id_for_existing_and_planned_records():
    """Positional detail lookups retain the pynetbox Endpoint.get contract."""
    api = FakeNetBox()
    existing = api.dcim.devices.add(FakeRecord(id=10, name='existing'))
    facade = PlanningNetBox(api)
    result = facade.dcim.devices.get(10)
    assert result.id == existing.id
    assert result.name == existing.name
    created = facade.dcim.devices.create(name='planned')
    assert facade.dcim.devices.get(created.id) is created


def test_facade_get_supports_keyword_lookup_for_planned_record():
    """Keyword lookups can resolve records created earlier in the same plan."""
    api = FakeNetBox()
    facade = PlanningNetBox(api)
    created = facade.dcim.devices.create(name='planned')
    assert facade.dcim.devices.get(name='planned') is created


def test_planned_creates_are_visible_to_later_executor_stages():
    """Later network planning can resolve an object created by an earlier dry-run stage."""
    api = FakeNetBox()
    facade = PlanningNetBox(api)
    created = facade.virtualization.virtual_machines.create(name='new', cluster=3)
    assert facade.virtualization.virtual_machines.get(id=created.id) is created
    assert facade.virtualization.virtual_machines.filter(cluster_id=3) == [created]
    assert api.virtualization.virtual_machines.all() == []


def test_facade_rejects_delete():
    """The dry-run surface has no delete path."""
    api = FakeNetBox()
    api.dcim.devices.add(FakeRecord(id=10, name='before'))
    facade = PlanningNetBox(api)
    try:
        facade.dcim.devices.get(id=10).delete()
    except AssertionError as exc:
        assert 'Delete is forbidden' in str(exc)
    else:
        raise AssertionError('delete unexpectedly succeeded')


def test_guarded_full_executor_records_exact_action_with_zero_real_writes(monkeypatch):
    """Planning reuses the full precheck/write ordering against only the facade."""
    api = FakeNetBox()
    facade = PlanningNetBox(api)
    events = []
    def stage(nb_api, _hosts, _target, *, confirmed=False):
        events.append('precheck' if isinstance(nb_api, PlanningNetBox) and nb_api is not facade else 'write')
        if confirmed:
            nb_api.virtualization.virtual_machines.create(name='planned', cluster=1)
    monkeypatch.setattr(netbox_full_apply, 'STAGES', (('VM', stage),))
    monkeypatch.setattr(netbox_full_apply, 'report_missing_managed_objects', lambda *_args: None)
    netbox_full_apply.apply_full_sync(facade, [], object(), confirmed=True)
    assert events == ['precheck', 'write']
    assert api.mutations == []
    assert facade.mutations[0].after['name'] == 'planned'


def test_real_proxmox_vm_executor_plans_update_without_external_write(fake_netbox):
    """The established QEMU executor runs unchanged on the recording facade."""
    _, _, cluster, target = add_target(fake_netbox)
    fake_netbox.virtualization.virtual_machines.add(FakeRecord(
        id=10, name='old-name', cluster=cluster, tenant=None, status='offline',
        vcpus=1, memory=512, disk=1024, start_on_boot='off',
        custom_fields={**vm_identity(), 'manual': 'preserved'}))
    hosts = discover_hosts(FakeProxmox(proxmox_responses()), sample_source_config())
    facade = PlanningNetBox(fake_netbox)
    apply_virtual_machines(facade, hosts, target, confirmed=True)
    assert fake_netbox.mutations == []
    assert any(mutation.operation == 'update' for mutation in facade.mutations)
    assert fake_netbox.virtualization.virtual_machines.get(id=10).name == 'old-name'


def test_real_esxi_executor_plans_managed_only_without_external_write(fake_netbox):
    """ESXi review-only objects remain untouched while managed actions are recorded."""
    hosts, managed, review = setup_esxi(fake_netbox)
    managed_before, review_before = managed.serialize(), review.serialize()
    facade = PlanningNetBox(fake_netbox)
    execute_esxi_runtime(facade, hosts, esxi_config(), confirmed=True)
    assert fake_netbox.mutations == []
    assert managed.serialize() == managed_before
    assert review.serialize() == review_before
    assert facade.mutations


def test_nested_facade_never_mutates_outer_plan_and_keeps_working_copy():
    api=FakeNetBox();api.dcim.devices.add(FakeRecord(id=10,name='original',custom_fields={}))
    outer=PlanningNetBox(api);inner=PlanningNetBox(outer)
    inner.dcim.devices.get(id=10).update({'name':'changed'})
    assert inner.dcim.devices.get(id=10).name=='changed'
    assert outer.dcim.devices.get(id=10).name=='original'
    assert not outer.mutations and not api.mutations


def test_nested_virtual_references_never_reach_http():
    """Outer host/interface plus inner dependencies retain distinct identities."""
    from tests.fakes.netbox_http import netbox_http
    from urllib.parse import parse_qs, urlsplit
    seed = FakeNetBox()
    seed.dcim.devices.add(FakeRecord(id=10, name='existing'))
    seed.dcim.interfaces.add(FakeRecord(id=20, name='existing-nic', device=10))
    requests = []
    with netbox_http(seed, requests=requests) as (api, rows, writes):
        outer = PlanningNetBox(api)
        host = outer.dcim.devices.create(name='outer-host')
        nic = outer.dcim.interfaces.create(name='eth0', device=host.id)
        inner = PlanningNetBox(outer)
        other = inner.dcim.devices.create(name='inner-host')
        assert other.id != host.id
        assert inner.dcim.devices.get(host.id).name == 'outer-host'
        assert inner.dcim.devices.get(id=other.id) is other
        assert inner.dcim.interfaces.filter(device_id=host.id)[0].id == nic.id
        child = inner.dcim.interfaces.create(name='eth1', device=host.id, parent=nic.id)
        assert {r.id for r in inner.dcim.interfaces.filter(device_id=host.id)} == {nic.id, child.id}
        assert inner.dcim.interfaces.get(parent_id=nic.id) is child
        assert inner.dcim.interfaces.filter(device_id=other.id) == []
        assert {r.id for r in inner.dcim.devices.filter(id=[10, host.id, other.id])} == {10, host.id, other.id}
        existing = inner.dcim.interfaces.get(id=20)
        assert existing.device.id == 10
        existing.name = 'renamed'
        existing.save()
        assert inner.dcim.interfaces.get(name='existing-nic') is None
        assert inner.dcim.interfaces.get(name='renamed').id == 20
        assert inner.dcim.devices.get(str(host.id)).id == host.id
        inner.dcim.interfaces.get(nic.id).update({'name': 'inner-name'})
        assert inner.dcim.interfaces.get(name='inner-name').id == nic.id
        assert outer.dcim.interfaces.get(nic.id).name == 'eth0'
        assert len(rows['dcim.devices']) == 1 and not writes
        assert requests
        for method, path in requests:
            assert method == 'GET'
            assert '/-' not in path
            assert not any(v.startswith('-') for values in parse_qs(urlsplit(path).query).values() for v in values)


def test_http_errors_and_ambiguous_matches_are_not_hidden():
    import pytest
    from pynetbox.core.query import RequestError
    from tests.fakes.netbox_http import netbox_http
    seed = FakeNetBox()
    seed.dcim.devices.add(FakeRecord(id=10, name='duplicate'))
    with netbox_http(seed) as (api, _rows, _writes):
        facade = PlanningNetBox(api)
        facade.dcim.devices.create(name='duplicate')
        with pytest.raises(ValueError, match='Multiple'):
            facade.dcim.devices.get(name='duplicate')
    with netbox_http(seed, authorize=lambda *_: False) as (api, _rows, _writes):
        with pytest.raises(RequestError):
            PlanningNetBox(PlanningNetBox(api)).dcim.devices.filter(id=10)


def test_http_fixture_records_and_rejects_virtual_reference():
    import pytest
    from pynetbox.core.query import RequestError
    from tests.fakes.netbox_http import netbox_http
    requests = []
    with netbox_http(FakeNetBox(), requests=requests) as (api, _rows, _writes):
        with pytest.raises(RequestError):
            list(api.dcim.interfaces.filter(device_id=-1))
        assert requests == [('GET', '/api/dcim/interfaces/?device_id=-1&limit=0')]


def test_snapshot_reuses_reads_but_nested_overlay_and_next_plan_stay_fresh():
    api = FakeNetBox()
    endpoint = api.virtualization.virtual_machines
    calls = []
    original = endpoint.filter
    endpoint.filter = lambda **kw: (calls.append(kw) or original(**kw))
    first = PlanningNetBox(api)
    second = PlanningNetBox(first)
    assert second.virtualization.virtual_machines.filter(cluster_id=3) == []
    created = first.virtualization.virtual_machines.create(name='planned', cluster=3)
    assert second.virtualization.virtual_machines.filter(cluster_id=3)[0].id == created.id
    assert len(calls) == 1
    endpoint.add(FakeRecord(id=42, name='concurrent', cluster=3))
    fresh = PlanningNetBox(api)
    assert fresh.virtualization.virtual_machines.filter(cluster_id=3)[0].id == 42
    assert len(calls) == 2


def test_snapshot_does_not_cache_partial_iteration_or_hide_errors():
    import pytest
    api = FakeNetBox()
    def incomplete(**kw):
        yield FakeRecord(id=1, name='partial')
        raise RuntimeError('fixture page failure')
    api.dcim.devices.filter = incomplete
    facade = PlanningNetBox(api)
    for _ in range(2):
        with pytest.raises(RuntimeError, match='fixture page failure'):
            facade.dcim.devices.filter(site_id=1)
    assert not facade.dcim.devices._reads
