"""LXC application report; preserve provider-specific behavior."""


def report_lxc_precheck(site, cluster, contexts):
    """Print LXC create/update/skip counts for already validated contexts.

    Preserve context order and sort changed field names for display. This stage
    neither writes nor decides whether a context is blocked: LXC preparation
    raises before reporting. Return None.
    """
    create_count = 0
    update_count = 0
    skip_count = 0

    print("=== LXC APPLY PRECHECK ===")

    print(f"target_site={site.name} " f"cluster={cluster.name}")

    print()

    for context in contexts:
        container = context["container"]

        existing = context["existing"]

        changes = context["changes"]

        if existing is None:
            action = "CREATE"
            create_count += 1
        elif changes:
            action = "UPDATE"
            update_count += 1
        else:
            action = "SKIP"
            skip_count += 1

        print(f"{action} LXC " f"vmid={container.vmid} " f"name=" f"{container.original_name!r}")

        if changes:
            print("  fields=" + ",".join(sorted(changes.keys())))

    print()

    print("LXC PRECHECK SUMMARY")

    print(f"  create={create_count}")

    print(f"  update={update_count}")

    print(f"  skip={skip_count}")

    print()

    print("PRECHECK PASSED")
