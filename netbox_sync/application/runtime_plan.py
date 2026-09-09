"""Canonical provider-neutral planning used by Web and scheduled execution."""

from .discovery_review import build_esxi_review, build_proxmox_review
from .planning_netbox import PlanningNetBox
from .sync_plan import plan_from_mutations, plan_from_review
from ..esxi_adoption import build_esxi_adoption_plan
from ..esxi_runtime import execute_esxi_runtime
from ..netbox_full_apply import apply_full_sync


def build_runtime_plan(nb_api, hosts, config):
    """Run guarded executors on a write-recording facade and return one canonical plan."""
    from ..host_mapping import validate
    validate(nb_api,config.target,hosts)
    review = (build_proxmox_review(nb_api, hosts, config) if config.source_type == 'proxmox'
              else build_esxi_review(build_esxi_adoption_plan(nb_api, hosts, config), config))
    review_plan = plan_from_review(review, config)
    if not review_plan.apply_allowed:
        return review_plan
    planning_api = PlanningNetBox(nb_api)
    if config.source_type == 'proxmox':
        apply_full_sync(planning_api, hosts, config.target, confirmed=True)
    else:
        execute_esxi_runtime(planning_api, hosts, config, confirmed=True)
    return plan_from_mutations(review, config, planning_api.mutations)
