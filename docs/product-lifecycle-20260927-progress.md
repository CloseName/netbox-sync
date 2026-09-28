# Product lifecycle rework — local acceptance evidence

Base: `49a3b95b74494ff8ebcf7455587141b19f733772`, canonical `main`.
Task: attachment `3bf59d58-b945-4cbc-a720-3100d4f59264`.
Evidence updated 28 September 2026. No live remediation is claimed.

## Final local acceptance — 28 September 2026

This section supersedes the chronological intermediate/pending notes below.
The complete production lifecycle/upgrade/Sync-only reinstall scenario passed
with real NetBox 4.7/PostgreSQL and synthetic ESXi SOAP/Proxmox HTTPS providers.
No user installation or external NetBox was accessed. No backup/dump was created.

| Original requirement | Implementation and executed evidence |
| --- | --- |
| Atomic registration and useful refusals | Reservation + immutable intent transaction; placement preflight; typed Guard refusal; PostgreSQL rollback/concurrency and complete public API registration |
| Automatic continuation | 0015 durable jobs, exact broker attestation, actor/nonce binding; real API restart during cluster refusal completes one cluster/source without another final POST |
| Complete deletion | 0014 constrained purge plus 0015/0016 dependent-row cleanup; real broker credential deletion and NetBox ownership closure; foreign/shared resources and external audit retained |
| Wait for existing work | 0016 durable Admin consent, schedule pause, row-locked admission fence; production active PLAN/removal/lifecycle restart; unit/PG active-write and uncertain-outcome refusal |
| Same-host re-add | Full source removal followed by new registration, manual apply, unchanged replan and removal, through public API |
| Conflicting AM IP/MAC | Seven-VM SOAP fixture with all supplied AM IP cases; actual plan/apply and zero-change replan; observation/strict/ownership/VRF coverage in targeted regression suites |
| Proxmox completeness | Production VM/LXC manual plan/apply, unchanged plan, real scheduled no-op and complete removal |
| One-time integration rights | One namespace grant per installation, multiple sources and providers; no per-source permission edits; foreign namespace refusal covered separately |
| Container simplification | 12 to 10 permanent containers; 5 real supervised-bundle/cross-UID tests; actual Compose models 10 standalone / 10 external ingress / 9 external DB |
| Ordinary UX | Automatic attempt status and removal progress; 81 affected browser cases, 88 UI unit cases; precise EN/RU admission errors and unchanged auth checks |
| Upgrade | Exact f6d297f image to current implementation through installer components; unchanged DB container/mounts, secret hashes, policy, onboarding, sources, history and installation identity |
| Sync-only reinstall | Inventory ownership checks, removal of only fixture-owned Sync resources, fresh namespace/DB/enrollment, retained separate NetBox/TLS, same-host add/apply/no-op/schedule/remove |

Executed commands and test selections for the final diff:

- `NETBOX_SYNC_FULL_LIFECYCLE=1` with `tests/run_retirement_production_worker.py`:
  complete production ingress/API/manual/scheduled/upgrade/reinstall sequence PASS.
  Final real-NetBox/production-bundle/broker/PG full-purge regression also passed
  (1 test, 73.25 seconds); complete harness exit status 0.
  Only its nonprivileged isolated operator helper receives Docker socket; product
  Compose never receives it. Fixture project: `netbox-sync-retirement-408d42ebad25`.
- 181 affected Linux/PostgreSQL regressions passed: removal queue, registration
  jobs, purge, retirement journal/continuation, source lifecycle, migrations,
  catalog creation, Operator registration and discovery transport/API.
- 113 identity/namespace/installer/inventory checks passed. Four opt-in supervisor
  skips replaced by all 5 explicit Linux bundle tests passing; the Docker-CLI
  skip replaced by actual host Compose validation. These are accounted-for
  environment skips, not silent acceptance gaps.
- 15 real PostgreSQL deployment/grant tests passed, including immutable registration
  payload and narrow queue/job permissions, without generic runtime DELETE.
- 95 Linux first-run/discovery/authorization regressions passed after the last
  status-gate fix. Real Bootstrap lock contention returns temporary unavailability,
  not false unfinished setup. Status-only POSTs retain session/role/actor checks
  while avoiding the Bootstrap write-admission lock.
- 81 affected Playwright tests and 88 UI unit tests passed; TypeScript, Vite and
  Docker production image build passed. Existing large-bundle advisory remains.
- Docker desktop-linux, Engine 29.7.2, Compose 5.5.0. Tested image manifest:
  `sha256:8b8c3052ba7a5581c2ef05f3a6e9c95f2eb9fd71dc3c16149a4ed00d1d7e78a8`.

Integration failures found and corrected before acceptance: lost first UI status
response due to reference comparison; pending-removal transport code discarded;
Bootstrap busy misreported as unfinished setup; read-only continuation status
unnecessarily dependent on the Bootstrap exclusive lock. Full gate rerun, not
just component tests, verifies these corrections together.

