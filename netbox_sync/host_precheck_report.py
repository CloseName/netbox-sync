"""Pre-write report for fully checked host contexts."""


def print_host_precheck(contexts, site, cluster, host_types):
    """Print the original host precheck report without changing records."""
    print("=== HOST APPLY PRECHECK ===")
    print(f"target_site={site.name} " f"cluster={cluster.name}")
    print()

    for context in contexts:
        host = context["host"]
        device_type = host_types[host.source_id]
        device = context["device"]

        action = "MATCH" if device is not None else "CREATE"

        print(
            f"{action} DEVICE "
            f"{host.normalized_name}" + (f' reason={context["match_reason"]}' if context["match_reason"] else "")
        )

        changed_cf = context["changed_custom_fields"]

        print(f"  managed_custom_fields_changed=" f"{len(changed_cf)}")

        if changed_cf:
            print("  managed_custom_fields=" + ",".join(changed_cf))

        print(f"  interfaces=" f"{len(host.interfaces)}")

        print(f"  addresses=" f'{len(context["addresses"])}')

        print(f"  management=" f'{context["management_interface"]}:' f'{context["management_address"]}')

    print()
    print("PRECHECK PASSED")
