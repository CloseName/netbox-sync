# UI-6 integration and acceptance report

Date: 2026-09-07. Repository: `E:\Codex\Project\netbox-sync`.
Base HEAD: `68e6025439136e8ab57b752d20e6fa729e040d1f`.
Status: **READY FOR FINAL MANUAL UI ACCEPTANCE TESTING**.
This supersedes the earlier incomplete draft. Explicit user authorization covered
Apply/API/scheduler integration and the narrow lifecycle capabilities. No push, deploy,
production or historical-server operation was performed. The full UI stage is not closed.

## 1. Pre-implementation architecture findings

The repository used long synchronous frontend requests and React-owned review state.
Discovery/Plan shared a serial Unix-socket supervisor. Existing source-scoped credentials,
root broker file protections, canonical plan digests, single-use confirmation tokens,
child revalidation and shared manual/scheduled apply lock were retained.

Audit answers: A, guaranteed durable Build Plan after disconnect: no; B, persisted active
planning record: no; C, duplicate expensive work possible: yes (serialization could queue
another execution); D, another browser could retrieve a READY plan: no; E, reuse sync_runs
without changing its meaning: no. Separate latest-operation state was the narrower choice.

## 2. Browser-close behavior before changes

A worker could finish after its requester disconnected, but completion alone did not
provide a retrievable durable result. Another browser could neither identify that work
nor review its result. Frontend state could disappear with navigation or browser close.

## 3. Durable operation model

source_operations holds at most two latest slots per source: PLAN and DISCOVERY. Each
has a stable generation UUID, source/kind, closed status, server timestamps, safe error
and canonical bounded result. Actual synchronization remains exclusively in sync_runs.
The discovery supervisor authenticates peers before forking, accepts concurrent short
requests and detaches accepted provider work from the response socket.

## 4. PLAN exclusivity contract

A per-source transaction advisory gate and composite source/kind key serialize start
transitions. Simultaneous starts return the same RUNNING UUID; only the creator launches
work. A separate session advisory lock prevents duplicate executor callbacks. Completion
updates only the matching RUNNING UUID. Late completion emits a safe source/UUID event
without overwriting the latest generation. Real PostgreSQL concurrent races pass.

## 5. DISCOVERY deduplication contract

The same contract applies independently to DISCOVERY. Success is SUCCEEDED rather than
READY. The latest canonical result is retained; no growing discovery history is added.
Browser and PostgreSQL tests check duplicate starts without duplicate provider work.

## 6. Cross-source concurrency

Execution locks are keyed by source and operation kind: another source or the other kind
can proceed. No global operation queue is introduced. Existing global apply serialization
remains solely for write/lifecycle safety. Planning does not silently disable scheduled
sync. Source generation transitions are held during manual review revalidation and Apply.

## 7. Recovery and stale behavior

On lookup, RUNNING older than 180 seconds becomes FAILED/OPERATION_INTERRUPTED only when
its executor lock is free. Existing provider-child execution has a 120-second bound;
DB connections have bounded connection/statement/lock waits and TCP liveness settings.
A supervisor still owning the executor lock is conservatively active; a permanently
unresponsive process requires operator investigation, never forced concurrent retry.

Results expire on lookup after 24 hours: PLAN becomes STALE; DISCOVERY becomes
FAILED/RESULT_EXPIRED. Restore invalidates RUNNING/READY context. There is no automatic
retry or resume. Failed/stale state remains available until explicit new work replaces it.

## 8. Plan persistence and review

The result is validated against the existing closed worker DTO, exact source and canonical
digest before persistence, with an 8 MiB ceiling. Public projection excludes internal IDs.
Prepare binds the current READY operation UUID plus the existing digest/token semantics.
Apply verifies that generation under the unchanged shared filesystem lock and still
replans before writing. Old-generation tokens fail even when a replacement digest is equal.
A failed newer generation cannot revive the prior READY plan. Revalidation marks only the
reviewed UUID stale; failure to persist this projection never permits an otherwise rejected
Apply. No selective rows, bypass of apply_allowed or second apply execution model exists.

## 9. Frontend polling and activity

Sync reads operations on open/refocus and polls sequentially every 2.5 seconds while work
is RUNNING. Reads are bounded at 10 seconds; starts at 15 seconds. Leaving stops browser
polling but not accepted server execution. Lost start acknowledgement triggers a read,
not a duplicate POST retry. Unknown state disables controls pending a successful reload.

Browser B sees the same operation/time and disabled duplicate action. A newly observed
Discovery generation opens its section. READY repopulates review; FAILED/STALE remain
explicit after reopen. Elapsed time has no invented percentage or internal stage.

## 10. Remove Source lifecycle

Configuration > Lifecycle requires exact typed Source ID and a current revision. The
existing shared apply lock, source transition gate and credential-reference gate protect
the transition. Active PLAN/DISCOVERY, active Apply, or retained RUNNING/OUTCOME_UNCERTAIN/
PARTIALLY_APPLIED run evidence blocks removal. Uncertain history is deliberately
conservative and requires reconciliation; a later successful run does not erase it.

