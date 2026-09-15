"""WEB-5A canonical plan and safety contract."""

from dataclasses import replace

from netbox_sync.application.discovery_review import (DiscoveryReview, ReviewClassification,
                                                            ReviewItem)
from netbox_sync.application.sync_plan import (SyncAction, plan_from_mutations, plan_from_review,
                                                    safe_source_fingerprint)
from tests.sample_data import sample_source_config


def review(items):
    return DiscoveryReview('pve-infra-test', 'proxmox', 'test-site', 'Test Cluster', tuple(items))


def item(external_id, classification=ReviewClassification.MANAGED, matched=1):
    return ReviewItem('qemu', f'vm-{external_id}', external_id, classification, 'TEST',
                      'Safe test evidence.', 'none', matched, f'old-{external_id}')


def test_canonical_plan_is_order_independent_and_deterministic():
    config = sample_source_config()
    first = plan_from_review(review([item('2'), item('1')]), config)
    second = plan_from_review(review([item('1'), item('2')]), config)
    assert first.digest == second.digest
    assert first.canonical_json() == second.canonical_json()


def test_relevant_state_changes_digest_but_credentials_do_not_leak():
    config = sample_source_config()
    plan = plan_from_review(review([item('1')]), config)
    changed = plan_from_review(review([item('1', matched=2)]), config)
    assert changed.digest != plan.digest
    serialized = plan.canonical_json()
    assert 'token_id' not in serialized
    assert 'token_secret' not in serialized
    assert '/run/secrets' not in serialized
    assert safe_source_fingerprint(replace(config, address='new-endpoint')) != plan.source_fingerprint


def test_review_is_isolated_while_conflict_blocks_entire_plan():
    config = sample_source_config()
    review_only = plan_from_review(review([
        item('1'), item('2', ReviewClassification.REVIEW_REQUIRED, None)]), config)
    blocked = plan_from_review(review([
        item('1'), item('2', ReviewClassification.CONFLICT, None)]), config)
    assert review_only.apply_allowed
    assert review_only.items[1].action is SyncAction.REVIEW_REQUIRED
    assert not blocked.apply_allowed


def test_plan_projection_is_read_only():
    config = sample_source_config()
    result = plan_from_review(review([item('1')]), config)
    assert result.items[0].action is SyncAction.NO_CHANGE


def test_executor_plan_explicitly_binds_retain_only_disappearance_policy():
    """No-delete disappearance handling is visible and part of the digest."""
    config = sample_source_config()
    plan = plan_from_mutations(review([item('1')]), config, ())
    assert any(value.action is SyncAction.RETAIN_ONLY for value in plan.items)
    assert 'DISAPPEARANCE_RETAIN_ONLY' in plan.canonical_json()


def test_unexecuted_discovery_create_is_explicitly_unsupported():
    config = sample_source_config()
    plan = plan_from_mutations(review([item('new', ReviewClassification.WOULD_CREATE, None)]), config, ())
    unresolved = [row for row in plan.items if row.external_id == 'new']
    assert len(unresolved) == 1
    assert unresolved[0].action is SyncAction.UNSUPPORTED
    assert unresolved[0].reason_code == 'EXECUTOR_CREATE_UNSUPPORTED'
