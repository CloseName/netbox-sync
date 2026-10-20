"""Apply checked host contexts after caller confirmation."""


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

    created = 0
    updated = 0
    skipped = 0

    for context in contexts:
        host = context["host"]
        device_type = host_types[host.source_id]
        device = context["device"]

        if device is None:
            device = nb_api.dcim.devices.create(
                name=host.normalized_name,
                device_type=device_type.id,
                role=role.id,
                site=site.id,
                platform=platform.id,
                cluster=cluster.id,
                status="active",
                custom_fields=context["desired_custom_fields"],
            )

            created += 1

            print(f"CREATE DEVICE " f"id={device.id} " f"name={device.name}")

        else:
            changes = _device_changes(
                device,
                site=site,
                role=role,
                platform=platform,
                device_type=device_type,
                cluster=cluster,
                desired_custom_fields=context["desired_custom_fields"],
                changed_custom_fields=context["changed_custom_fields"],
            )

            if changes:
                device.update(changes)
                updated += 1

                print(f"UPDATE DEVICE " f"id={device.id} " f'fields={",".join(changes)}')
            else:
                skipped += 1

                print(f"SKIP DEVICE " f"id={device.id}")

        if not host_networking:
            continue
        interfaces = {}

        existing_interfaces = _load_existing_interfaces(
            nb_api,
            device,
        )

        for discovered in sorted(
            host.interfaces,
            key=lambda item: item.name,
        ):
            interface = existing_interfaces.get(discovered.name)

            desired_type = _desired_interface_type(discovered)

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

                created += 1

                print(f"CREATE INTERFACE " f"id={interface.id} " f"name={interface.name}")

            else:
                changes = _interface_changes(
                    interface,
                    discovered,
                )

                if changes:
                    interface.update(changes)

                    updated += 1

                    print(
                        f"UPDATE INTERFACE "
                        f"id={interface.id} "
                        f"name={interface.name} "
                        f"fields="
                        f'{",".join(changes)}'
                    )
                else:
                    skipped += 1

                    print(f"SKIP INTERFACE " f"id={interface.id} " f"name={interface.name}")

            interfaces[discovered.name] = interface

        ip_objects = {}

        for interface_name, address in context["addresses"]:
            interface = interfaces[interface_name]

            matches = _find_ip_matches(
                nb_api,
                address,
            )

            if len(matches) > 1:
                raise HostApplyError(f"IP conflict appeared " f"during apply: " f"{address}")

            if not matches:
                ip = nb_api.ipam.ip_addresses.create(
                    address=address,
                    status="active",
                    assigned_object_type=("dcim.interface"),
                    assigned_object_id=(interface.id),
                )

                created += 1

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

                    updated += 1

                    print(f"ASSIGN IP " f"id={ip.id} " f"address={address} " f"interface=" f"{interface_name}")

                elif assigned_type == "dcim.interface" and assigned_id == interface.id:
                    skipped += 1

                    print(f"SKIP IP " f"id={ip.id} " f"address={address}")

                else:
                    raise HostApplyError(
                        f"IP assignment changed "
                        f"after preflight: "
                        f"{address} -> "
                        f"{assigned_type}:"
                        f"{assigned_id}"
                    )

            ip_objects[address] = ip

        management_address = context["management_address"]

        primary_ip = ip_objects[management_address]

        current_device = nb_api.dcim.devices.get(device.id)

        current_primary = _object_id(current_device.serialize().get("primary_ip4"))

        if current_primary != primary_ip.id:
            current_device.update(
                {
                    "primary_ip4": primary_ip.id,
                }
            )

            updated += 1

            print(f"SET PRIMARY IPv4 " f"device={device.name} " f"address=" f"{management_address}")

        else:
            skipped += 1

            print(f"SKIP PRIMARY IPv4 " f"device={device.name}")

    print()
    print(f"APPLY SUMMARY " f"created={created} " f"updated={updated} " f"skipped={skipped}")