Limits: providers are controlled realistic fixtures, not live hypervisors. Real
host systemd startup/reboot was not exercised in a container; generation/installer
unit checks and the actual scheduled container entrypoint were exercised. The
full runtime upgrade starts at f6d297f (already bundled); legacy 12-to-10 transition
has installer regressions, not a claim of a live upgrade. Browser tests use fixtures;
production public API/worker/NetBox scenarios are an additional independent gate.
External Guard must be updated separately by its operator to the matching code
and once-per-installation permissions before new registration. Existing unproved
ownership is not fabricated; unknown writes still block deletion. Never-stored
credentials require re-entry. These safety limits are explicit product behavior.

See [Sync-only reinstall](sync-only-clean-reinstall.md),
[service boundaries](worker-bundles-and-continuation.md), and
[one-time permissions](guard-installation-permissions.md).

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


2026-09-28 continuation from f6d297f (in progress, not accepted/published):
- Added immutable durable registration jobs (0015), lifecycle attestation of
  deterministic broker-owned references, API restart continuation for both
  providers without retaining credentials in DB or needing a browser session.
  Missing pre-staging secrets require explicit re-entry; no invented credentials.
- Exact unknown cluster intent uses GET receipt first; only REQUEST_NOT_FOUND plus
  the Guard idempotent_creation capability permits identical nonce/wire replay.
  Ordinary catalog reconciliation remains read-only. External Guard update is a
  separate operator prerequisite, never executed against the user installation.
- Added confirmed removal queue (0016): pause new work, wait for admitted work,
  reconcile expired read-only operations only after their owner lock is free,
  refuse unknown/partial writes, permit evidence reconciliation and reviewed retry.
- Executed 160 targeted Linux/PostgreSQL regressions, 14 real deployment-role
  tests, 87 UI unit tests and TypeScript successfully. Two initial test failures
  were tuple-vs-list empty collection expectations, corrected before full rerun.
- Real NetBox 4.7 + production Compose bootstrap bundle/broker + PG full-purge
  gate passed, 72.14s. Old harness omitted Redis, causing fixture errors; added
  a uniquely labelled tmpfs Redis with no persistence in the isolated namespace.
- Exact f6d297f baseline and prepared production images built successfully.
- Full public ingress/API/real-NetBox AM/manual/scheduled/remove/re-add and
  upgrade/reinstall harness is being executed; not yet passing. No live actions,
  backups/dumps, publication or external NetBox changes.
- Latest row-lock strengthening in migration0016 and UI refusal explanation need
  final rerun/build. Whole original task still ACTIVE; do not report completion.


Further integration review (still in progress):
- 181 affected Linux/PostgreSQL tests passed, including the queue row-lock race,
  registration restart, immutable intent, purge rollback and discovery transport.
- 113 additional identity/namespace/deployment/inventory checks passed. Five skips
  were four opt-in bundle cases and one Docker-CLI-in-runner case. Replacement:
  all five bundle tests passed in an explicitly isolated init container; actual
  host Compose models passed standalone/external-ingress/external-DB (10/10/9).
  The bare bundle test now creates the same root:root 0755 socket volume roots as
  Docker; product socket permissions/capabilities are unchanged.
- 81 complete affected Playwright scenarios and 88 UI unit tests passed. A real
  selected-attempt object-reference race discarded the first automatic status
  response; comparison now uses source/registration identity.
- 39 real API AuthPolicy checks passed, including new queue/status routes: Admin
  only; Operator/Viewer denied before the lifecycle transport is called.
- Production integration found pending-removal admission codes discarded by the
  discovery client/API mapping. Preserve exact SOURCE_RETIREMENT_PENDING and
  SOURCE_ARCHIVED as HTTP409; UI renders closed EN/RU messages, never remote text.
- Repeated full rehearsals must have their own empty NetBox database. Reusing a
  failed fixture correctly triggered host name/ownership adoption refusal. The
  full harness now creates its own uniquely labelled tmpfs PostgreSQL and removes
  only its own resources; it never clears an existing NetBox database.
- Full gate not yet complete; final publication remains conditional on it.

- A full isolated gate reached the final fresh-install removal after passing AM,
  scheduler, upgrade preservation, automatic registration after API restart,
  full removal/re-add and Proxmox VM/LXC. Final status polling exposed a second
  product defect: middleware labelled any unavailable Bootstrap status as
  BOOTSTRAP_NOT_READY. Real READY-file lock contention now reproduces the issue;
  temporary BUSY/unavailability returns fail-closed HTTP503, while confirmed
  non-READY remains HTTP409. Polling retries only status, not removal writes.
  The 94 Linux bootstrap/discovery/authorization regressions all passed.
  A new complete gate with this correction is running; no final success claimed.
