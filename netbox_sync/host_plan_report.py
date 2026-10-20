"""Read-only planning stages preserving existing selection and output contracts."""


def print_host_plan_targets(site, role, platform, host_types, cluster_type, cluster, hosts, config):
    print("=== NETBOX INFRASTRUCTURE PLAN ===")
    print("No changes will be written to NetBox.")
    print()

    print("TARGET CONFIG")
    print(f"  site:         {site.name} (id={site.id})")
    print(f"  device_role:  {role.name} (id={role.id})")
    print(f"  platform:     {platform.name} (id={platform.id})")
    for host in hosts:
        device_type = host_types[host.source_id]
        print(
            f"  device_type [{host.source_id}]: "
            f'{getattr(device_type, "model", None) or device_type.slug} '
            f"(id={device_type.id})"
        )
    print(f"  cluster_type: {cluster_type.name} " f"(id={cluster_type.id})")
    print()

    if cluster is None:
        print(f"CREATE CLUSTER name={config.cluster_name} " f"type={cluster_type.name} " f"scope=dcim.site:{site.id}")
    else:
        print(f"MATCH CLUSTER id={cluster.id} " f"name={cluster.name} " f"reason=name+type+scope")

    print()


def report_host_plans(
    nb_api,
    nb_objects,
    hosts,
    config,
    site,
    role,
    platform,
    host_types,
    cluster,
    *,
    _find_device_match,
    _plan_host_network,
    build_device_custom_fields,
    MANAGED_DEVICE_CUSTOM_FIELDS,
    json,
    plan_virtual_machines,
    plan_vm_networks,
    plan_lxc_containers,
):
    for host in hosts:
        device_type = host_types[host.source_id]
        print(f"HOST source={host.source} " f"source_id={host.source_id}")

        device, reason = _find_device_match(
            nb_objects,
            host,
        )

        if device is None:
            print(f"  CREATE DEVICE " f"name={host.normalized_name}")
        else:
            print(f"  MATCH DEVICE " f"id={device.id} " f"name={device.name} " f"reason={reason}")

        print(f"  SET site={site.name}")
        print(f"  SET role={role.name}")
        print(f"  SET platform={platform.name}")
        print(f"  SET device_type={device_type.slug}")
        print(f"  SET cluster={config.cluster_name}")
        print(f"  SET primary_ip4=" f'{host.management_ip or "-"}')

        _plan_host_network(
            nb_api,
            host,
            device,
            site,
        )

        existing_custom_fields = (
            dict(
                getattr(
                    device,
                    "custom_fields",
                    None,
                )
                or {}
            )
            if device is not None
            else {}
        )

        desired_custom_fields = build_device_custom_fields(
            host,
            existing_custom_fields,
        )

        print()
        print("  MANAGED CUSTOM FIELDS")

        for field_name in MANAGED_DEVICE_CUSTOM_FIELDS:
            current = existing_custom_fields.get(field_name)

            desired = desired_custom_fields.get(field_name)

            action = "KEEP" if current == desired else "SET"

            rendered = json.dumps(
                desired,
                ensure_ascii=False,
                sort_keys=True,
            )

            print(f"    {action} " f"{field_name}=" f"{rendered}")

        print()
        print("  DISCOVERED HARDWARE")
        print(f'    cpu_model={host.cpu.model or "-"}')
        print(f'    cpu_vendor={host.cpu.vendor or "-"}')
        print(f"    cpu_sockets={host.cpu.sockets}")
        print(f"    cpu_cores={host.cpu.cores}")
        print(f"    cpu_threads={host.cpu.logical_cpus}")
        print(f"    memory_mib=" f"{host.memory_bytes // 1024**2}")
        print(f"    hypervisor_version=" f'{host.hypervisor_version or "-"}')

        print()
        print(f"  GUESTS qemu={len(host.virtual_machines)} " f"lxc={len(host.containers)}")

        plan_virtual_machines(
            nb_api,
            host,
            cluster,
        )

        plan_vm_networks(
            nb_api,
            host,
            cluster,
            site,
        )

        plan_lxc_containers(
            nb_api,
            host,
            cluster,
        )

        print()
