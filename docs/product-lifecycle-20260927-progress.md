# Product lifecycle rework — active, NOT accepted as complete

Base: `49a3b95b74494ff8ebcf7455587141b19f733772`, canonical `main`.
Task: attachment `3bf59d58-b945-4cbc-a720-3100d4f59264`.
Evidence updated 28 September 2026. No live remediation is claimed.

## Restrictions

No live access/deployment, no external NetBox changes, no backup/dump/restore
creation or restore-test containers for this disposable acceptance environment.
This is a test-environment exception, not a production backup policy.
Docker: desktop-linux, Engine 29.7.2. Operator disk location:
`E:\Docker\DockerDesktopWSL`; no virtual disk operations performed.
Existing resources were preserved. The real-NetBox harness removes only its own
uniquely labelled temporary resources, with label checks. No global cleanup.
Ordinary commit/push authorized after the mandatory complete-product gates.
Publication of an incomplete lifecycle replacement is not an acceptance result.

## Implemented and reproduced

- Before correction, legacy placement refusal left a host reservation without an
  intent (real PostgreSQL regression: expected zero, observed one). Placement is
  checked before reservation, and the reservation plus validated durable intent
  now commit in one transaction. A failure during intent persistence rolls both
  back. Exact retries keep the original binding; changed requests are refused.
- Resolved placement is also checked during the settings step and again against
  the actual server-selected site before optional remote creation.
- A proven Guard refusal after dispatch used to become UNCERTAIN. The reproduced
  structured 403/PERMISSION_DENIED now stays REFUSED; an explicit identical
  registration retry can correct its permissions. Lost responses remain uncertain
  and receipt-only. Historical ambiguous journals are not relabelled as refusals.
- Per-account/per-tab non-secret draft survives reload for eight hours, including
  provider, endpoint, port, TLS selection, display name, selected site and request
  identity. It does not store credentials, tokens or inventory. Explicit discard
  and completed registration clear it. Placement references are read afresh.
- New registration mappings explicitly select observation policy. Existing strict
  source policies remain unchanged. Disputed IP and MAC assignments preserve VM
  inventory and interface observations, without assigning an arbitrary owner.
  Foreign/unassigned MAC records are not adopted. Existing assignments remain.
- Strict MAC conflicts have a typed public conflict; observe mode reports excluded
  MAC assignments in the plan. `network_complete` supplements `ipam_complete` so
  a MAC-only observation cannot produce a misleading complete result. EN/RU copy
  distinguishes inventory completion from incomplete network assignments.
- Planner version advanced to web-5a-7, invalidating old prepared plans.

## Evidence actually executed

1. Linux/PostgreSQL selection: **357 passed**, no skips:
   `test_onboarding`, `test_onboarding_security`, `test_onboarding_postgres`,
   `test_api_sources`, `test_api_sources_postgres`, `test_inventory_conflicts`,
   `test_apply_worker`, `test_first_sync`, `test_ip_observations`,
   `test_network_scopes`, `test_esxi_runtime`, `test_registration_continuation`,
   `test_catalog_creation`, `test_host_registration`, `test_operator_registration`,
   `test_retirement_transport`.
2. Playwright: **95 passed**, entire add-source-wizard, source-placement and
   sync-workflow suites. Includes EN/RU, light/dark, narrow screens, reload,
   expired authentication, duplicate submission, and stale/lost-response states.
   The first run exposed an obsolete placement fixture returning `sources` for
   registration-attempts; fixed to the real `attempts` contract, then reran all 95.
3. UI unit suite: **86 passed**, including the draft-whitelist regression.
   TypeScript/Vite passed; git diff --check passed.
4. Actual NetBox 4.7.0 HTTPS/DRF/models, PostgreSQL and production Compose
   retirement-worker: **1 integrated test passed** (69.64 seconds). This runs
   `tests/run_retirement_production_worker.py` with the isolated lifecycle PG
   fixture and `netbox-sync-lifecycle:20260927-final` retirement image. The
   changed plan/apply code is mounted read-only into the test runner. This is
   NOT a fresh product-image/browser/worker acceptance for the whole new task.
   It covers all exact AM IP facts, seven distinct VMs, a cloned MAC, interfaces,
   CPU/memory/aggregate disk sizes, observations, zero-create/update replan,
   explicit existing VRFs, and exact guarded deletion with generation closure.
   The retirement image is unchanged from the base; its Sync finalization still
   retains history. No new full-purge guarantee follows from this test.
5. Actual NetBox model validation: separate existing VRFs accept the same address;
   enforced-unique same VRF refuses equal/different masks. No invented VRFs.
6. Standalone/external production Compose models validate. Standalone proxy owns
   80/443; external publishes no ports. Broker remains networkless; API/DB/workers
   expose no host ports. External config requires the explicit ingress directory.

Provider data is synthetic except the operator-supplied AM names/address facts;
there were no live hypervisor calls. The fixture is shared in
`tests/fakes/am_conflicts.py`. VM disk support remains aggregate size, not separate
VirtualDisk records. No claim of full test-VM acceptance is made.

## Remaining mandatory implementation and gates at ddb3209 (historical)

