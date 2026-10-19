from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS
from copy import deepcopy

import pytest
from pyVmomi import vim
from netbox_sync.esxi_events import collect_events, normalize, merge_events, apply_event_snapshots
from netbox_sync.prerequisites import definition
from netbox_sync.application.planning_netbox import PlanningNetBox
from tests.fakes import FakeRecord
from tests.test_esxi_runtime import _setup, _config

NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)


def event(key=1, **changes):
    values = dict(key=key, createdTime=NOW - timedelta(minutes=1), userName='alice',
                  vm=NS(vm=NS(_moId='vm-551'), name='example'),
                  fullFormattedMessage='PASSWORD_DO_NOT_EXPORT')
    values.update(changes)
    return make(values)


def make(values):
    obj = type('VmReconfiguredEvent', (), {})()
    obj.__dict__.update(values)
    return obj


class Collector:
    def __init__(self, latest, pages=(), fail=False):
        self.latestPage = latest
        self.pages = iter(pages)
        self.fail = fail
        self.destroyed = False
        self.calls = 0
    def SetCollectorPageSize(self, size):
        assert size == 200
    def ResetCollector(self):
        pass
    def ReadPreviousEvents(self, size):
        self.calls += 1
        if self.fail:
            raise vim.fault.NoPermission()
        return next(self.pages, [])
    def DestroyCollector(self):
        self.destroyed = True


def collect(collector):
    specs = []
    def create(spec):
        specs.append(spec)
        return collector
    data = collect_events(NS(eventManager=NS(CreateCollectorForEvents=create)),
                          vim.HostSystem('host-1'), 'source', 'host', now=NOW)
    assert specs[0].entity.entity._moId == 'host-1'
    assert specs[0].disableFullMessage
    assert collector.destroyed
    return data


def test_actor_details_and_no_private_freeform():
    spec = NS(numCPUs=4, memoryMB=8192, extraConfig=['SECRET'],
              deviceChange=[NS(operation='add', device=NS(key=3000))])
    row = normalize(event(configSpec=spec), 'source', 'host')
    assert row['actor'] == 'alice'
    assert row['changes']['numCPUs'] == 4
    assert row['changes']['devices'][0]['operation'] == 'add'
    assert 'SECRET' not in str(row) and 'PASSWORD' not in str(row)
    assert row['vm_reference'] == 'vm-551'
    assert 'uuid' not in row  # Never assign old MoRefs to a present-day VM UUID.
    assert normalize(event(userName=''), 'source', 'host')['actor_status'] == 'unknown'


def test_real_sdk_event_and_disk_change():
    obj = vim.event.VmReconfiguredEvent(
        key=42, createdTime=NOW, userName='alice',
        vm=vim.event.VmEventArgument(vm=vim.VirtualMachine('vm-551'), name='example'),
        configSpec=vim.vm.ConfigSpec(deviceChange=[vim.vm.device.VirtualDeviceSpec(
            operation='add', device=vim.vm.device.VirtualDisk(key=3000, capacityInKB=1024))]))
    row = normalize(obj, 'source', 'host')
    assert row['changes']['devices'] == [dict(operation='add', device_type='VirtualDisk',
                                             key=3000, capacity_bytes=1048576)]


def test_latest_page_is_included_and_overlap_deduplicated():
    result = collect(Collector([event(2)], [[event(2), event(1)], []]))
    assert result['status'] == 'available'
    assert len(result['events']) == 2


def test_permission_failure_does_not_export_partial_history_or_fault():
    result = collect(Collector([event()], fail=True))
    assert result == {'status': 'permission_denied', 'events': []}


def test_bounded_reads_and_partial_marker():
    collector = Collector([event(i) for i in range(200)],
                          [[event(i) for i in range(j, j+200)] for j in range(200, 1400, 200)])
    result = collect(collector)
    assert result['status'] == 'partial'
    assert len(result['events']) == 1000 and collector.calls <= 5


