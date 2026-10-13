# Two-host production update

Use the same clean pinned release on both machines.

1. On netbox-sync: bash deploy/update-production-sync.sh pause
2. On netbox: SYNC_PAUSED=yes bash deploy/update-production-netbox.sh
3. After step 2 succeeds, on netbox-sync: bash deploy/update-production-sync.sh resume

Sync root is /netbox/containers. NetBox Compose paths are discovered from container
labels. Each host prints its backup directory. Sync backups use the verified
backup format. NetBox saves its database, configuration and previous image tag.
Dump catalogue verification is not a full restore rehearsal.
Both UIs are temporarily unavailable. Do not reboot during maintenance: scheduler
masks are runtime-only. If any step fails, keep Sync paused and inspect the error.
No automatic database rollback is attempted. Image rollback alone does not undo
migrations or inventory writes; data rollback requires coordinated database and
configuration recovery. Backup directories are root-only and may contain secrets.
Resume activates configured schedules. Rebuild previously reviewed plans.

## ESXi prerequisites

The network check verifies both esxi_host_network and hardware_identity. New
messages identify the exact field and state. Guard now creates a missing
esxi_host_network during migrations. Existing field values are retained.
Incompatible definitions are not coerced. For provisioning fields, let the
NetBox worker finish and repeat verification before resuming Sync. Review
conflicting definitions in NetBox Sync settings; do not delete populated fields.

## Provider navigation

The NetBox Sync provider menu is defined by Guard, independently of Selectel
account enrollment. Non-superusers need netbox_guard.view_resourceregistry.
The updater does not grant additional privileges. Refresh the UI after upgrading.

The release includes ESXi generation replacement (see recreated-vm.md). Reusing
a card requires proven ownership, absence of the old UUID and no protected
dependencies. IP, NAT, provider bindings and pfSense prevent automatic destructive
component replacement. This is not unconditional same-name adoption.
