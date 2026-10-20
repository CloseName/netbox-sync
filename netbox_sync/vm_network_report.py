"""Operator-facing precheck report for validated VM network contexts."""

from .interface_display import interface_display_name


def _print_interface(vm, nic_context, counts):
    """Print one VM interface and accumulate its network action counts."""
    nic = nic_context["source"]
    existing = nic_context["existing"]

    if existing is None:
        counts["interface_create"] += 1
        action = "CREATE"
    elif nic_context["interface_changes"]:
        counts["interface_update"] += 1
        action = "UPDATE"
    else:
        counts["interface_skip"] += 1
        action = "SKIP"

    print(
        f"  {action} INTERFACE "
        f"name={interface_display_name(vm, nic)} "
        f'bridge={nic.bridge or "-"} '
        f"vlan="
        f'{nic.vlan_id if nic.vlan_id is not None else "-"}'
    )

    if nic_context["mac_value"]:
        if nic_context["existing_mac"] is None:
            counts["mac_create"] += 1
            mac_action = "CREATE"
        else:
            counts["mac_reuse"] += 1
            mac_action = "MATCH"

        print(f"    {mac_action} MAC " f'{nic_context["mac_value"]}')

    for ip_context in nic_context["ips"]:
        if ip_context["existing"] is None:
            counts["ip_create"] += 1
            ip_action = "CREATE"
        else:
            counts["ip_reuse"] += 1
            ip_action = "MATCH"

        print(f"    {ip_action} IP " f'{ip_context["address"]}')


def _print_primary(context, vm, counts):
    """Print the VM primary-IP decision, retaining manual-primary preservation counts."""
    candidate = context["primary_candidate"]

    if candidate is not None:
        primary_action = context["primary_action"]
        if primary_action == "set":
            counts["primary_set"] += 1
            print(f"  PRIMARY IPv4 SET candidate={candidate}")
        elif primary_action == "match":
            counts["primary_match"] += 1
            print(f"  PRIMARY IPv4 MATCH candidate={candidate}")
        else:
            counts["primary_preserve_manual"] += 1
            print(
                "  PRIMARY IPv4 PRESERVE "
                f"vm={vm.original_name!r} "
                f'current={context["primary_current"]!r} '
                f"discovered={candidate!r} "
                "reason=same-vm-existing-primary"
            )


def print_vm_network_precheck(contexts, site, cluster):
    """Print planned actions and counters without performing writes."""
    counts = dict.fromkeys(
        (
            "interface_create",
            "interface_update",
            "interface_skip",
            "mac_create",
            "mac_reuse",
            "ip_create",
            "ip_reuse",
            "primary_set",
            "primary_match",
            "primary_preserve_manual",
        ),
        0,
    )

    print("=== VM NETWORK APPLY PRECHECK ===")
    print(f"target_site={site.name} " f"cluster={cluster.name}")
    print()

    for context in contexts:
        vm = context["source_vm"]
        netbox_vm = context["netbox_vm"]

        print(f"VM id={netbox_vm.id} " f"vmid={vm.vmid} " f"name={vm.original_name!r}")

        for nic_context in context["nics"]:
            _print_interface(vm, nic_context, counts)

        _print_primary(context, vm, counts)

    print()
    print("PRECHECK SUMMARY")
    print(f"  interface_create={counts['interface_create']}")
    print(f"  interface_update={counts['interface_update']}")
    print(f"  interface_skip={counts['interface_skip']}")
    print(f"  mac_create={counts['mac_create']}")
    print(f"  mac_match={counts['mac_reuse']}")
    print(f"  ip_create={counts['ip_create']}")
    print(f"  ip_match={counts['ip_reuse']}")
    print(f"  primary_set={counts['primary_set']}")
    print(f"  primary_match={counts['primary_match']}")
    print("  primary_preserve_manual=" f"{counts['primary_preserve_manual']}")

    print()
    print("PRECHECK PASSED")
