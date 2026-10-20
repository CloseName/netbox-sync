"""Plan a single LXC without applying adoption or conflict decisions."""


def plan_lxc_container(
    container,
    existing_vms,
    cluster,
    counters,
    *,
    find_lxc_sync_identity_matches,
    print_desired_lxc,
    lxc_identity_source_id,
    _status,
    _disk_mib,
    build_lxc_custom_fields,
    MANAGED_LXC_CUSTOM_FIELDS,
    json,
):
    """Report one container identity or adoption decision and update plan counters."""

    identity_matches = find_lxc_sync_identity_matches(
        existing_vms,
        container,
    )

    if len(identity_matches) > 1:
        counters["conflict"] += 1

        print(
            f"    CONFLICT LXC "
            f"vmid={container.vmid} "
            f"name={container.original_name!r} "
            f"reason=duplicate_identity"
        )

        return

    existing = None

    if len(identity_matches) == 1:
        existing = identity_matches[0]

        counters["match"] += 1

        print(
            f"    MATCH LXC "
            f"id={existing.id} "
            f"vmid={container.vmid} "
            f"name={container.original_name!r} "
            f"reason=sync_identity"
        )

    else:
        name_matches = [
            candidate
            for candidate in existing_vms
            if (
                candidate.name.casefold() == container.original_name.casefold()
                and getattr(
                    candidate,
                    "tenant",
                    None,
                )
                is None
            )
        ]

        if len(name_matches) > 1:
            counters["conflict"] += 1

            print(
                f"    CONFLICT LXC "
                f"vmid={container.vmid} "
                f"name={container.original_name!r} "
                f"reason=duplicate_name"
            )

            return

        if len(name_matches) == 1:
            counters["adopt_candidate"] += 1

            print(
                f"    ADOPT CANDIDATE "
                f"LXC vmid="
                f"{container.vmid} "
                f"name="
                f"{container.original_name!r} "
                f"action=not-adopted"
            )

            existing = name_matches[0]
        else:
            counters["create"] += 1

            print(f"    CREATE LXC " f"vmid={container.vmid} " f"name=" f"{container.original_name!r}")

    print_desired_lxc(
        container,
        cluster,
        existing,
        lxc_identity_source_id=lxc_identity_source_id,
        _status=_status,
        _disk_mib=_disk_mib,
        build_lxc_custom_fields=build_lxc_custom_fields,
        MANAGED_LXC_CUSTOM_FIELDS=MANAGED_LXC_CUSTOM_FIELDS,
        json=json,
    )
