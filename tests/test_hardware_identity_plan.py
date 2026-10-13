"""Re-read provider inventory, rather than reuse one timestamped discovery object."""
from copy import deepcopy
from dataclasses import replace
import pytest
from tests.fakes import FakeNetBox, FakeProxmox
from tests.fakes.esxi import fake_esxi_service
from tests.fakes.netbox_http import netbox_http
from tests.sample_data import sample_source_config, proxmox_responses
from tests.test_first_sync import target
from tests.test_esxi_runtime import _config
from netbox_sync.application.runtime_plan import build_runtime_plan
from netbox_sync.proxmox_discovery import discover_hosts as discover_pve
from netbox_sync.esxi_discovery import discover_hosts as discover_esxi
from netbox_sync.netbox_full_apply import apply_full_sync
from netbox_sync.esxi_runtime import execute_esxi_runtime
from netbox_sync.application.planning_netbox import PlannedMutation
from netbox_sync.application.sync_plan import plan_from_mutations
from netbox_sync.plan_diagnostics import summary, differences
from tests.test_sync_plan import review


@pytest.mark.parametrize('provider', ['esxi', 'proxmox'])
@pytest.mark.parametrize('existing', [False, True])
def test_fresh_discoveries_have_same_plan_and_apply_actual_observation_time(provider, existing, monkeypatch):
    seed = FakeNetBox()
    config = target(seed, _config() if provider == 'esxi' else
                    replace(sample_source_config(), legacy_identity_owner=False))
    def discover(second):
        hosts = (discover_esxi(fake_esxi_service(), config) if provider == 'esxi' else
                 discover_pve(FakeProxmox(proxmox_responses()), config))
        hosts[0].hardware_identity['observed_at'] = f'2026-10-13T15:00:{second:02d}+00:00'
        return hosts
    def apply(api, hosts):
        if provider == 'esxi':
            execute_esxi_runtime(api, hosts, config, confirmed=True)
        else:
            apply_full_sync(api, hosts, config.target, confirmed=True)
    with netbox_http(seed) as (api, rows, writes):
        if existing:
            apply(api, discover(0))
        writes.clear()
        first = build_runtime_plan(api, discover(10), config)
        second = build_runtime_plan(api, discover(20), config)
        assert first.apply_allowed and second.apply_allowed and not writes
        assert first.digest == second.digest
        assert first.canonical_dict() == second.canonical_dict()
        before = deepcopy(rows)
        actual = discover(30)
        from netbox_sync import apply_worker
        monkeypatch.setattr('pynetbox.api', lambda *a, **kw: api)
        changed = deepcopy(actual)
        changed[0].hardware_identity['status'] = 'access_denied'
        monkeypatch.setattr(apply_worker, '_discover', lambda _: (config, changed))
        payload = dict(operation='apply', netbox_url='http://fixture', netbox_token='fixture',
                       expected_digest=first.digest, expected_summary=summary(first.canonical_dict()))
        with pytest.raises(apply_worker.ApplyWorkerError) as error:
            apply_worker.execute_child(payload)
        assert error.value.code == 'PLAN_STALE' and not writes
        monkeypatch.setattr(apply_worker, '_discover', lambda _: (config, actual))
        assert apply_worker.execute_child(payload)['status'] == 'SUCCEEDED'
        device = next(iter(rows['dcim.devices'].values()))
        assert device['custom_fields']['hardware_identity'] == actual[0].hardware_identity
        if existing:
            for endpoint in rows:
                if endpoint != 'dcim.devices':
                    assert rows[endpoint] == before[endpoint], endpoint


def test_only_desired_hardware_clock_is_excluded_from_review():
    doc = dict(version=1, source='esxi', status='collected', observed_at='2026-10-13T15:00:10+00:00',
               identifiers=[dict(kind='system_serial', value='real-serial', field='serialNumber')], conflicts=[])
    before = {'custom_fields': {'hardware_identity': dict(doc, observed_at='2026-10-12T15:00:00+00:00')}}
    after = {'custom_fields': {'hardware_identity': doc,
                              'operator_evidence': {'observed_at': 'keep-exact'}}}
    original = deepcopy(after)
    def plan(old=before, new=after, endpoint='dcim.devices'):
        return plan_from_mutations(review([]), sample_source_config(),
            [PlannedMutation('update', endpoint, 1, old, new)])
    first = plan()
    later = deepcopy(after)
    later['custom_fields']['hardware_identity']['observed_at'] = '2026-10-13T15:00:20+00:00'
    assert plan(new=later).digest == first.digest
    assert differences(summary(first.canonical_dict()), plan(new=later).canonical_dict()) == []
    assert after == original  # Canonicalization must not mutate the executor payload.
    for field, value in (('status', 'access_denied'), ('identifiers', []), ('source', 'proxmox'),
                         ('conflicts', ['system_serial']), ('version', 2)):
        changed = deepcopy(later)
        changed['custom_fields']['hardware_identity'][field] = value
        assert plan(new=changed).digest != first.digest, field
        assert 'PLANNED_ACTIONS' in differences(summary(first.canonical_dict()), plan(new=changed).canonical_dict())
    changed = deepcopy(before)
    changed['custom_fields']['hardware_identity']['observed_at'] = '2026-10-13T14:00:00+00:00'
    assert 'NETBOX_OBSERVATION' in differences(summary(first.canonical_dict()), plan(old=changed).canonical_dict())
    changed = deepcopy(after)
    changed['custom_fields']['operator_evidence']['observed_at'] = 'changed'
    assert plan(new=changed).digest != first.digest
    assert plan(endpoint='virtualization.virtual_machines', new=later).digest != plan(endpoint='virtualization.virtual_machines').digest

