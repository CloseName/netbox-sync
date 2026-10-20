"""Write previously validated VM network contexts in their original order."""

from .interface_display import interface_display_name
from .vm_network_preflight import (
    _assigned_object,
    _current_primary_mac_id,
    _current_primary_ip_id,
)


def _write_interface(nb_api, nic_context, vm, netbox_vm, counts):
    """Create or update one VM interface and retain the original output and counters."""
    nic = nic_context["source"]
    interface = nic_context["existing"]

    if interface is None:
        interface = nb_api.virtualization.interfaces.create(
            virtual_machine=(netbox_vm.id),
            name=interface_display_name(vm, nic),
            enabled=True,
            custom_fields=(nic_context["desired_custom_fields"]),
        )

        counts["created_interfaces"] += 1

        print(
            f"CREATE INTERFACE "
            f"id={interface.id} "
            f"vm={netbox_vm.name!r} "
            f"name={interface_display_name(vm, nic)}"
        )

    elif nic_context["interface_changes"]:
        interface.update(nic_context["interface_changes"])

        counts["updated_interfaces"] += 1

        print(f"UPDATE INTERFACE " f"id={interface.id} " f"name={interface_display_name(vm, nic)}")
    else:
        counts["skipped"] += 1

    return interface


def _write_mac(nb_api, nic_context, interface, counts):
    """Create or assign the checked MAC, then update the interface primary MAC."""
    mac_value = nic_context["mac_value"]

    if mac_value:
        mac = nic_context["existing_mac"]

        if mac is None:
            mac = nb_api.dcim.mac_addresses.create(
                mac_address=(mac_value),
                assigned_object_type=("virtualization." "vminterface"),
                assigned_object_id=(interface.id),
            )

            counts["created_macs"] += 1

            print(f"CREATE MAC " f"id={mac.id} " f"{mac_value}")

        else:
            (
                assigned_type,
                assigned_id,
            ) = _assigned_object(mac)

            if assigned_type is None and assigned_id is None:
                mac.update(
                    {
                        "assigned_object_type": "virtualization." "vminterface",
                        "assigned_object_id": interface.id,
                    }
                )

                counts["updated_macs"] += 1

                print(f"ASSIGN MAC " f"id={mac.id} " f"{mac_value}")
            else:
                counts["skipped"] += 1

        primary_mac_id = _current_primary_mac_id(interface)

        if primary_mac_id != mac.id:
            interface.update(
                {
                    "primary_mac_address": mac.id,
                }
            )

            counts["updated_interfaces"] += 1

            print(f"SET PRIMARY MAC " f"interface={interface.id} " f"mac={mac.id}")
        else:
            counts["skipped"] += 1


def _write_ip(nb_api, ip_context, interface, counts):
    """Create or assign one checked IP while preserving its VRF and failure boundary."""
    address = ip_context["address"]

    ip = ip_context["existing"]

    if ip is None:
        ip = nb_api.ipam.ip_addresses.create(
            address=address,
            **({"vrf": ip_context["vrf_id"]} if ip_context["vrf_id"] is not None else {}),
            status="active",
            assigned_object_type=("virtualization." "vminterface"),
            assigned_object_id=(interface.id),
        )

        counts["created_ips"] += 1

        print(f"CREATE IP " f"id={ip.id} " f"address={address}")

    else:
        (
            assigned_type,
            assigned_id,
        ) = _assigned_object(ip)

        if assigned_type is None and assigned_id is None:
            ip.update(
                {
                    "assigned_object_type": "virtualization." "vminterface",
                    "assigned_object_id": interface.id,
                }
            )

            counts["updated_ips"] += 1

            print(f"ASSIGN IP " f"id={ip.id} " f"address={address}")
        else:
            counts["skipped"] += 1

    return ip


def _write_primary(context, applied_ips, netbox_vm, counts):
    """Apply the existing VM primary IPv4 policy after all interface writes."""
    candidate = context["primary_candidate"]

    if candidate is not None and candidate in applied_ips and context["primary_action"] != "preserve_manual":
        ip = applied_ips[candidate]

        current_primary = _current_primary_ip_id(netbox_vm)

        if current_primary != ip.id:
            netbox_vm.update(
                {
                    "primary_ip4": ip.id,
                }
            )

            counts["updated_primary"] += 1

            print(f"SET PRIMARY IPv4 " f"vm={netbox_vm.name!r} " f"address={candidate}")
        else:
            counts["skipped"] += 1


def write_vm_networks(nb_api, contexts):
    """Apply checked contexts and report results; caller owns confirmation."""
    print()
    print("=== VM NETWORK APPLY ===")

    counts = dict.fromkeys(
        (
            "created_interfaces",
            "updated_interfaces",
            "created_macs",
            "updated_macs",
            "created_ips",
            "updated_ips",
            "updated_primary",
            "skipped",
        ),
        0,
    )

    for context in contexts:
        vm = context["source_vm"]
        netbox_vm = context["netbox_vm"]
        applied_ips = {}

        for nic_context in context["nics"]:
            interface = _write_interface(nb_api, nic_context, vm, netbox_vm, counts)

            _write_mac(nb_api, nic_context, interface, counts)

            for ip_context in nic_context["ips"]:
                applied_ips[ip_context["key"]] = _write_ip(nb_api, ip_context, interface, counts)

        _write_primary(context, applied_ips, netbox_vm, counts)

    print()
    print("VM NETWORK APPLY SUMMARY")
    print(f"  interfaces_created=" f"{counts['created_interfaces']}")
    print(f"  interfaces_updated=" f"{counts['updated_interfaces']}")
    print(f"  macs_created={counts['created_macs']}")
    print(f"  macs_updated={counts['updated_macs']}")
    print(f"  ips_created={counts['created_ips']}")
    print(f"  ips_updated={counts['updated_ips']}")
    print(f"  primary_updated=" f"{counts['updated_primary']}")
    print(f"  skipped={counts['skipped']}")