The transaction disables the source and automatic sync and creates a tombstone before
optional file cleanup. No NetBox or provider call is made. History and NetBox objects remain.

## 11. Tombstone semantics

The original source row and identity remain reserved. API/scheduler adapters exclude
removed sources and reject subsequent changes. Direct source URLs display removed state,
cleanup outcome and retained-history navigation. There is no restore, purge or automatic
identity reuse. Source configuration and history are not rewritten into a second identity.

## 12. Credential deletion policy

Retention is the default. Explicit cleanup requires exact exclusive local references and
existing broker ownership/receipt/inode/mode checks. The entire pair is retained if any
reference is shared, legacy or ambiguous. Reference assignment is serialized with cleanup
and cannot adopt a tombstoned source's refs. File checks are performed before deletion.

The broker alone performs cleanup; API requests never contain arbitrary deletion paths.
A failure after the committed tombstone leaves CLEANUP_FAILED, with no automatic retry.
Provider-side tokens are never revoked. Linux tests cover owned deletion, shared/legacy
retention, unsafe files, broker transport/restart and original file security contracts.

## 13. Registration collision

An existing tombstone returns SOURCE_ID_RESERVED. The frontend uses a typed allowlisted
error to show: "This Source ID was previously used and is reserved by a removed source."
Unknown backend text remains hidden. PostgreSQL, API, frontend unit and browser tests
cover the distinction; the existing generic form initially masked it and was corrected.

## 14. Backup/restore changes

The reviewed head and exact table inventory include operations/tombstones. Full DB state
is dumped; manifest secret refs cover active sources so explicitly removed local files
are not required for a removed source. Remaining files preserve the existing tar/xattrs
contract. Fresh restore rejects source, history, operation and tombstone rows, including
orphan lifecycle evidence; exact empty-schema cleanup has no CASCADE.

After forward migration/grants, restored RUNNING operations become interrupted failures
and READY plans become STALE, with results cleared and no resume. Tombstones/history
remain. Validated older bundles receive only the missing protected role secrets/DSNs and
broker.env in staging. Current configuration is preserved. A real client-path mismatch
was fixed: the external PostgreSQL binary checked is now the same absolute binary executed.

## 15. DB roles and security

New operation_writer can SELECT source identity/enabled and SELECT/INSERT/UPDATE operation
slots. New lifecycle_writer can SELECT required evidence, update source enabled/sync_enabled,
insert narrow tombstone columns and update cleanup state. Existing readers gain only the
needed tombstone/operation SELECT. Actual grants deny runtime DELETE/TRUNCATE/DDL, schema
creation, identity rewrite and unrelated table/column writes. No migration-owner DSN reaches
runtime. Provider children strip writer DSNs; API receives neither new writer.

Bootstrap-stage follow-up supersedes the original broker/DB integration: the broker
now has literal `network_mode: none` and no DB credentials. A separate lifecycle worker
owns the unchanged narrow DB capability and shared apply lock, and calls broker-owned
file cleanup over Unix socket. It has no provider or NetBox secret mounts. See
[first-run boundaries and acceptance](first-run.md).

## 16. Historical-server bridge

The actual historical "Planning worker unavailable" cause remains unverified: that server
was intentionally not accessed. The [runbook](historical-ui-test-bridge.md) distinguishes
mount/path/listener/peer/protocol/timeout failures using read-only, secret-free checks and
provides a separate disposable-VM clone procedure. It is not an instruction to upgrade
the historical server. No implicit naming/socket compatibility fallback was added.

## 17. Backend/API changes

New protected operation start endpoints and bounded operation reads use the discovery
supervisor. Lifecycle read/remove uses fixed peer-checked broker messages. Existing
synchronous Plan/Discovery endpoints share the durable store; UI uses start/read.
Configured production Apply requires generation context in addition to its existing
capability. Source, result, CSRF and malformed-response boundaries have regression coverage.
Scheduler uses lifecycle-aware adapters and its existing lock/execution semantics.

## 18. Migrations

0004_source_operations follows unchanged 0003_netbox_sync_naming. New head
0005_source_tombstones adds reservations and an invoker-security, fixed-search-path
credential-reference trigger. Historical migrations remain unchanged. Both new revisions
are forward-only, with no destructive downgrade. New/populated/repeated migration and
actual grants pass on PostgreSQL 16; historical naming transition passes separately.

## 19. Tests and results

- Final full Linux/PostgreSQL-enabled backend suite: **752 passed, 4 skipped**, 23.17s.
  Includes real Unix fork/disconnect, operation races/fencing, source lifecycle, Linux
  broker/root/xattr security, deployed grants and PostgreSQL backup/restore.
- Linux skips: Docker backup opt-in, Docker CLI Compose, naming-cluster opt-in and live
  ESXi. The first three were separately run successfully on the Docker-enabled host;
  live ESXi was intentionally not configured. No real providers are required by this task.
