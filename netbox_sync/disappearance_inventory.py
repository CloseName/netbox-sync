"""Read-only planning stages preserving existing selection and output contracts."""


def resolve_disappearance_target(nb_api, config, *, cluster_filter):
    site = nb_api.dcim.sites.get(slug=config.site_slug)

    if site is None:
        raise RuntimeError("Target site not found")

    clusters = list(nb_api.virtualization.clusters.filter(**cluster_filter(config)))

    clusters = [
        cluster
        for cluster in clusters
        if (cluster.serialize().get("scope_type") == "dcim.site" and cluster.serialize().get("scope_id") == site.id)
    ]

    if len(clusters) != 1:
        raise RuntimeError("Expected exactly one " "target cluster")

    cluster = clusters[0]

    return site, cluster


def load_disappearance_inventory(nb_api, cluster, *, _object_id):
    target_vms = list(nb_api.virtualization.virtual_machines.filter(cluster_id=cluster.id))

    all_interfaces = list(nb_api.virtualization.interfaces.all())

    interfaces_by_vm = {}

    for interface in all_interfaces:
        vm_id = _object_id(interface.serialize().get("virtual_machine"))

        if vm_id is not None:
            interfaces_by_vm.setdefault(
                vm_id,
                [],
            ).append(interface)

    return target_vms, interfaces_by_vm