- Full deletion currently still archives local source/history. Replace it only
  after private filesystem cleanup, exact external completion evidence, atomic
  local purge, and late-registration/worker fencing are implemented together.
- Remove registration/cancellation manual loops; durable background continuation
  after browser closure/restart and historical uncertain refusal recovery still
  require implementation. No automatic replay of an unproved write is allowed.
- Once-per-installation constrained Guard permissions: current tests still grant
  known namespaces. Actor-only permission constraints are insufficient, because
  a newly authored retirement intent does not prove ownership by that actor.
- Container consolidation and supervision remain design work; no Compose service
  removed or merged in these commits. See architecture notes below.
- Fresh no-backup Sync-only reinstall, full lifecycle/scheduler/restart/concurrency
  gates and final clean-install runbook are NOT ready. Do not use this checkpoint
  as permission to wipe Sync or change external NetBox.
- Full task commits/publication only after these gates; do not report completion.

## Container audit and next boundary

At checkpoint ddb3209 the count was **12 before / 12 then**. Current bundles below reduce this to 10. Profiles for one-shot tools
and old stopped test containers are not permanent product components.

| Component | Required boundary / consolidation finding |
|---|---|
| API | DB reader plus constrained Unix clients; no provider/NetBox/bind secrets or egress. Keep separate. |
| Proxy | Optional operator TLS/public edge; only private API socket. Keep optional. |
| PostgreSQL | Private DB network, no published port. Keep separate. |
| Secret broker | Literal network_mode:none; local credential ownership/files only. Keep separate. |
| Auth worker | LDAP egress and bind secret, authentication DB role; isolate from provider/NetBox control. |
| Probe worker | Ephemeral credentials and bounded destination policy; no stored provider/NetBox secrets. Keep separate. |
| Lifecycle worker | DB lifecycle role, shared lock, private broker/retirement clients; no NetBox token/egress. Keep separate. |
| Schedule worker | Two-column DB writer, no credentials/egress. Merging into lifecycle would also expose its private control sockets; not assumed safe. |
| Discovery worker | Provider/NetBox read path, DB/operation roles, bounded cross-UID children. |
| Apply worker | Same network and mounted provider/NetBox directories as discovery, plus run role and shared lock. Candidate common sync service with explicit role selection per operation. |
| Bootstrap worker | Owns NetBox configuration and catalog journals, NetBox egress; no provider/DB credentials. |
| Retirement worker | NetBox-only, read-only configuration, private socket mounted only by lifecycle. Candidate common NetBox-control service, but filesystem ownership and separate peer/socket authorities must remain explicit. |

Candidate target is 10 services, not a committed new topology: common sync worker
and common NetBox-control worker. A correct implementation needs bounded shutdown,
reaping, health per interface, explicit child environment filtering and failure
recovery. Do not simply run shell background jobs or union all service privileges.

Guard remains necessary for atomic creation claims/receipts, exact dependency
closure, object-generation checks and write rejection for closed namespaces.
A read-then-delete REST loop does not provide those guarantees. External NetBox
system audit is not Sync-local purge data. Its generation seals cannot be erased
without a replacement fence against old requests. No Guard update was deployed.

## Saved implementation checkpoints

- `c9bb761`: atomic registration reservation/intent, early placement and confirmed refusal retry.
- `29e582e`: account-scoped non-secret form persistence and placement feedback.
- `55b543b`: safe IP/MAC observations, typed completion and real NetBox AM evidence.

These are local checkpoints, not a completed release. No push or deployment has
been performed for this task. The remaining gates above are still mandatory.


## Continuation checkpoints — 2026-09-28

The preceding remaining-work list describes checkpoint ddb3209, not current code.
The operator explicitly approved a narrowly scoped source-purge SECURITY DEFINER
function, including source-local history/audit deletion. No live work or backups.

Implemented in local checkpoint `5f77d55`, with UI checkpoint `010b9b2`; the full task is still under integration review:
- Migration 0014: exact receipt/generation/credential/file evidence, no active or
  uncertain operations; transactional source-only purge, fixed pg_catalog path,
  lifecycle-only EXECUTE, no generic DELETE. Shared credentials/other sources and
  external audit remain. Registration admission and source assignment are fenced.
- Private NetBox worker verifies the receipt before root-owned source journal
  cleanup; symlink/hardlink/permission/mismatched pointer checks fail closed.
  Missing final HTTP response resolves from the exact external closed receipt.
- Confirmed removal continues from its durable journal after restart. No automatic
  approval of READY reviews and no blind re-dispatch of an unknown remote write.
- Supervised NetBox and sync bundles replace two permanent containers (12 to 10),
  preserve socket peer boundaries, filter child DB-role environments, bound
  cross-UID termination, and expose socket health. Legacy services are opt-in
  profiles; installer removes only its own old Compose services on upgrade.
- Per-installation source namespace and once-only Guard permission generator.
  Requires the new read-only Guard source_namespace_state capability. External
  NetBox operator must separately review/update the plugin; no live update here.
- Removal UI polls automatically and returns to source list after full purge.

