# One-time Guard permissions for a Sync installation

This is operator configuration of the external NetBox, not an installer action.
No live NetBox changes have been performed. The integration user must not be a
superuser; the runtime token must not have arbitrary NetBox DELETE privileges.

The installer writes a non-secret random installation identity to
`$ROOT/state/installation-id`, and the same value to `NETBOX_SYNC_SOURCE_NAMESPACE`
in generated API configuration. Upgrades preserve it. New source IDs use
`n<32 hexadecimal characters>-<provider>-<random identifier>` (at most 62 characters).
The API checks this namespace before reserving a new source. Display names remain
operator-selected. Existing sources retain their identities and ownership.

After `deploy/install.py --prepare-only` for the selected root, obtain the exact
native NetBox ObjectPermission definitions without printing any env values:

```sh
python3 "$CHECKOUT/deploy/guard_permissions.py" --root "$ROOT"
```

In NetBox Administration → Permissions, create the two definitions shown by this
command and assign them to the dedicated Sync integration user/group. Use the
exact Object Type, actions and JSON constraints. This is once per installation,
not once per source. The `source_instance__startswith` includes the terminating
hyphen; do not replace it with an empty prefix or remove the constraint.

These are **additional Guard permissions**, not a replacement for ordinary
constrained view/add/change permissions on supported NetBox models and read
permissions on catalogs/custom fields. Preserve the approved placement scope of
those model permissions. Guard still checks actual parent placement, provenance,
object generation, dependencies and the complete retirement closure. Prefix
membership alone never grants ownership of an existing object.

For an existing installation, retain its already-reviewed exact legacy source
constraints once, alongside the new installation prefix. Do not grant all
historical source IDs merely because their names match. Old persisted registration
attempts can retain their original ID only when bound to the authenticated actor;
new requests cannot choose an unrelated namespace. A genuinely clean reinstall
gets a different namespace and cannot silently adopt the old installation's objects.

## Closed-source fencing and compatible transition

This release needs Guard capability `source_namespace_state` and authenticated
`GET sources/<source>/state/`. This returns only source identity and a closed/open
boolean. It performs no write. GuardIdentity, SourceClosure and external audit
remain unchanged. Existing Guard CREATE/retirement routes remain compatible;
there is no migration for this new endpoint.

The NetBox operator must install the matching reviewed plugin code separately,
retaining its database and installation UUID, **before** enabling this Sync release's
new registration/full-purge path. Sync does not update NetBox. An older plugin fails
closed with a specific integration-update message; no fallback CREATE, local
reservation or credential write is allowed. This is a real deployment dependency,
not a claim that the current test installation has already been updated.

The local real-NetBox 4.7 test grants a single fixture installation prefix, creates
multiple ESXi/Proxmox source trees without per-source permission edits, and rejects
an outside namespace with transaction rollback. Live operator acceptance remains
separate. External NetBox receipts and generation seals are security/audit records;
Sync-local purge does not erase them or reopen a retired namespace.
