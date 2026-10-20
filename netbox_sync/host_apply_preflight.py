"""Read-only host checks before the whole batch is allowed to write."""


def prepare_host_context(
    nb_api,
    host,
    site,
    *,
    host_networking=True,
    _resolve_device,
    _managed_metadata,
    _load_existing_interfaces,
    _management_binding,
    _canonical_address,
    _find_ip_matches,
    HostApplyError,
):
    """Resolve host ownership and validate all enabled network bindings before writes."""

    device, match_reason = _resolve_device(
        nb_api,
        host,
        site,
    )

    if not host_networking:
        desired, changed = _managed_metadata(host, device)
        return {
            "host": host,
            "device": device,
            "match_reason": match_reason,
            "interfaces": {},
            "management_interface": None,
            "management_address": None,
            "addresses": [],
            "desired_custom_fields": desired,
            "changed_custom_fields": changed,
        }

    existing_interfaces = _load_existing_interfaces(
        nb_api,
        device,
    )

    discovered_names = [interface.name for interface in host.interfaces]

    if len(discovered_names) != len(set(discovered_names)):
        raise HostApplyError(f"Duplicate discovered interface " f"name on {host.normalized_name}")

    (
        management_interface,
        management_address,
    ) = _management_binding(host)

    addresses = []

    for interface in host.interfaces:
        expected_interface = existing_interfaces.get(interface.name)

        for raw_address in interface.addresses:
            address = _canonical_address(raw_address)

            matches = _find_ip_matches(
                nb_api,
                address,
            )

            if len(matches) > 1:
                raise HostApplyError(f"IP conflict: {address} " f"matches={len(matches)}")

            if len(matches) == 1:
                ip = matches[0]
                data = ip.serialize()

                assigned_type = data.get("assigned_object_type")

                assigned_id = data.get("assigned_object_id")

                if assigned_type is None and assigned_id is None:
                    pass

                elif (
                    expected_interface is not None
                    and assigned_type == "dcim.interface"
                    and assigned_id == expected_interface.id
                ):
                    pass

                else:
                    raise HostApplyError(
                        f"IP {address} is already " f"assigned to " f"{assigned_type}:" f"{assigned_id}"
                    )

            addresses.append(
                (
                    interface.name,
                    address,
                )
            )

    (
        desired_custom_fields,
        changed_custom_fields,
    ) = _managed_metadata(
        host,
        device,
    )

    return {
        "host": host,
        "device": device,
        "match_reason": match_reason,
        "interfaces": existing_interfaces,
        "management_interface": management_interface,
        "management_address": management_address,
        "addresses": addresses,
        "desired_custom_fields": desired_custom_fields,
        "changed_custom_fields": changed_custom_fields,
    }