Evidence so far (not final acceptance of the entire task):
- 48 Linux/PostgreSQL lifecycle, continuation, archive compatibility, migration,
  namespace regressions passed after correcting fixtures to use broker-owned keys.
- 13 additional source-purge/filesystem tests passed: rollback after late SQL
  failure; partial shared pair; broker refusal/retry; untrusted legacy file path;
  exact file cleanup, symlink/hardlink/mode/pointer refusal and interrupted cleanup.
- 14 actual PostgreSQL deployment-role/grant tests passed in a newly isolated DB.
- Earlier bundle/continuation/deployment selection: 72 passed, 1 skip.
- Real NetBox 4.7 HTTPS + PostgreSQL + production NetBox bundle: 1 gate passed,
  69.94s. Full source purge, repeated completion, AM observations and no-op plans,
  once-only prefix permissions and outside-prefix denial. Image was built before
  the last credential cleanup/UI edits; rebuild and final gate remain mandatory.
- UI: 86 unit tests and TypeScript/Vite passed before the latest copy/client test.

Still mandatory: finish durable registration continuation (including Proxmox),
active-operation removal waiting, final late-writer race audit, whole UI suites,
full production API/manual/scheduled/upgrade/reinstall gates without backup/restore,
Sync-only reinstall procedure, final review, logical commits and ordinary push.
No claim that all original requirements are complete. The original checkpoints
are preserved; publication is still deferred until the remaining product gates.

Latest executed evidence:
- Expanded Linux selection: **368 passed, 1 skip**. The skip is
  `test_deployment_foundation.py::test_canonical_compose_renders_without_provider_configuration`:
  no Docker CLI inside the test runner. The actual host Docker Compose models
  were separately validated for standalone, external ingress and external DB;
  counts 10/10/9, proxy ports 80/443 only in standalone, exact tmpfs, no backend/DB
  published ports, broker network_mode none. This skip has replacement evidence.
- A dict-row admission-lock result initially caused four API registration failures.
  Corrected tuple/dict handling; the expanded selection above passed afterward.
- **14 deployment-role tests passed again** on a new uniquely labelled tmpfs
  PostgreSQL, including migration 0014 and lifecycle-only purge grants.
- **56 targeted DB/lifecycle/inventory tests passed**, including late scheduler
  history INSERT refused after purge and atomic rollback of intermediate deletes.
- **34 durable-lifecycle Playwright scenarios passed**, including EN/RU narrow
  automatic removal status across reload; **2 saved-registration polling tests
  passed**, no browser retry of the registration POST; **87 UI unit tests passed**.
- TypeScript and Docker production build passed with the current UI/backend.
  Existing Vite bundle-size warning remains (about 755 kB before compression).
- Strengthened real NetBox 4.7 gate **passed (72.91 s)** after an earlier fixture
  correctly failed full purge because it used an unproved absolute legacy secret
  path. The fixture now creates ephemeral credentials through the actual product
  broker as API UID10001, uses real root-only cleanup transport, proves the file
  absent, and keeps broker network_mode none. This is stronger than replacing the
  callback with a successful mock. Full-purge repeat, new host reservation,
  ESXi/PVE real-model AM observation/no-op scenarios remain covered.
- `git diff --check` passed. No backup/dump/restore containers or live actions.

The read-only `deploy/reinstall_inventory.py` and draft
`docs/sync-only-clean-reinstall.md` preserve external NetBox and /etc TLS, reject
foreign volume/network consumers and external-DB reset, and never execute
cleanup. The clean reinstall acceptance gate is still NOT executed.

Precise next implementation work (not an authorization blocker):
1. Durable registration completion after API/browser restart. Current server
   journal preserves ESXi intent, but credentials are initially ephemeral and
   Proxmox lacks the equivalent durable intent. UI now automatically reads state;
   that is not proof of server-side completion. Persist a bounded approved job
   with metadata/opaque secret references, preserve existing role boundaries,
   and reconcile guarded cluster creation before final registry insertion.
2. Confirmed removal waiting for ordinary active operations: current guards
   correctly refuse active/uncertain writes; automatic waiting/admission pause
   remains to be implemented without relabelling an unknown apply as safe.
3. Upgrade/fresh reinstall and complete production API/manual/scheduled/browser
   gates for both providers, with actual consolidated service topology. Do not run
   the default auth Compose harness backup/restore branch for this task.
4. Rebuild/rerun bundled runtime after the bounded-busy health correction below.
5. Final product UX/old administrative paths review and then ordinary push.

External deployment prerequisite: the NetBox operator must independently install
matching Guard code supporting source_namespace_state. No NetBox update is
performed or authorized here. This is separate from the unfinished local gates.


Bounded-busy health correction: the serial apply socket can be occupied during
its existing 300-second child budget. Root-owned ephemeral PID/start-generation/
monotonic-time evidence permits only this known busy case, for at most 330 seconds
including DB/cleanup overhead. Missing, expired, malformed, linked, foreign-mode,
wrong-generation or exited-process evidence fails health. The execution timeout,
shared apply lock, confirmation store and network/capability boundaries are
unchanged. No credentials/source contents enter this marker. Source process
supervision still terminates the whole bundle immediately when a member exits.