def test_identity_scoping_and_provider_key_reuse():
    original = normalize(event(), 'source', 'host')['event_id']
    assert original != normalize(event(), 'other', 'host')['event_id']
    assert original != normalize(event(), 'source', 'other')['event_id']
    assert original != normalize(event(createdTime=NOW), 'source', 'host')['event_id']


def test_baseline_then_new_events_preserve_dedupe_and_failure_history():
    first = dict(status='available', events=[normalize(event(), 'source', 'host')])
    baseline = merge_events(None, first, 'source', 'host')
    assert not baseline['events'][0]['alert_eligible']
    assert merge_events(baseline, first, 'source', 'host') == baseline
    second = dict(status='available', events=first['events'] + [normalize(event(2, createdTime=NOW), 'source', 'host')])
    merged = merge_events(baseline, second, 'source', 'host')
    assert sum(r['alert_eligible'] for r in merged['events']) == 1
    failed = merge_events(merged, dict(status='unavailable', events=[]), 'source', 'host')
    assert failed['events'] == merged['events']
    late = dict(status='available', events=[normalize(event(3, createdTime=NOW-timedelta(days=1)), 'source', 'host')])
    assert sum(r['alert_eligible'] for r in merge_events(merged, late, 'source', 'host')['events']) == 1
    with pytest.raises(ValueError):
        merge_events(merged, second, 'different', 'host')


def test_unavailable_first_read_does_not_enable_historical_alerts():
    previous = merge_events(None, dict(status='unavailable', events=[]), 'source', 'host')
    observed = dict(status='available', events=[normalize(event(), 'source', 'host')])
    assert not merge_events(previous, observed, 'source', 'host')['events'][0]['alert_eligible']


def test_export_dry_run_then_apply_and_repeat_noop(fake_netbox):
    hosts, _, _ = _setup(fake_netbox, review=False)
    host = hosts[0]
    host.esxi_events = dict(status='available', events=[normalize(event(), host.source_instance, host.source_id)])
    if not fake_netbox.extras.custom_fields.filter(name='esxi_events'):
        fake_netbox.extras.custom_fields.add(FakeRecord(id=900, **definition('esxi_events')))
    fake_netbox.mutations.clear()
    api = PlanningNetBox(fake_netbox)
    apply_event_snapshots(api, hosts)
    assert not fake_netbox.mutations
    apply_event_snapshots(fake_netbox, hosts)
    device = fake_netbox.dcim.devices.get(id=5)
    before = deepcopy(device.custom_fields)
    assert before['esxi_events']['events'][0]['actor'] == 'alice'
    fake_netbox.mutations.clear()
    apply_event_snapshots(fake_netbox, hosts)
    assert not fake_netbox.mutations and device.custom_fields == before


def test_missing_field_does_not_block_inventory(fake_netbox):
    hosts, _, _ = _setup(fake_netbox, review=False)
    hosts[0].esxi_events = dict(status='available', events=[])
    fake_netbox.extras.custom_fields.records[:] = [
        r for r in fake_netbox.extras.custom_fields.records if r.name != 'esxi_events']
    fake_netbox.mutations.clear()
    apply_event_snapshots(fake_netbox, hosts)
    assert not fake_netbox.mutations


def test_runtime_exports_events_inside_plan_and_apply(fake_netbox):
    from netbox_sync.esxi_runtime import execute_esxi_runtime
    hosts, _, _ = _setup(fake_netbox, review=False)
    hosts[0].esxi_events = dict(status='available', events=[normalize(event(), 'source', 'host')])
    fake_netbox.extras.custom_fields.add(FakeRecord(id=900, **definition('esxi_events')))
    fake_netbox.mutations.clear()
    execute_esxi_runtime(fake_netbox, hosts, _config(), confirmed=False)
    assert not fake_netbox.mutations
    execute_esxi_runtime(fake_netbox, hosts, _config(), confirmed=True)
    assert fake_netbox.dcim.devices.get(id=5).custom_fields['esxi_events']['initialized']
    fake_netbox.mutations.clear()
    execute_esxi_runtime(fake_netbox, hosts, _config(), confirmed=True)
    assert not fake_netbox.mutations
