"""Read-only planning stages preserving existing selection and output contracts."""


def prepare_host_plan_targets(nb_api, hosts, config, *, _get_required, cluster_filter):
    from .host_mapping import validate

    validate(nb_api, config, hosts)
    site = _get_required(
        nb_api.dcim.sites,
        description="site",
        slug=config.site_slug,
    )

    role = _get_required(
        nb_api.dcim.device_roles,
        description="device role",
        slug=config.device_role_slug,
    )

    platform = _get_required(
        nb_api.dcim.platforms,
        description="platform",
        slug=config.platform_slug,
    )

    from .host_mapping import device_types

    host_types = device_types(
        nb_api,
        config,
        hosts,
        lambda endpoint, description, **kw: _get_required(endpoint, description=description, **kw),
    )

    cluster_type = _get_required(
        nb_api.virtualization.cluster_types,
        description="cluster type",
        slug=config.cluster_type_slug,
    )

    cluster = None

    for candidate in nb_api.virtualization.clusters.filter(**cluster_filter(config)):
        serialized = candidate.serialize()

        if (
            serialized.get("type") == cluster_type.id
            and serialized.get("scope_type") == "dcim.site"
            and serialized.get("scope_id") == site.id
        ):
            cluster = candidate
            break

    return site, role, platform, host_types, cluster_type, cluster
