"""Primary IPv4 selection for the legacy read-only VM network planner."""


def plan_primary_ipv4(netbox_vm, discovered_ipv4, ips_by_id, counters, *, _existing_primary_ipv4):
    """Print the original primary decision and update only the plan counter."""
    unique_ipv4 = sorted(set(discovered_ipv4))

    current_primary = _existing_primary_ipv4(
        netbox_vm,
        ips_by_id,
    )

    if len(unique_ipv4) == 1:
        candidate = unique_ipv4[0]

        if current_primary == candidate:
            print(f"      KEEP PRIMARY IPv4 " f"{candidate}")
        else:
            counters["primary_set"] += 1

            print(f"      SET PRIMARY IPv4 " f"{candidate}")

    elif not unique_ipv4:
        print("      PRIMARY IPv4 " "action=unchanged " "reason=no-discovered-address")

    else:
        print("      PRIMARY IPv4 " "action=unchanged " "reason=ambiguous " f"candidates=" + ",".join(unique_ipv4))
