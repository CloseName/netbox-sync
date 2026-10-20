"""Read-only MAC planning; conflicts are reported without aborting IP planning."""


def plan_interface_mac(nic, existing_interface, macs_by_address, counters, *, _canonical_mac, _assigned_object):
    """Print the existing MAC decision and increment its planner counter."""
    mac_value = _canonical_mac(nic.mac_address)

    if mac_value:
        mac_matches = macs_by_address.get(
            mac_value,
            [],
        )

        if len(mac_matches) > 1:
            counters["mac_conflict"] += 1

            print(f"        CONFLICT MAC " f"{mac_value} " f"matches=" f"{len(mac_matches)}")

        elif len(mac_matches) == 1:
            mac = mac_matches[0]

            (
                assigned_type,
                assigned_id,
            ) = _assigned_object(mac)

            allowed = assigned_type is None and assigned_id is None

            if (
                existing_interface is not None
                and assigned_type == "virtualization.vminterface"
                and assigned_id == existing_interface.id
            ):
                allowed = True

            if allowed:
                counters["mac_match"] += 1

                print(f"        MATCH MAC " f"id={mac.id} " f"{mac_value}")
            else:
                counters["mac_conflict"] += 1

                print(
                    f"        CONFLICT MAC "
                    f"id={mac.id} "
                    f"{mac_value} "
                    f"assigned="
                    f"{assigned_type}:"
                    f"{assigned_id}"
                )
        else:
            counters["mac_create"] += 1

            print(f"        CREATE MAC " f"{mac_value}")
