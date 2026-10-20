"""Apply checked host contexts after caller confirmation."""

from typing import Any, Callable, NamedTuple


class _HostTargets(NamedTuple):
    """Already-resolved placement and the existing host-networking switch."""

    site: Any
    role: Any
    platform: Any
    cluster: Any
    host_types: dict
    networking: bool


class _HostOperations(NamedTuple):
    """Legacy-injected operations retained by the public write entry point."""

    device_changes: Callable
    load_interfaces: Callable
    interface_type: Callable
    interface_changes: Callable
    find_ips: Callable
    object_id: Callable
    error: type[Exception]


def _write_device(nb_api, context, targets, operations, counts):
    """Create or update the checked host device and return its original source context."""
    host = context["host"]
    device_type = targets.host_types[host.source_id]
    device = context["device"]

    if device is None:
        device = nb_api.dcim.devices.create(
            name=host.normalized_name,
            device_type=device_type.id,
            role=targets.role.id,
            site=targets.site.id,
            platform=targets.platform.id,
            cluster=targets.cluster.id,
            status="active",
            custom_fields=context["desired_custom_fields"],
        )

        counts["created"] += 1

        print(f"CREATE DEVICE " f"id={device.id} " f"name={device.name}")

    else:
        changes = operations.device_changes(
            device,
            site=targets.site,
            role=targets.role,
            platform=targets.platform,
            device_type=device_type,
            cluster=targets.cluster,
            desired_custom_fields=context["desired_custom_fields"],
            changed_custom_fields=context["changed_custom_fields"],
        )

        if changes:
            device.update(changes)
            counts["updated"] += 1

            print(f"UPDATE DEVICE " f"id={device.id} " f'fields={",".join(changes)}')
        else:
            counts["skipped"] += 1

            print(f"SKIP DEVICE " f"id={device.id}")

    return device, host


def _write_interfaces(nb_api, host, device, operations, counts):
    """Reload and write host interfaces in sorted source-name order."""
    interfaces = {}

    existing_interfaces = operations.load_interfaces(
        nb_api,
        device,
    )

    for discovered in sorted(
        host.interfaces,
        key=lambda item: item.name,
    ):
        interface = existing_interfaces.get(discovered.name)

        desired_type = operations.interface_type(discovered)

        if interface is None:
            payload = {
                "device": device.id,
                "name": discovered.name,
                "type": desired_type,
                "enabled": bool(discovered.autostart),
            }

            if discovered.comments is not None:
                payload["description"] = discovered.comments

            interface = nb_api.dcim.interfaces.create(**payload)

            counts["created"] += 1

            print(f"CREATE INTERFACE " f"id={interface.id} " f"name={interface.name}")

        else:
            changes = operations.interface_changes(
                interface,
                discovered,
            )

            if changes:
                interface.update(changes)

                counts["updated"] += 1

                print(
                    f"UPDATE INTERFACE "
                    f"id={interface.id} "
                    f"name={interface.name} "
                    f"fields="
                    f'{",".join(changes)}'
                )
            else:
                counts["skipped"] += 1

                print(f"SKIP INTERFACE " f"id={interface.id} " f"name={interface.name}")

        interfaces[discovered.name] = interface

    return interfaces


def _write_addresses(nb_api, context, interfaces, operations, counts):
    """Recheck each address immediately before writing its interface assignment."""
    ip_objects = {}

    for interface_name, address in context["addresses"]:
        interface = interfaces[interface_name]

        matches = operations.find_ips(
            nb_api,
            address,
        )

        if len(matches) > 1:
            raise operations.error(f"IP conflict appeared " f"during apply: " f"{address}")

        if not matches:
            ip = nb_api.ipam.ip_addresses.create(
                address=address,
                status="active",
                assigned_object_type=("dcim.interface"),
                assigned_object_id=(interface.id),
            )

            counts["created"] += 1

            print(f"CREATE IP " f"id={ip.id} " f"address={address} " f"interface=" f"{interface_name}")

        else:
            ip = matches[0]
            data = ip.serialize()

            assigned_type = data.get("assigned_object_type")
            assigned_id = data.get("assigned_object_id")

            if assigned_type is None and assigned_id is None:
                ip.update(
                    {
                        "assigned_object_type": "dcim.interface",
                        "assigned_object_id": interface.id,
                    }
                )

                counts["updated"] += 1

                print(f"ASSIGN IP " f"id={ip.id} " f"address={address} " f"interface=" f"{interface_name}")

            elif assigned_type == "dcim.interface" and assigned_id == interface.id:
                counts["skipped"] += 1

                print(f"SKIP IP " f"id={ip.id} " f"address={address}")

            else:
                raise operations.error(
                    f"IP assignment changed " f"after preflight: " f"{address} -> " f"{assigned_type}:" f"{assigned_id}"
                )

        ip_objects[address] = ip

    return ip_objects


def _write_host(nb_api, context, targets, operations, counts):
    """Write one host completely before proceeding to the next checked context."""
    device, host = _write_device(nb_api, context, targets, operations, counts)
    if not targets.networking:
        return
    interfaces = _write_interfaces(nb_api, host, device, operations, counts)
    ip_objects = _write_addresses(nb_api, context, interfaces, operations, counts)
    management_address = context["management_address"]

    primary_ip = ip_objects[management_address]

    current_device = nb_api.dcim.devices.get(device.id)

    current_primary = operations.object_id(current_device.serialize().get("primary_ip4"))

    if current_primary != primary_ip.id:
        current_device.update(
            {
                "primary_ip4": primary_ip.id,
            }
        )

        counts["updated"] += 1

        print(f"SET PRIMARY IPv4 " f"device={device.name} " f"address=" f"{management_address}")

    else:
        counts["skipped"] += 1

        print(f"SKIP PRIMARY IPv4 " f"device={device.name}")


def write_hosts(
    nb_api,
    contexts,
    site,
    role,
    platform,
    cluster,
    host_types,
    *,
    host_networking,
    _device_changes,
    _load_existing_interfaces,
    _desired_interface_type,
    _interface_changes,
    _find_ip_matches,
    _object_id,
    HostApplyError,
):
    """Preserve mutation order, late IP checks and operation reporting."""
    print()
    print("=== HOST APPLY ===")

    counts = dict.fromkeys(("created", "updated", "skipped"), 0)

    targets = _HostTargets(site, role, platform, cluster, host_types, host_networking)
    operations = _HostOperations(
        _device_changes,
        _load_existing_interfaces,
        _desired_interface_type,
        _interface_changes,
        _find_ip_matches,
        _object_id,
        HostApplyError,
    )
    for context in contexts:
        _write_host(nb_api, context, targets, operations, counts)

    print()
    print(
        f"APPLY SUMMARY " f"created={counts['created']} " f"updated={counts['updated']} " f"skipped={counts['skipped']}"
    )
