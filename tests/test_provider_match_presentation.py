"""Matching explanations preserve ambiguity and avoid exposing raw inventory."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('match_presentation', Path(__file__).parents[1] / 'deploy/netbox_guard/provider_match_presentation.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_candidate_explains_evidence_without_claiming_binding():
    result = module.explain(dict(reason='identity_needs_confirmation', candidates=[dict(
        name='host', url='/dcim/devices/1/', secret='must not leak',
        evidence=dict(same_name=True, public_ips=['192.0.2.1'], observed_guest_wans=[{'vm_id': 2}]))],
        ignored_address_matches=[{'address': '10.0.0.1'}]))
    assert 'подтверждение' in result['reason']
    assert len(result['candidates'][0]['reasons']) == 3
    assert result['private_scope_unverified']
    assert result['writes_performed'] is False
    assert 'must not leak' not in str(result)


def test_cloud_task_and_unknown_reason_are_not_success():
    assert 'операция' in module.explain({'reason': 'provider_task_in_progress'})['reason']
    assert 'дополнительной проверки' in module.explain({'reason': 'unknown'})['reason']
