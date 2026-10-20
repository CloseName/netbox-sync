"""LXC application preflight; preserve provider-specific behavior."""


def prepare_lxc_contexts(
    hosts, all_vms, target_vms, cluster, *, _find_identity_matches, _desired_fields, _changes, LXCApplyError
):
    contexts = []

    discovered_ids = set()

    for host in hosts:
        for container in host.containers:
            source_id = str(container.source_id)

            if source_id in discovered_ids:
                raise LXCApplyError(f"Duplicate discovered " f"LXC identity: " f"{source_id}")

            discovered_ids.add(source_id)

            identity_matches = _find_identity_matches(
                all_vms,
                container,
            )

            if len(identity_matches) > 1:
                raise LXCApplyError(f"Duplicate NetBox " f"LXC identity: " f"{source_id}")

            existing = None

            if len(identity_matches) == 1:
                existing = identity_matches[0]

                existing_cluster = getattr(
                    getattr(
                        existing,
                        "cluster",
                        None,
                    ),
                    "id",
                    None,
                )

                if existing_cluster != cluster.id:
                    raise LXCApplyError(f"LXC identity " f"{source_id} exists " f"outside target cluster")

            else:
                name_matches = [vm for vm in target_vms if (vm.name.casefold() == container.original_name.casefold())]

                if name_matches:
                    raise LXCApplyError(
                        f"LXC adoption candidate " f"exists without " f"sync identity: " f"{container.original_name!r}"
                    )

            desired = _desired_fields(
                container,
                cluster,
                existing,
            )

            changes = {}

            if existing is not None:
                changes = _changes(
                    existing,
                    desired,
                )

            contexts.append(
                {
                    "container": container,
                    "existing": existing,
                    "desired": desired,
                    "changes": changes,
                }
            )

    return contexts
