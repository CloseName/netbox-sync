"""LXC application writes; preserve provider-specific behavior."""


def write_lxc_containers(nb_api, contexts):
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
