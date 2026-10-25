# Automated test Guard update and Selectel evidence reconciliation

This is an optional stage of the reviewed `deploy/update_test.py`, not a new
installer, GitHub deployment credential, production path or import authorization.
The operator approves a merged full SHA and deployment separately. No manual
server diagnostic commands are part of this workflow. The existing release
executor loads the approved version and runs its saved updater. Transport/start
of the release executor remains the installation's deployment mechanism; this PR
does not install a privileged web updater or a GitHub runner on the server.

## Release operation

Use `--with-guard` alongside the existing pinned `--commit` option in both
read-only preflight and the separately approved `--apply --idle-confirmed` operation.
UI maintenance acknowledgement remains required: no running/pending source or
lifecycle work, no concurrent operators. Schedules must already be off. The
script refuses scheduled/running Selectel work rather than changing schedules.

1. Validate canonical Sync host, root, commit, URLs, bootstrap and schedules.
   Discover NetBox/worker Compose identity from running container labels. Reject
   foreign roots, different images, external bind mounts, plugin source mounts,
   ambiguous/nonlocal database services and missing backup tools. No secrets or
   complete Compose configuration are printed.
2. Pause only the allowlisted Sync services and verify the existing Sync backup.
3. Hold the shared Sync apply lock. Build Guard from the pinned checkout on the
   **exact currently installed NetBox image** with pulling disabled. This is not
   an upgrade of the NetBox base version. No Guard permissions, tokens, native
   flags or account schedules are provisioned or changed.
4. Stop only NetBox and its worker. Save a PostgreSQL custom-format dump and
   validate it with `pg_restore --list`; archive discovered configuration/bind
   sources and validate the archive listing. Retain the old image by a recovery
   tag. The private bundle lives in `/netbox-sync-test/backups/guard-<stamp>-<SHA>`.
   `GUARD_BACKUP_VERIFIED` means an archive/dump can be read, not a rehearsed restore.
5. Replace the existing configured `netbox-with-sync-guard:*` image reference,
   preserving the existing Compose configuration. Run migrations, recreate only
   NetBox/worker with no dependencies, pulling or rebuilding, then verify image
   IDs, health, Django checks, migration state, HTTPS and the loaded Guard content
   fingerprint. Check the managed importer's current preflight permissions.
6. Install/start Sync through the existing updater. Inside the bootstrap container,
   verify the authenticated, namespace-pinned Selectel protocol and reconcile each
   unresolved account by GET. Print only compatibility and per-account evidence
   codes; save the evidence on the account for display in the UI. Recheck schedules.

Any failed stage stops the sequence. It may leave services stopped; backups and
the stage report are retained. There is no automatic rollback, database restore,
image pruning, schedule enablement or blind retry. Recovery needs a reviewed
release action based on the failed stage, not manual server investigation.
All generic child commands have a 30-minute ceiling; dump/list and HTTPS checks
have shorter bounds. The known test stack must fit the discovered contract;
unknown installation layouts fail closed and need a code change.

## Compatibility and receipt semantics

The authenticated account-import preflight now advertises `selectel_protocol: 1`
and `receipt_lookup: true`, after checking permissions and receipt tables. New
Sync refuses a legacy/unknown protocol before collection. This intentionally
requires coordinated Sync/Guard updates for Selectel; ESXi, Proxmox and pfSense
contracts are unchanged. Preflight does not certify all object-level constraints
for future resources or Selectel API permissions.

`GET providers/accounts/<account>/runs/<UUID>/` shares Guard namespace and importer
authorization. It tries the same account transaction lock as import and reads
only receipts. It never calls an import, creates an inventory object or replays
a write. A receipt must belong to the same account and actor. Outcomes:

| Outcome | Meaning and action |
| --- | --- |
| committed | Matching account receipt exists. Sync additionally requires the saved request digest and Guard instance, and validates result shape before confirming completion. |
| not_found | Neither final nor derived stage receipts exist. Absence does not prove that historical writes never occurred. Keep the original error and import gate. |
| partial_evidence | Derived stage receipts exist without final receipt. Preserve the gate; this does not certify which native objects still exist. |
| conflict | Account, actor, instance, digest or result does not match. Preserve the gate. |
| busy / unavailable | Import is active or lookup could not be validated. Preserve the gate; a read-only check can be repeated. |
| intent_unavailable | A historical receipt exists but Sync did not persist its request digest/instance. Preserve the gate. |

New runs atomically persist their canonical payload digest and Guard instance
**before** sending import. A later confirmed receipt changes only completion and
the receipt summary; it does not schedule another run. Recovered receipts cannot
reuse an older run's product coverage. Original UUID and finish timestamp remain,
with a separate reconciliation timestamp. These intent fields remain private.

The Selectel UI offers **Проверить результат импорта** under the existing admin
permission. It performs the same GET-only lookup, displays evidence, and keeps
collection disabled unless completion is proven. Account/collection/global locks
prevent overlap with local imports and lifecycle operations. Credential edits do
not resolve uncertainty.

The two historical accounts 29916 and 435835 have no receipts in the supplied
25 October evidence. This new release is expected to report `not_found` and keep
them blocked if that remains true. It does not turn them green or invent a safe
retry. Live acceptance, full resource coverage, matching and idempotency still
require separately authorized testing; Selectel remains experimental.
