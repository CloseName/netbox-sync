"""LXC application writes; preserve provider-specific behavior."""


def write_lxc_containers(nb_api, contexts):
    """Write validated LXC contexts after the caller has confirmed the operation.

    Preserve context order, create with the prepared desired fields and update
    only nonempty changes. Count unchanged containers without per-item skip
    output. Propagate write failures without rollback or a final summary; earlier
    successful writes remain. Return None.
    """
    created = 0
    updated = 0
    skipped = 0

    print()
    print("=== LXC APPLY ===")

    for context in contexts:
        container = context["container"]

        existing = context["existing"]

        desired = context["desired"]

        changes = context["changes"]

        if existing is None:
            vm = nb_api.virtualization.virtual_machines.create(**desired)

            created += 1

            print(f"CREATE LXC " f"id={vm.id} " f"vmid={container.vmid} " f"name={vm.name!r}")

        elif changes:
            existing.update(changes)

            updated += 1

            print(f"UPDATE LXC " f"id={existing.id} " f"vmid={container.vmid} " f"name={existing.name!r}")

        else:
            skipped += 1

    print()

    print("LXC APPLY SUMMARY")

    print(f"  created={created}")

    print(f"  updated={updated}")

    print(f"  skipped={skipped}")
