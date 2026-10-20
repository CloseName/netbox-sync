"""Desired LXC plan details; independent of apply-time policies."""


def print_desired_lxc(
    container,
    cluster,
    existing,
    *,
    lxc_identity_source_id,
    _status,
    _disk_mib,
    build_lxc_custom_fields,
    MANAGED_LXC_CUSTOM_FIELDS,
    json,
):
    print(f"      identity=" f"{container.source}:" f"{lxc_identity_source_id(container)}")

    print(f"      cluster={cluster.name}")

    print(f"      status=" f"{_status(container.status)}")

    print(f"      vcpus=" f"{container.vcpus}")

    print(f"      memory_mib=" f"{container.memory_bytes // 1024**2}")

    print(f"      swap_mib=" f"{container.swap_bytes // 1024**2}")

    print(f"      disk_mib=" f"{_disk_mib(container)}")

    print(f"      architecture=" f"{container.architecture}")

    print(f"      os_type=" f"{container.os_type}")

    print(f"      start_on_boot=" f'{"on" if container.autostart else "off"}')

    current_cf = {}

    if existing is not None:
        current_cf = dict(
            getattr(
                existing,
                "custom_fields",
                None,
            )
            or {}
        )

    desired_cf = build_lxc_custom_fields(
        container,
        current_cf,
    )

    print("      managed_custom_fields:")

    for field_name in MANAGED_LXC_CUSTOM_FIELDS:
        action = "KEEP" if current_cf.get(field_name) == desired_cf.get(field_name) else "SET"

        print(
            f"        {action} "
            f"{field_name}="
            + json.dumps(
                desired_cf.get(field_name),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
