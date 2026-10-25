# Selectel diagnosis — 25 October 2026

Baseline: freshly fetched main `99676f7351940b598c02ae9530274d74f9a3315f`.
This is dated diagnostic evidence, not acceptance or permission to import.
Production was excluded. Test account state was read, never cleared or retried.

## Current execution path checked against code

| Stage | Implementation and actual boundary |
| --- | --- |
| Save account | `api/selectel.py` validates the request; `selectel_control._save_account` stores credentials in the private root-owned 0600 account file under the bootstrap lock. Saving validates field syntax, **not live credentials**. The public allowlist excludes password/token. Existing uncertain outcomes survive credential replacement. |
| Launch | `selectel_control._collect_account` checks configuration, activation, unresolved outcomes and concurrency. `launch` persists a run UUID before spawning the runner. Missing schedules default to off. |
| NetBox access | `selectel_runner._execute_run` checks Guard preflight before contacting Selectel. Presence of the importer secret file alone is not proof of valid permissions. |
| Provider access | `tools/selectel_audit/collector.Credentials.authenticate` verifies account/domain and project scope. Product reads record per-endpoint coverage; HTTP 200 does not certify account-wide visibility. |
| Collection | The unprivileged child invokes the existing collector. HTTPS origin constraints, request/page/size/deadline limits remain. DNS/storage registry construction and server wire projection are separate. |
| Normalize | `selectel_inventory.Inventory` uses account/project/region/native identity, refuses conflicting server records and retains unavailable sections. `resource_registry` preserves scoped observations/conflicts and unresolved relationships. |
| Match/plan | Guard inventory review and `provider_reconcile.prepare` build internal plans. Bindings/typed hardware evidence are authoritative; names/IPs are candidates or blockers. Reverse onboarding uses `selectel_host_match`. There is **no separate user-reviewed account import plan in Sync yet**. |
| Write | The explicit collect action currently proceeds to import under shared apply and collection locks, with a second activation/run check. `account_import.import_account` atomically writes inventory/registry, optionally native reconciliation, then `ProviderAccountRun` using the run UUID. |
| Result | Runner persists only its current run. Lost responses/process interruption remain uncertain and block retry. The confirmation correction validates the Guard account-result contract before `completed`; known transport refusals differ from uncertainty. |
| UI | Saved credentials are labelled unverified; completed means import acknowledgement, not complete provider coverage. Uncertain accounts cannot start another import and show their run UUID. |

## Read-only evidence supplied from the test installation

The operator confirmed current release `99676f7…` and `netbox-sync.timer` inactive.
Both account schedules and next-run fields were absent/null in the projection;
no scheduler was enabled. The `netbox` container belongs to `/netbox-test` and uses
image `sha256:4a8670c8ce655da6943a858104589b40e1dbe8d41668effe59bbba1cd911dc41`.

| Account | Original run UUID | Current result |
| --- | --- | --- |
| 29916 | `f5f3efcc-436a-4caf-8d21-d5492ba94f4c` | `attention / IMPORT_UNCONFIRMED` |
| 435835 | `85c0013b-6464-4d8a-aa66-2604623ffbcf` | `attention / IMPORT_UNCONFIRMED` |

The runs started 15 October at 08:23:24 and 08:34:24 UTC respectively. Queries in
an explicitly read-only database transaction found no account receipt, no derived
`servers`, `native`, `native-projection` receipt, and no `registry` receipt for
either run. A missing registry receipt alone would not prove failure: unchanged
registry data can produce no change receipt.

Account 29916 has 68 inventory rows observed 12 October, registry revision 2
observed 13 October, 45 bindings and zero `ProviderCreatedObject` rows. Account
435835 has no inventory, registry, bindings or created-object rows. These checks
found no applied full/partial result attributable to the two runs; old rows must
not be counted as their success. Absence of evidence is not authorization to reset
the account, nor proof of the exact historical exception or absence of out-of-band
changes. Historical logs and a separately reviewed reconciliation remain needed.

SHA-256 hashes of installed `account_import.py`, `inventory_service.py`,
`resource_registry_service.py`, and `provider_reconcile.py` exactly matched this
main checkout. Native reconciliation is enabled on this NetBox. Those current
modules place all account stages and the receipt in one database transaction.

## Findings and priorities

1. **Confirmed code blocker, PR #113:** the managed non-superuser importer has
   model-level add permissions for Region/Site, but permission checks on unsaved
   instances return false. The Selectel writer used that failing check. Correct
   creation validates the model grant and then enforces object constraints on the
   provisional saved row inside an atomic savepoint. Constraint denial rolls back;
   no broader permission is granted. Disposable NetBox CI passed the native and
   constrained-permission scenarios. This does not prove the cause of the old runs.
2. **Confirmed result/UI bugs, PR #114:** empty or wrong-account import responses
   could become completed; known Guard refusal was presented as uncertainty;
   configured credentials looked ready, and uncertain accounts had an enabled
   collect button despite backend refusal. Regression tests reproduce these cases.
3. **Confirmed collection bugs, PR #115:** malformed next links escaped partial
   reporting, invalid page limits could look complete, and Retry-After was ignored.
   Keep partial evidence and honor bounded backoff without retrying Guard writes.
4. **Not established as current configuration failures:** invalid Selectel password,
   missing product permissions, incorrect importer token or hidden projects. No
   fresh provider calls were made, and no secrets were inspected in chat output.
5. **Still acceptance work:** explicit account plan/review, durable read-only receipt
   reconciliation, full permission/coverage testing, real identity/collision cases,
   repeat import without duplicates, and independent NIC/port evidence. Existing
   checks forbid name-only adoption; real-account completeness remains unproven.

## Next acceptance boundary

Review/merge the independent PRs only with operator approval. Pin a merged full
commit and use `deploy/update_test.py` with a verified backup for Sync. PR #113
changes Guard and needs a **separate approved NetBox/Guard update**; the Sync updater
does not install it. Keep all schedules off, including bootstrap's Selectel loop.

Before an authorized import, reconcile the old runs and establish idle state,
actual importer token ownership/permissions, Guard version and intended native
changes. A fresh collection currently also writes, so it is not a diagnostic-only
button. Test repeat/idempotency, partial reads, permission refusal, ambiguous
identity, native placement, management/primary IP preservation and ESXi/Proxmox
VM/LXC/pfSense coexistence. Successful isolated tests do not accept Selectel.
