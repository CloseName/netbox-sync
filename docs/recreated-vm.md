# Recreated ESXi virtual machines

NetBox Sync retains records absent from discovery. Absence does not prove deletion:
an inventory can be incomplete, permissions can change, or a VM can move.
An offline VM is not necessarily absent and is never considered deleted just because
it is powered off or lacks VMware Tools.

When a new UUID reuses the name of an absent VM owned by the same source in the
same target cluster, the new VM is isolated as `VM_RECREATED_NAME`. Other objects
continue through the normal guarded synchronization. This is not adoption: no old
UUID, IP, interface, disk, NAT or provider binding is moved to the replacement.

The review shows the old NetBox record link and old/new identifiers. Give the new
VM a unique name on the hypervisor and rebuild the plan to create a separate card.
Retirement/deletion of the old card remains a separate reviewed operation. This
release does not automatically rename or delete old cards, or create a new card
under a generated alias. It removes the source-wide blocker for this narrow case,
not the need to resolve the occupied name for the new VM.

Foreign or multiple owners, an old UUID still present in inventory, multiple
candidates, and matching network addresses remain protected conflicts. Name
comparison is case-insensitive. There are no per-host names or IDs in the rule.

## Test acceptance

1. Sync a disposable VM and record its NetBox ID/UUID and existing associations.
2. Delete it in the test hypervisor and create a VM with the same name, new UUID
   and new MAC. Rebuild: one review row, no source-wide ambiguity blocker.
3. Review the retained record link and identifiers; sync an unrelated change.
   The old card and all of its associations must remain unchanged.
4. Rename the replacement to a unique name. Rebuild and sync: a separate new card
   must be created without reusing the old ID or associations.
5. Rebuild again: the replacement must match its own stable identity.

Production is not an acceptance environment for this change.
