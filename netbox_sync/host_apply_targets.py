"""Resolve prerequisites and explicit mappings before host preflight."""

from dataclasses import dataclass


@dataclass(frozen=True)
class HostApplyTargets:
    """Resolved original NetBox records and per-host device types."""

    site: object
    role: object
    platform: object
    host_types: dict
    cluster: object


def prepare_host_apply_targets(nb_api, hosts, config, *, _required, _resolve_cluster):
    """Preserve prerequisite lookup order and propagate failures before writes."""
    from .host_mapping import validate, selected, device_types

    validate(nb_api, config, hosts)
    site = _required(
        nb_api.dcim.sites,
        "site",
        **selected(config, "site", config.site_slug),
    )

    role = _required(
        nb_api.dcim.device_roles,
        "device role",
        **selected(config, "device_role", config.device_role_slug),
    )

    platform = _required(
        nb_api.dcim.platforms,
        "platform",
        **selected(config, "platform", config.platform_slug),
    )

    host_types = device_types(nb_api, config, hosts, _required)

    cluster_type = _required(
        nb_api.virtualization.cluster_types,
        "cluster type",
        **selected(config, "cluster_type", config.cluster_type_slug),
    )

    cluster = _resolve_cluster(
        nb_api,
        site,
        cluster_type,
        config.cluster_name,
        getattr(config, "onboarding_mapping", {}).get("references", {}).get("cluster", {}).get("id"),
    )

    return HostApplyTargets(
        site=site,
        role=role,
        platform=platform,
        host_types=host_types,
        cluster=cluster,
    )
