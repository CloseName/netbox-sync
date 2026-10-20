"""Prepare LXC targets and derive cluster membership from the global inventory."""
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LXCApplyInventory:
    """Original records and ordered global and target VM selections."""
    site: Any
    cluster: Any
    all_vms: list
    target_vms: list


def prepare_lxc_apply_inventory(nb_api, config, *, cluster_filter, LXCApplyError):
    """Preserve LXC-specific scope checks, reads and membership semantics."""
    site = nb_api.dcim.sites.get(
        slug=config.site_slug
    )

    if site is None:
        raise LXCApplyError(
            'Target site not found'
        )

    clusters = list(
        nb_api.virtualization.clusters.filter(
            **cluster_filter(config)
        )
    )

    target_clusters = []

    for cluster in clusters:
        data = cluster.serialize()

        if (
            data.get('scope_type')
            == 'dcim.site'
            and data.get(
                'scope_id'
            ) == site.id
        ):
            target_clusters.append(
                cluster
            )

    if len(target_clusters) != 1:
        raise LXCApplyError(
            'Expected exactly one '
            'target cluster'
        )

    cluster = target_clusters[0]

    all_vms = list(
        nb_api.virtualization
        .virtual_machines
        .all()
    )

    target_vms = [
        vm
        for vm in all_vms
        if (
            getattr(
                getattr(
                    vm,
                    'cluster',
                    None,
                ),
                'id',
                None,
            )
            == cluster.id
        )
    ]

    return LXCApplyInventory(site, cluster, all_vms, target_vms)
