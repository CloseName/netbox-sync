# Recreated ESXi virtual machines

NetBox Sync retains records absent from discovery. Absence does not prove deletion:
an inventory can be incomplete, permissions can change, or a VM can move.
An offline VM is not necessarily absent and is never considered deleted just because
it is powered off or lacks VMware Tools.

## Automatic replacement

After a successful fresh ESXi discovery, a new UUID may reuse an old card when:

- Exactly one old card and one new VM share the name (case-insensitive), in the
  same source instance and target cluster. The old UUID is absent from discovery.
- Guard has a creation claim for the card and every component being replaced.
  A sync identity, matching name or the `netbox-sync-apply` author alone is not
  creation proof. Manually created/adopted cards remain protected.
- There are no IPs, NAT dependencies, provider bindings, external references,
  pfSense metadata, or unrecognized/manual component metadata.
- The complete dependency fingerprint still matches immediately before writing.

The plan shows `VM_GENERATION_REPLACE`: an update to the existing NetBox ID,
with a link to the card and the old/new UUID. Guard atomically changes the UUID
and removes the old creation-proven, unconnected NICs/disks/MAC records. The normal
executor then writes current CPU/RAM/status and builds the new components.
No old IP or external binding is transferred. There is no per-host mapping.

The Guard reset is atomic; the subsequent synchronization is not one global
database transaction. If a later write fails, the existing partial-run protection
requires a fresh plan. The next plan matches the new UUID and finishes its managed
fields; it must not blindly repeat the original plan. Reset receipts make the
exact same request idempotent and reject changed payloads or generations.

If proof is unavailable (including an older Guard), the new VM remains a separate
`VM_RECREATED_NAME` review item; other safe objects can synchronize. The old card
and its associations are preserved. The review links to that card. A unique name
on the new VM allows a separate card without transferring old associations.

Foreign or multiple owners, an old UUID still present in inventory, multiple
candidates, and matching network addresses remain protected conflicts. Name
comparison is case-insensitive. There are no per-host names or IDs in the rule.
Proxmox generation replacement is not introduced by this change; its identifiers
have different reuse semantics.

## Test acceptance

Update both Guard and Sync with `deploy/update-vm-replacement-test.sh`. It verifies
the test host and URLs, backs up Sync plus the NetBox database/configuration, and
preserves the old Guard image. It does not request inventory synchronization;
the configured scheduler resumes after the installer.

1. Sync a disposable VM through Guard and record its NetBox ID/UUID.
2. Delete it in the test hypervisor and create a VM with the same name, new UUID
   and new MAC. Rebuild: one generation replacement, same card ID.
3. Apply. Verify the new UUID/resources, same ID, no old NIC/disk residue.
4. Rebuild: no second replacement and no duplicate card.
5. Repeat with an IP or manually created component on the old card: it must stay
   unchanged and require separate review. Existing pfSense and provider links
   must remain unchanged.

Production is not an acceptance environment for this change.

Backups stay in the printed `/var/tmp/netbox-vm-replacement-backup.*` directory.
`previous-netbox-image` and `previous-sync-release` record prior versions. A code
rollback does not undo an already applied UUID replacement; data recovery needs
the corresponding reviewed database restore procedure.
