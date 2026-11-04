import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('automation', Path(__file__).parents[1] / 'deploy/netbox_guard/provider_automation.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_region_fallback_is_explicit_and_not_retained_or_failed():
    snapshot = dict(identity=dict(kind='cloud_vm', region='ru-9'), sections={
        'resource': dict(status='collected', data={'status': 'SHELVED_OFFLOADED'}),
        'placement': dict(status='not_reported', data={})})
    assert module.placement(snapshot) == ('region:ru-9', 'ru-9 — зона не указана', True)
    snapshot['sections']['placement']['retained'] = True
    assert module.placement(snapshot) is None
    snapshot['sections']['placement'] = dict(status='access_denied', data={})
    assert module.placement(snapshot) is None


def test_automatic_candidates_refuse_conflicts_names_alone_and_bound_targets():
    target = dict(resource='device', id=1, evidence=dict(public_ips=['94.26.228.220']))
    plan = dict(resource='device', candidates=[target])
    assert module.candidate(plan, set()) == 1
    assert module.candidate(plan, {('device', 1)}) is None
    plan['candidates'].append(dict(resource='vm', id=2, host_device_id=1, evidence={}))
    assert module.candidate(plan, set()) == 1
    plan['candidates'][1]['host_device_id'] = 3
    assert module.candidate(plan, set()) is None
    plan['candidates'] = [dict(resource='device', id=1, evidence=dict(same_name=True))]
    assert module.candidate(plan, set()) is None
