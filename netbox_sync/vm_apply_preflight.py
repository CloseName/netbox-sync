"""VM application preflight; preserve provider-specific behavior."""


def _validate_discovered_vms(discovered, identity_for, name_for, error):
    """Reject duplicate identities before duplicate target names or any NetBox matching."""
    # Fail before NetBox matching if the
    # source itself supplied duplicate IDs.
    identities = {}
    names = {}

    for vm in discovered:
        identity = identity_for(vm)

        identities.setdefault(
            identity,
            [],
        ).append(vm)

        names.setdefault(
            name_for(vm).casefold(),
            [],
        ).append(vm)

    duplicate_identities = {key: value for key, value in identities.items() if len(value) > 1}

    if duplicate_identities:
        details = ", ".join(sorted(duplicate_identities.keys()))

        raise error("Duplicate discovered VM " f"identities: {details}")

    duplicate_names = {key: value for key, value in names.items() if len(value) > 1}

    if duplicate_names:
        details = ", ".join(sorted(duplicate_names.keys()))

        raise error("Duplicate discovered VM " f"names in target cluster: " f"{details}")


def prepare_vm_contexts(
    nb_api, hosts, all_vms, target_vms, cluster, *, _identity, netbox_vm_name, VMApplyError, _preflight_vm, _object_id
):
    """Return discovered VMs and ordered write contexts without NetBox writes.

    Reject duplicate discovered identities and case-insensitive target names
    before matching; build contexts in node/source VM ID order. Per-VM blocked
    contexts are reported by the caller. Remove aggregate disk updates for VMs
    with native NetBox disk records, preserving their independently managed size.
    """
    discovered = []

    for host in hosts:
        discovered.extend(host.virtual_machines)

    _validate_discovered_vms(discovered, _identity, netbox_vm_name, VMApplyError)

    contexts = []

    for vm in sorted(
        discovered,
        key=lambda item: (
            item.node_source_id,
            item.vmid,
        ),
    ):
        contexts.append(
            _preflight_vm(
                all_vms,
                target_vms,
                vm,
                cluster,
            )
        )

    native_disk_parents = {
        _object_id(d.serialize().get("virtual_machine")) for d in nb_api.virtualization.virtual_disks.all()
    }
    for context in contexts:
        existing_vm = context.get("existing")
        if existing_vm is not None and existing_vm.id in native_disk_parents:
            context.get("changes", {}).pop("disk", None)

    return discovered, contexts
