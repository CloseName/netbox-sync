# Recreated ESXi virtual machines

NetBox Sync retains records absent from discovery. Absence does not prove deletion:
an inventory can be incomplete, permissions can change, or a VM can move.
An offline VM is not necessarily absent and is never considered deleted just because
it is powered off or lacks VMware Tools.

If an existing interface on a VM matches only the adapter name or network label,
Sync reports `VM_NIC_NAME_OCCUPIED` with the VM, adapter and NetBox interface ID(s).
Network writes for that VM resume on a fresh plan once the conflict is resolved.
Inventory updates and other VMs continue during the conflict.

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

When Guard cannot prove a safe replacement, a uniquely identified VM can get
its own card. A retained card with a single, unique VM identity in this source
does not compete for the new VM by name, MAC or IP. A new card whose display name
is occupied receives a deterministic source-and-identity suffix within 64
characters. The original ESXi name remains in the managed metadata. This also
covers simultaneous case-insensitive and truncated-name collisions.

Observe mode saves disputed IP and MAC reports as interface observations. In
strict mode network writes for the participating guests are deferred, while VM
resources and other guests can synchronize. Existing assignments keep their
owners. Explicit VRFs continue to determine the IP address space.

Weak evidence pointing to a legacy or foreign card is isolated for review.
Conflicting exact identities, invalid placement and an untrustworthy source
inventory can still block a plan. Explicit legacy adoption has its own preflight.

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
   unchanged while the new VM receives a separate card. Existing pfSense and provider links
   must remain unchanged.

Production is not an acceptance environment for this change.

Backups stay in the printed `/var/tmp/netbox-vm-replacement-backup.*` directory.
`previous-netbox-image` and `previous-sync-release` record prior versions. A code
rollback does not undo an already applied UUID replacement; data recovery needs
the corresponding reviewed database restore procedure.