- Host Docker backup + backup regressions: **38 passed, 1 Linux-only skip**. The Linux
  xattr case passes in the full Linux suite. Unique Docker project/volume cleaned by test.
- Host deployment tests: **33 passed, 3 POSIX-only skips**; those POSIX cases pass on Linux.
- Marked disposable naming PostgreSQL regression: **1 passed**.
- Frontend unit: **48 passed**. TypeScript strict and Vite production build pass.
- Full Playwright: **130 passed**, 1.6m. git diff --check passes.

Two backend dependency deprecation warnings and Vite's upstream use-client warnings are
non-failing. No new dependency was introduced to work around those warnings. Counts above
are separate overlapping runs, not a claimed sum of unique tests.

## 20. Browser and manual validation

New independent shared-server browser fixtures cover two browsers, browser close/reopen,
duplicate PLAN/DISCOVERY, other source/kind concurrency, READY/FAILED/STALE and removal.
Visual scenarios cover running, ready, failed, exact confirmation, active blocker, removed
page and reserved-ID registration at 1440/1024/768. Screenshots were inspected for layout,
readability and state clarity. Existing theme, keyboard, zoom and responsive tests pass.

Browser tests mock provider/API data; Linux transport and PostgreSQL tests establish
backend execution separately. No real-provider/manual production acceptance is claimed.
The full UI stage remains open for the user's final manual cases.

## 21. Docker/Compose validation

Docker Engine **29.7.2**, Compose **5.5.0**. Final Dockerfile.web build succeeds.
Image tested: `netbox-sync-ui6-integration:20260907`, manifest
`sha256:37746e4bd5114d817265c6886daae2d7f6e91c42c24379bd5ccc5cfdf11ccbb6`.

Disposable production-like container: UID10001, read-only root, dropped capabilities,
no-new-privileges, localhost-only port, no mounts/credentials, real `/app/web` via Uvicorn.
No Vite/dev server was used for this smoke.

| Exact route | Result |
| --- | --- |
| / | 200 built SPA |
| /sources | 200 built SPA |
| /sources/test-source | 200 built SPA |
| /sources/add | 200 built SPA |
| /runs | 200 built SPA |
| /runs/test-run-id | 200 built SPA |
| /diagnostics | 200 built SPA |
| /sources/test-source/sync | 200 built SPA |
| /sources/test-source/configuration | 200 built SPA |
| /unknown-ui6-route | 404 |
| /api/ui6-missing | 404 |
| /api/v1/ui6-missing | 404 |
| /assets/ui6-missing.js | 404 |
| /missing.js | 404 |
| /assets/index-XjgUoGJU.js | 200; 348335 bytes |
| /assets/index-CUhG9TBo.css | 200; 28144 bytes |

Fetched asset SHA256 values match the files inside the image. Canonical production,
external-PostgreSQL overlay and development Web profiles all render with config --quiet.
Owned Web/test/PG/naming containers, anonymous volumes and tagged smoke images were removed
after exact label checks. Base images and shared build caches were not pruned.

## 22. Commits

- `47fc277` feat: integrate durable operations and safe source lifecycle
- `1b6af75` feat: expose durable operations and source removal in UI
- This report and the six updated product documents/runbook are in the subsequent
  `docs: record UI-6 contracts and acceptance evidence` commit.

Backend runtime, migrations, roles and backup changes form one atomic integration unit.
Local commits use the identity already recorded in the repository history for these
commands only; global Git configuration was not changed. No push/deploy.

## 23. Git status

Implementation is committed; documentation is recorded with this report. Final clean-tree
and exact HEAD verification is reported in the task response after the documentation
commit. Ignored browser/build outputs remain local evidence. The pre-existing inaccessible
.pytest_cache was not deleted or re-owned; tests used no cache provider.

## 24. Remaining blockers for push

No known UI-6 automated acceptance blocker remains. Push is explicitly forbidden until a
separate user instruction; final manual UI acceptance remains outstanding before closing
the redesign. Production migration/release rehearsal is a later deployment activity.

## 25. Remaining blockers before manual UI acceptance

No implementation blocker remains for an isolated manual acceptance test. Provision a
separate matching test stack using the runbook; never attach UI-6 to historical workers
or production targets. Real-provider cases need separately scoped test credentials/targets.
The historical cause is unknown, not silently repaired or asserted from repository evidence.

## 26. Deferred scope

Intentionally excluded: RBAC/LDAP/actor identity, Bootstrap redesign, restore removed
source, purge, provider revocation, bulk actions, global queue, persistent discovery
history, snapshot comparison, maintenance windows, integrations and telemetry. Runtime
run-history reconciliation and human acceptance remain explicit operator work.

Are durable per-source operations, duplicate-operation protection and safe Remove Source lifecycle complete enough for final manual UI acceptance testing?

**YES**
