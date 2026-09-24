# Source retirement integration (local implementation)

Current recovery delivery and remaining limitations: [24 September acceptance](backend-completion-acceptance-20260924.md). Older checkpoint counts below are historical.

This is the implemented boundary for the separately approved retirement worker.
It is not a declaration that all twelve backend-completion requirements or live
acceptance have passed. No live NetBox objects were inspected or changed.

## Processes and trust

- Secret broker retains literal `network_mode: none`, provider credential ownership
  checks and local filesystem cleanup. No NetBox/DB access was added.
- Lifecycle worker has only the internal DB network in bundled mode and no
  NetBox/provider token mount. It owns the shared apply lock, registry/tombstone checks and retirement journal.
- `netbox-sync-retirement-worker` alone receives the existing protected NetBox
  configuration read-only and the optional NetBox CA directory read-only. It has
  only the egress network, no PostgreSQL network/DSN, provider credentials, published
  ports, Docker socket or systemd interface. Root is needed for its root-only Unix
  socket; capabilities remain dropped except CHOWN. Filesystem is read-only.
- Only lifecycle mounts `/run/netbox-sync-retirement/worker.sock`. API has neither
  this socket nor the NetBox token. Server-side Admin authorization protects review,
  confirmation, receipt check and explicit continuation; Operator/Viewer are refused.
- The HTTP child accepts only fixed actions against the protected configured HTTPS
  NetBox URL, validates its certificate with the existing optional CA, pins DNS and
  refuses redirects. Token travels on stdin, not argv/env/logs. Child deadline is
  45 seconds with bounded termination/reaping; no automatic HTTP write retry.

The existing external-PostgreSQL override already puts lifecycle/API/schedule on
`netbox-sync-egress` to reach the operator database. This change does not add or
broaden that existing attachment. It does **not** provide a network-layer destination
firewall for external-DB mode; DB-only describes lifecycle's implemented capability,
not an OS-enforced egress ACL in that mode. Likewise retirement's fixed destination
is enforced by its closed protocol/pinned HTTP client, not by an IP firewall. A
literal destination-only network requirement for external PostgreSQL remains a
separate deployment-hardening limitation; do not describe it as already enforced.

## Explicit activation and compatibility

Guard is optional and is installed independently into the certified NetBox 4.7.0
instance. Sync does not deploy/manage NetBox. The plugin fails closed on an unknown
schema/trigger/dependency shape. See `deploy/netbox_guard/README.md`.

The operator must verify the guard installation UUID and supply it with
`deploy/install.py --netbox-guard-instance <verified UUID>` alongside the normal
installation/upgrade arguments. It is persisted as `NETBOX_SYNC_GUARD_INSTANCE`
in the root-selected `config/compose.env`. An ordinary upgrade preserves it and
refuses a different UUID; changing the external database requires a separate
reviewed recovery procedure. An absent UUID does not enable deletion or infer trust
from a URL. External PostgreSQL/ingress keep the same boundary.

Source-created cluster and runtime CREATEs can acquire atomic NetBox ownership
claims when this option is configured. Manual and scheduled paths share the facade;
planning intercepts CREATE before any guard call. Run-bound nonces do not authorize
restarting or reapplying a used/uncertain run. Existing objects are not claimed by
this facade. Historical v2 source identities alone are insufficient proof of
creation; an unclaimed/manual dependent blocks retirement rather than being adopted.

## Removal and recovery of the operation

1. Admin requests an exact source-bound object review. Complete bounded placement
   and dependency checks include host/VM/NIC/IP/MAC/disk; common catalogs remain.
2. Confirmation binds the source revision, actor, namespace, original enabled flags,
   tombstone generation, object manifest and digest. Pending runs/uncertain writes,
   foreign ownership and active placement conflicts refuse execution.
3. Migration `0010_source_retirements` persists SENDING and disables synchronization
   before the remote request. NetBox deletes the complete approved tree in one
   transaction under its dependency fence, then records its receipt. Receipt failure
   rolls back deletion. A manually supplied cluster is retained.
4. Only the exact confirmed receipt allows local tombstone/finalization. Local
   exclusive credential cleanup follows existing ownership rules; shared/legacy
   credentials and provider-side access are not revoked. Run History remains.
5. Transport loss/restart retains UNCERTAIN. Ordinary checking reads the original
   receipt, never repeats deletion. A reloaded browser uses the same operation ID.
6. If the original request never arrived, Admin may explicitly confirm continuation.
   The server must first read the exact original REVIEWED receipt and revalidate
   registry generation, digest, namespace and flags. It reuses the same idempotent
   intent; NetBox rechecks dependencies in its transaction. Changed evidence refuses.
   A committed receipt is finalized without another delete. Continuation logs only
   the operation UUID and closed action, never object contents or credentials.

The original authenticated Admin principal currently owns the pending operation.
Transfer to a different Admin is not implemented. Missing/changed evidence cannot
be resolved by inventing a new operation or changing journal rows manually.

## Backup and upgrade

The Sync backup includes its new journal, source/tombstone state and existing secret
protections. Restore converts SENDING to UNCERTAIN, does not replay HTTP writes and
rechecks external receipts even when the restored local record says SUCCEEDED.
It does not back up external NetBox. Its claims/receipts and actual object state
must be recovered together; the separate full-NetBox restore gate remains open.

Before stopping a timer/service, maintenance reads service names from the selected
release's actual Compose model. New backup helpers therefore omit retirement-worker
when backing up an old release that does not define it. Empty/failed inventory
stops preflight before timer/lock changes. Backup restarts only previously running
services and the previously active timer. No current symlink, credentials or volume
replacement is needed to use the compatible helper.

## Executed evidence and remaining work

- Real NetBox 4.7 / PostgreSQL: ten-object retirement, immutable receipt, changed
  dependencies, rollback, concurrency, unchanged manual data and namespace fencing.
- Actual production Compose worker using the newly built `Dockerfile` image, verified
  TLS and separate isolated PostgreSQL coordinator: source review → deliberately
  undelivered request → UNCERTAIN → read-only check → restarted coordinator → explicit
  continuation → receipt → local tombstone. Prior Run History and idempotency passed.
  Product worker code was not replaced by a bind mount in the final gate.
- Full Linux/PostgreSQL suite: 1382 passed, 47 classified skips.
- Narrow DB grants and real dump/restore: 12 passed; separate zero-source PG gate passed. Restored pending removal remains
  uncertain; no automatic replay. Three actual standalone/external Compose-model
  checks passed. API role checks cover all four retirement routes.
- Full current-image production Compose API/auth/probe/bootstrap gate: bundled and
  external DB both passed again after the API resume fix, with an actual API → Unix
  lifecycle refusal for an unknown intent before any NetBox mutation; bundled mode includes supported host CLI backup/restore
  and prior service-state restoration. Historical 897de2a and
  5acd4c1 upgrades to0010 passed, including retained LDAP settings/bind files on
  another upgrade. These no-systemd harnesses do not prove a real host reboot.
- Frontend: 74 unit tests; TypeScript/Vite build; 30 durable lifecycle browser tests,
  including EN/RU explicit continuation at 768px and response loss/reload.

The real worker gate uses a claimed NetBox fixture, not a full provider discovery →
manual/scheduled sync → remove → re-register cycle. That combined gate, legacy claim
migration, orphan executor, old CM UNKNOWN reconciliation, PAM/Proxmox identity and
guard-enabled populated upgrade acceptance remain separate unfinished items. The guard
CREATE facade has focused tests, but this does not prove all those runtime paths.
No live acceptance, push or deployment is implied by the local evidence above.
