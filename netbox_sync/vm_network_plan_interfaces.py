"""Interface validation and matching for the read-only VM network planner."""

from .interface_display import interface_display_name


def validate_plan_interfaces(
    discovered_vm, existing_interfaces, counters, *, validate_interface_names, _interface_match
):
    """Return whether this VM can continue after reporting name conflicts."""
    try:
        validate_interface_names(discovered_vm, existing_interfaces, _interface_match, ValueError)
    except (ValueError, RuntimeError) as exc:
        counters["interface_conflict"] += 1
        print(f"      CONFLICT INTERFACE {exc}")
        return False

    discovered_names = {}

    for nic in discovered_vm.interfaces:
        discovered_names.setdefault(
            interface_display_name(discovered_vm, nic).casefold(),
            [],
        ).append(nic)

    duplicate_source_names = [name for name, items in discovered_names.items() if len(items) > 1]

    if duplicate_source_names:
        counters["interface_conflict"] += len(duplicate_source_names)

        print("      CONFLICT " "duplicate discovered " "interface names: " + ",".join(sorted(duplicate_source_names)))

        return False

    return True


def match_plan_interface(discovered_vm, nic, existing_interfaces, counters, *, find_nic_sync_identity_matches):
    """Return (can_continue, existing_interface), preserving create versus conflict."""
    existing_matches = find_nic_sync_identity_matches(
        existing_interfaces,
        discovered_vm,
        nic,
    )

    existing_interface = None

    if len(existing_matches) > 1:
        counters["interface_conflict"] += 1

        print(
            f"      CONFLICT INTERFACE "
            f"name={interface_display_name(discovered_vm, nic)!r} "
            f"matches={len(existing_matches)}"
        )

        return False, None

    if len(existing_matches) == 1:
        existing_interface = existing_matches[0]

        counters["interface_match"] += 1

        print(
            f"      MATCH INTERFACE "
            f"id={existing_interface.id} "
            f"name={interface_display_name(discovered_vm, nic)}"
        )
    else:
        counters["interface_create"] += 1

        print(f"      CREATE INTERFACE " f"name={interface_display_name(discovered_vm, nic)}")

    return True, existing_interface
