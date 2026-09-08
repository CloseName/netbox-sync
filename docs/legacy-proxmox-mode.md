> Paths using `/opt/netbox-sync` below illustrate the generic default. For another root, use the selected ROOT and [deployment path contract](deployment-paths.md).

# Legacy Proxmox mode

This compatibility path runs one Proxmox VE source from the historical provider-specific environment contract. It is not the canonical production deployment.

Use the `netbox-sync` command with protected `PVE_*` and `NB_*` variables or their documented `*_FILE` variants. `SOURCE_INSTANCE` must be operator-defined and stable. Never place tokens in the repository or shell history.

The Proxmox account requires read access to `VM.Monitor`, `Pool.Audit`, `VM.Audit`, and `Sys.Audit`. The NetBox token needs only the permissions required by the selected guarded operation.

Existing logical source credential filenames and registry references are unchanged by the product naming migration. Old absolute secret paths are supported only by the explicit legacy resolver; new Deployment Foundation services use `/opt/netbox-sync/secrets` and `/run/secrets/netbox-sync*` mounts.

For new installations use [Deployment](deployment.md), register sources through the supported source registry/Web flow, and use the canonical scheduler and worker boundaries.
