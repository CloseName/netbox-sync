"""Shared post-discovery sync execution with explicit injected collaborators."""

import os
import sys

import pynetbox


def execute_discovered_source(
    source_config,
    hosts,
    sync_mode,
    pve_api=None,
    *,
    _scheduled_stage,
    _read_secret,
    execute_esxi_runtime,
    apply_full_sync,
    _load_nb_objects,
    _run_inventory,
    plan_hosts,
    apply_hosts,
    apply_virtual_machines,
    apply_vm_networks,
    apply_lxc_containers,
    apply_lxc_networks,
    _process_pve_tags,
    _process_pve_virtual_machine,
):
    """Run the shared NetBox pipeline for generic discovered objects."""

    # Read-only inspection remains available for duplicate reconciliation.
    if sync_mode == "apply" and os.getenv("SOURCE_CONFIG_MODE") in ("registry", "registry-all"):
        from .source_bootstrap import _postgres_registry
        from .host_registration import HostRegistrationConflict
        from .orchestrator import SourceReconciliationRequired

        registry = _postgres_registry(os.environ["NETBOX_SYNC_REGISTRY_DSN"], os.environ["NETBOX_SYNC_REGISTRY_SCHEMA"])
        try:
            registry.assert_exclusive_host(source_config)
        except HostRegistrationConflict:
            raise SourceReconciliationRequired("Duplicate provider host identity requires reconciliation") from None

    # Select the NetBox token by synchronization mode.
    #
    # inventory / plan:
    #   read-only token
    #
    # apply:
    #   dedicated write-enabled token, available only through
    #   the explicit apply compose override.
    if sync_mode == "apply":
        apply_scope = (
            os.getenv(
                "APPLY_SCOPE",
                "",
            )
            .strip()
            .lower()
        )

        if apply_scope not in {
            "host",
            "vm",
            "vm-network",
            "lxc",
            "lxc-network",
            "full",
        }:
            raise SystemExit(
                "SYNC_MODE=apply requires "
                "APPLY_SCOPE=host, vm, "
                "vm-network, lxc, "
                "lxc-network, or full. "
                "No changes were written."
            )

        nb_token_variable = "NB_APPLY_API_TOKEN"
    else:
        nb_token_variable = "NB_API_TOKEN"

    _scheduled_stage("netbox")
    # Read durable truth only inside the trusted scheduled runtime.
    if os.environ.get("NETBOX_SYNC_NETBOX_CONFIG_FILE"):
        from .bootstrap_state import runtime_netbox

        netbox_url, netbox_token = runtime_netbox(
            os.environ["NETBOX_SYNC_NETBOX_CONFIG_FILE"], "apply" if sync_mode == "apply" else "read"
        )
    else:
        netbox_url, netbox_token = os.environ["NB_API_URL"], _read_secret(nb_token_variable)
    nb_api = pynetbox.api(url=netbox_url, token=netbox_token)
    from .netbox_tls import configure_session

    configure_session(nb_api.http_session)

    if source_config.source_type == "esxi" and sync_mode == "plan":
        execute_esxi_runtime(
            nb_api,
            hosts,
            source_config,
            confirmed=False,
        )
        return

    if sync_mode == "apply" and apply_scope == "full":
        # Full scheduled execution uses the same scoped plan/executors as Web.
        # Do not preload the legacy catalog (disks, VLANs, prefixes, global rows).
        from .application.runtime_plan import build_runtime_plan

        _scheduled_stage("planning")
        history_plan = build_runtime_plan(nb_api, hosts, source_config)
        _scheduled_stage("planning", history_plan)
        if not history_plan.apply_allowed:
            from .scheduled_failure import ScheduledPlanBlocked

            raise ScheduledPlanBlocked("PLAN_BLOCKED")
        from .guarded_creation import for_run
        from .scheduled_failure import current_run_id

        nb_api = for_run(
            nb_api,
            source_config,
            instance=os.environ.get("NETBOX_SYNC_GUARD_INSTANCE"),
            run_id=current_run_id(),
            url=netbox_url,
            token=netbox_token,
        )
        # Executors repeat read-only preflight before reaching actual writes.
        # A read failure there must not create a permanent uncertain-write gate.
        before_write = lambda: _scheduled_stage("apply", history_plan)
        if source_config.source_type == "esxi":
            execute_esxi_runtime(
                nb_api,
                hosts,
                source_config,
                confirmed=os.getenv("APPLY_CONFIRM", "") == "FULL_WRITE",
                before_write=before_write,
            )
        else:
            apply_full_sync(
                nb_api,
                hosts,
                source_config.target,
                confirmed=os.getenv("APPLY_CONFIRM", "") == "FULL_WRITE",
                before_write=before_write,
            )
        return history_plan

    if source_config.source_type == "esxi" and sync_mode == "apply":
        raise SystemExit("Normal ESXi apply requires APPLY_SCOPE=full. No changes were written.")

    _scheduled_stage("legacy_read")
    # Load NetBox objects
    nb_objects = _load_nb_objects(nb_api)

    if sync_mode == "inventory":
        _run_inventory(
            nb_objects,
            hosts,
        )
        return

    if sync_mode == "plan":
        target_config = source_config.target

        plan_hosts(
            nb_api,
            nb_objects,
            hosts,
            target_config,
        )
        return

    if sync_mode == "apply":
        _scheduled_stage("apply")
        target_config = source_config.target

        if apply_scope == "host":
            apply_hosts(
                nb_api,
                hosts,
                target_config,
                confirmed=(os.getenv("APPLY_CONFIRM", "") == "HOST_WRITE"),
            )
            return

        if apply_scope == "vm":
            apply_virtual_machines(
                nb_api,
                hosts,
                target_config,
                confirmed=(os.getenv("APPLY_CONFIRM", "") == "VM_WRITE"),
            )
            return

        if apply_scope == "vm-network":
            apply_vm_networks(
                nb_api,
                hosts,
                target_config,
                confirmed=(os.getenv("APPLY_CONFIRM", "") == "VM_NETWORK_WRITE"),
            )
            return

        if apply_scope == "lxc":
            apply_lxc_containers(
                nb_api,
                hosts,
                target_config,
                confirmed=(os.getenv("APPLY_CONFIRM", "") == "LXC_WRITE"),
            )
            return

        if apply_scope == "lxc-network":
            apply_lxc_networks(
                nb_api,
                hosts,
                target_config,
                confirmed=(os.getenv("APPLY_CONFIRM", "") == "LXC_NETWORK_WRITE"),
            )
            return

    print("=== APPLY MODE ===")
    print("WARNING: changes to NetBox are enabled.")

    # Process Proxmox tags
    _process_pve_tags(
        pve_api,
        nb_api,
        nb_objects,
    )

    # Fetch VM tags from Proxmox
    pve_vm_tags = {}
    for pve_vm_resource in pve_api.cluster.resources.get(type="vm"):
        pve_vm_tags[pve_vm_resource["vmid"]] = []

        if "pool" in pve_vm_resource:
            pve_vm_tags[pve_vm_resource["vmid"]].append(f'Pool/{pve_vm_resource["pool"]}')

        if "tags" in pve_vm_resource:
            pass  # TODO: pve_vm_tags[pve_vm_resource['vmid']].append(pve_vm_resource['tags'])

    pve_ha_virtual_machine_ids = list(
        map(
            lambda r: int(r["sid"].split(":")[1]),
            filter(lambda r: r["type"] == "service", pve_api.cluster.ha.status.current.get()),
        )
    )

    # Process Proxmox nodes
    for pve_node in pve_api.nodes.get():
        pve_replicated_virtual_machine_ids = list(
            map(lambda r: r["guest"], pve_api.nodes(pve_node["node"]).replication.get())
        )

        # This script does not create the hardware devices.
        nb_device = nb_objects["devices"].get(pve_node["node"].lower())
        if nb_device is None:
            print(f'The device {pve_node["node"]} is not created on NetBox. Exiting.')
            sys.exit(1)
        else:
            nb_device.status = "active" if pve_node["status"] == "online" else "offline"
            nb_device.save()

        # Process Proxmox virtual machines per node
        for pve_virtual_machine in pve_api.nodes(pve_node["node"]).qemu.get():
            _process_pve_virtual_machine(
                pve_api,
                nb_api,
                nb_objects,
                nb_device,
                pve_vm_tags.get(pve_virtual_machine["vmid"], []),
                pve_virtual_machine,
                pve_virtual_machine["vmid"] in pve_replicated_virtual_machine_ids,
                pve_virtual_machine["vmid"] in pve_ha_virtual_machine_ids,
            )
