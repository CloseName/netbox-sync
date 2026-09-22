"""Canonical provider-neutral planning used by Web and scheduled execution."""

from .discovery_review import build_esxi_review, build_proxmox_review
from .planning_netbox import PlanningNetBox
from .sync_plan import plan_from_mutations, plan_from_review
from ..esxi_adoption import build_esxi_adoption_plan
from ..esxi_runtime import execute_esxi_runtime
from ..netbox_full_apply import apply_full_sync


def build_runtime_plan(nb_api, hosts, config):
    """Run guarded executors on a write-recording facade and return one canonical plan."""
    from .inventory_order import canonical_hosts
    hosts = canonical_hosts(hosts)
    from .sync_plan import (SyncPlan, SyncPlanItem, SyncAction, safe_source_fingerprint,
                            target_fingerprint, stable_fingerprint)
    from .ip_observations import assignment_inventory, source_policy
    _, conflicts, observations = assignment_inventory(hosts, source_policy(config))
    if conflicts:
        from dataclasses import asdict
        return SyncPlan(
            source_instance=config.source_instance, source_id=config.id,
            source_type=config.source_type, source_fingerprint=safe_source_fingerprint(config),
            target_fingerprint=target_fingerprint(config),
            provider_fingerprint=stable_fingerprint([asdict(c) for c in conflicts]),
            netbox_fingerprint=stable_fingerprint(None), conflicts=conflicts,
            items=tuple(SyncPlanItem(object_kind='source', external_id=c.value,
                name=config.name, action=SyncAction.BLOCKED, reason_code=c.kind,
                reason='Inventory conflict. Resolve the ambiguity and build a new plan.')
                for c in conflicts))
    # Reuse exact remote reads within one plan; prepare/apply reads afresh.
    nb_api = PlanningNetBox(nb_api)
    from ..host_mapping import validate
    from ..child_process import measured_phase
    with measured_phase('netbox_mapping'):
        validate(nb_api,config.target,hosts)
    with measured_phase('netbox_review'):
        review = (build_proxmox_review(nb_api, hosts, config) if config.source_type == 'proxmox'
                  else build_esxi_review(build_esxi_adoption_plan(nb_api, hosts, config), config))
    review_plan = plan_from_review(review, config)
    if not review_plan.apply_allowed:
        return review_plan
    planning_api = nb_api
    from .ip_observations import ObservationPrerequisiteError
    try:
        with measured_phase('netbox_simulation'):
            if config.source_type == 'proxmox':
                apply_full_sync(planning_api, hosts, config.target, confirmed=True)
            else:
                execute_esxi_runtime(planning_api, hosts, config, confirmed=True)
    except ObservationPrerequisiteError:
        from dataclasses import replace
        return replace(review_plan, items=(*review_plan.items, SyncPlanItem(
            object_kind='source', external_id=config.source_instance, name=config.name,
            action=SyncAction.BLOCKED, reason_code='OBSERVATION_FIELD_REQUIRED',
            reason='Prepare the network observations field in NetBox settings before synchronization.')))
    plan = plan_from_mutations(review, config, planning_api.mutations)
    if observations:
        from dataclasses import replace, asdict
        rows = tuple(SyncPlanItem(object_kind='ip_observation',
            external_id=c.value, name=c.value, action=SyncAction.UNSUPPORTED,
            reason_code='IP_OBSERVATION_ONLY',
            reason='Stored on NetBox interfaces for review; disputed IPAM assignments are not synchronized.',
            after=(('participants', [asdict(p) for p in c.participants]),)) for c in observations)
        plan = replace(plan, items=(*plan.items, *rows))
    return plan
