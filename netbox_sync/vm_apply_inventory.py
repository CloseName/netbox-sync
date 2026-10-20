"""Resolve VM apply targets and retain independent NetBox inventories."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VMApplyInventory:
    """Original target records and eagerly loaded VM selections."""

    site: Any
    cluster: Any
    all_vms: list
    target_vms: list


def prepare_vm_apply_inventory(nb_api, config, *, _required, _resolve_cluster):
    """Read prerequisites and VM selections in the established order."""
    site = _required(
        nb_api.dcim.sites,
        "site",
        slug=config.site_slug,
    )

    cluster_type = _required(
        nb_api.virtualization.cluster_types,
        "cluster type",
        slug=config.cluster_type_slug,
    )

    cluster = _resolve_cluster(
        nb_api,
        site,
        cluster_type,
        config.cluster_name,
        getattr(config, "onboarding_mapping", {}).get("references", {}).get("cluster", {}).get("id"),
    )

    all_vms = list(nb_api.virtualization.virtual_machines.all())

    target_vms = list(nb_api.virtualization.virtual_machines.filter(cluster_id=cluster.id))

    return VMApplyInventory(site, cluster, all_vms, target_vms)
