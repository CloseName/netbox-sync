"""Read-only bridge/VLAN reporting for a VM interface."""


def plan_interface_vlan(nic, vlans_by_vid, site, counters, *, _select_scoped):
    """Print bridge and VLAN choice, preserving warning-only failure policy."""
    print(f"        bridge=" f'{nic.bridge or "-"}')

    if nic.vlan_id is None:
        print("        vlan=-")
    else:
        vlan, vlan_state = _select_scoped(
            vlans_by_vid.get(
                nic.vlan_id,
                [],
            ),
            site.id,
        )

        if vlan_state == "match":
            print(f"        MATCH VLAN " f"id={vlan.id} " f"vid={nic.vlan_id}")
        elif vlan_state == "ambiguous":
            counters["warnings"] += 1

            print(f"        WARN VLAN " f"vid={nic.vlan_id} " f"ambiguous " f"action=not-set")
        else:
            counters["warnings"] += 1

            print(f"        WARN VLAN " f"vid={nic.vlan_id} " f"not-found " f"action=not-created")
