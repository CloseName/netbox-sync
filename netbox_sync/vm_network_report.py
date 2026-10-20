"""Operator-facing precheck report for validated VM network contexts."""

from .interface_display import interface_display_name


def print_vm_network_precheck(contexts, site, cluster):
    """Print planned actions and counters without performing writes."""
    interface_create = 0
    interface_update = 0
    interface_skip = 0
    mac_create = 0
    mac_reuse = 0
    ip_create = 0
    ip_reuse = 0
    primary_set = 0
    primary_match = 0
    primary_preserve_manual = 0

    print("=== VM NETWORK APPLY PRECHECK ===")
    print(f"target_site={site.name} " f"cluster={cluster.name}")
    print()

    for context in contexts:
        vm = context["source_vm"]
        netbox_vm = context["netbox_vm"]

        print(f"VM id={netbox_vm.id} " f"vmid={vm.vmid} " f"name={vm.original_name!r}")

        for nic_context in context["nics"]:
            nic = nic_context["source"]
            existing = nic_context["existing"]

            if existing is None:
                interface_create += 1
                action = "CREATE"
            elif nic_context["interface_changes"]:
                interface_update += 1
                action = "UPDATE"
            else:
                interface_skip += 1
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
                    mac_create += 1
                    mac_action = "CREATE"
                else:
                    mac_reuse += 1
                    mac_action = "MATCH"

                print(f"    {mac_action} MAC " f'{nic_context["mac_value"]}')

            for ip_context in nic_context["ips"]:
                if ip_context["existing"] is None:
                    ip_create += 1
                    ip_action = "CREATE"
                else:
                    ip_reuse += 1
                    ip_action = "MATCH"

                print(f"    {ip_action} IP " f'{ip_context["address"]}')

        candidate = context["primary_candidate"]

        if candidate is not None:
            primary_action = context["primary_action"]
            if primary_action == "set":
                primary_set += 1
                print(f"  PRIMARY IPv4 SET candidate={candidate}")
            elif primary_action == "match":
                primary_match += 1
                print(f"  PRIMARY IPv4 MATCH candidate={candidate}")
            else:
                primary_preserve_manual += 1
                print(
                    "  PRIMARY IPv4 PRESERVE "
                    f"vm={vm.original_name!r} "
                    f'current={context["primary_current"]!r} '
                    f"discovered={candidate!r} "
                    "reason=same-vm-existing-primary"
                )

    print()
    print("PRECHECK SUMMARY")
    print(f"  interface_create={interface_create}")
    print(f"  interface_update={interface_update}")
    print(f"  interface_skip={interface_skip}")
    print(f"  mac_create={mac_create}")
    print(f"  mac_match={mac_reuse}")
    print(f"  ip_create={ip_create}")
    print(f"  ip_match={ip_reuse}")
    print(f"  primary_set={primary_set}")
    print(f"  primary_match={primary_match}")
    print("  primary_preserve_manual=" f"{primary_preserve_manual}")

    print()
    print("PRECHECK PASSED")
