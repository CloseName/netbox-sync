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
