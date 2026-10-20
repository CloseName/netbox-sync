"""VM application writes; preserve provider-specific behavior."""


def write_virtual_machines(nb_api, cluster, contexts, *, build_vm_create_fields):
    print()
    print("=== VM APPLY ===")

    created = 0
    updated = 0
    skipped = 0

    for context in contexts:
        vm = context["vm"]
        existing = context.get("existing")

        if context["action"] == "create":
            created_vm = nb_api.virtualization.virtual_machines.create(
                **build_vm_create_fields(
                    vm,
                    cluster,
                    context["desired_custom_fields"],
                )
            )

            created += 1

            print(f"CREATE VM " f"id={created_vm.id} " f"vmid={vm.vmid} " f"name={created_vm.name!r}")

            continue

        changes = context["changes"]

        if changes:
            existing.update(changes)
            updated += 1

            print(f"UPDATE VM " f"id={existing.id} " f"vmid={vm.vmid} " f"fields=" f'{",".join(changes)}')
        else:
            skipped += 1

            print(f"SKIP VM " f"id={existing.id} " f"vmid={vm.vmid} " f"name={existing.name!r}")

    print()
    print(f"VM APPLY SUMMARY " f"created={created} " f"updated={updated} " f"skipped={skipped}")
