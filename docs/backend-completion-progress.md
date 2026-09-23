# Backend completion / 2026-09-22

Active user request: attachment 4a49ceb3-d1c9-4190-9d49-472750357d2d plus
item 12 (duplicate physical source registration). Base 3bb567ce493486a02fc36db495d91e7c151aff48.
Existing work preserved. User permits publication only after completion and successful
checks. No publication or deployment has occurred in this iteration.

## Initial implementation notes (historical checkpoint)

- PLAN: omit unused preliminary NetBox review; cache complete remote endpoint reads
  only inside a fresh PlanningNetBox instance. Never cache nested mutable overlays or
  failed partial pages. Next plan is fresh. Added bounded metadata phase timings for
  mapping/review/simulation; 120-second deadline and termination remain unchanged.
- HTTP fixture now returns real pagination links, rather than claiming a truncated
  page is complete. A 276-VM ESXi HTTP test verifies no duplicate GET selections,
  full NIC/IP inventory, no-op plan and a changed digest after a real remote change.
- ESXi host registration: draft migration 0007_host_reservations stores a hardware
  UUID reservation with source ID, actor and request nonce BEFORE catalog or secret
  writes. PostgreSQL serializes competing reservations. Pending reservations do not
  expire automatically after possible remote side effects. Tombstoned source rows
  retain identity. Missing legacy hardware identity blocks new registration pending
  review. ESXi preview=false cannot bypass hardware collection. DNS/display names,
  IP and local ha-host MoRef are not identities.
- Initial API and EN/RU errors include a validated existing-source link. New grants
  allow only registration SELECT/INSERT on reservations; backup schema/head updated.

These are work in progress, NOT a completed item 12 or a deployable release. Still
required: migration/backup/restore/production Compose integration; legitimate legacy
identity refresh; existing duplicate execution guard; recoverable reservation lifecycle;
full HTTP/browser positive registration; provider identity support for Proxmox;
operator reconciliation of duplicate sources. Do not publish this checkpoint.

## Checks actually executed

- 33 initial facade/first-sync/observation tests passed.
- 276-VM real HTTP suite: 8 passed, including fresh remote change detection.
- API/RBAC onboarding: 49 passed.
- Host reservations: 9 Linux/PostgreSQL tests passed (concurrent requests, durable
  retry, old/removed rows, missing identity, API refusal before cluster/secret writes).
- Broader Linux selection: 126 passed, 5 deployment tests skipped, 1 assertion failed
  because the expected migration HEAD was still 0006. The expected HEAD was updated
  to 0007; full selection must be rerun. The 5 skipped deployment tests were then run
  explicitly in a separate disposable DB and passed. A new narrow-grants test is
  added but not yet run.
- Frontend: 74 unit tests passed; TypeScript passed. An initial new TypeScript
  parameter-property syntax was incompatible with strip-only Node tests; corrected
  and the entire unit suite rerun successfully. Browser gates remain pending.

## Live read-only inspection (not acceptance of a fix)

On 22 September around 11:12-11:16 MSK, the existing authenticated UI displayed two
ESXI-INFRA records at the same DNS name. Both automatic schedules were OFF when read;
configured intervals were 10 and 5 minutes. Cluster labels differed in case
(ESXI-INFRA / ESXi-INFRA); this does not prove equal NetBox cluster IDs. One source
had no runs; the other had a blocked scheduled run. A single read-only Discovery was subsequently attempted for the second source; it
ended in DISCOVERY_TIMEOUT at 11:39:02 MSK, event
2fc4b259-9d88-4feb-8359-94c9a9353a18. No apply, configuration write, deletion,
credentials extraction or live NetBox query was performed. Hardware identity,
object ownership and credential ownership remain unverified. A later read-only
browser navigation to the first source placement endpoint was refused with
ERR_BLOCKED_BY_CLIENT (no reason supplied); it was not bypassed. Do not infer
physical-host identity from these labels/address alone.

## Full requirement matrix (not completed)

| Requirement | State / remaining gate |
| --- | --- |
| 1 NetBox retirement | NetBox-side claim/manifest/receipt transaction service and actual deletion/rollback/concurrency tested locally. NetBox HTTP and private Sync transport tested; product lifecycle coordinator, legacy claims and rollout remain missing; source removal is still retain-only. |
| 2 Orphan reconciliation | Durable authoritative reconciliation/periodic executor missing. |
| 3 Remove/re-add/recover | Bounded Admin ESXi same-namespace recovery, including verified legacy UUID/placement, implemented/tested. Proxmox and cross-namespace transfer remain unfinished. |
| 4 Cluster creation | Live cause unconfirmed; previous controlled test is not reproduction. |
| 5 IP scopes | Explicit existing-VRF guest mappings and preserved foreign/scope-change observations implemented and locally tested. Host-management VRF and automatic binding migration remain unsupported; MAC ownership safeguards remain. |
| 6 PAM VM identity | Still ambiguous; no identity schema changed or conflicts bypassed. |
| 7 CM uncertain run | Reconciliation state machine missing; do not replay old writes. |
| 8 PLAN latency | Confirmed redundant reads reduced locally; live root cause not established. |
| 9 AD/RBAC | Earlier fixture evidence only; fresh Microsoft AD acceptance pending. |
| 10 Reauthentication | Real API/auth-worker proof expiry, incorrect password, retained session and explicit retry passed locally. Original live logout cause remains unconfirmed. |
| 11 Apply response loss | Actual accepted HTTP disconnect with durable success/uncertain result, same run/digest, browser reload and worker restart passed in bundled/external production Compose. Live reproduction remains unperformed; physical partial-write fault passed in the continuation below. |
| 12 Duplicate hosts | UUID admission/reservations, same-attempt continuation, proven legacy identity and read-only Admin audit implemented locally. Live ownership of the two ESXI-INFRA records is still unproved; no deletion/transfer chosen. Proxmox identity admission is not included. |

## Isolated resources

Docker desktop-linux / Engine 29.7.2. Initial inventory: 15 stopped older rehearsal
containers, 55 volumes, 38 images; no ownership/obsolescence proof, none removed.
E drive free about 414.9 GB. VHD files untouched; desktop disk location not independently
verified yet. Do not repeat global cleanup.
Current disposable PostgreSQL: netbox-sync-host-claims-af62ff5f8b15414ea2872461211eb842,
label netbox-sync.task=host-claims-20260922, network none, data tmpfs, no named volume.
It exists solely for current tests; remove only after verifying that exact label.


## Continuation evidence — 22 September

- Preserved HEAD 3bb567ce493486a02fc36db495d91e7c151aff48 and all existing edits.
- Known duplicate recorded ESXi hardware UUIDs now block both manual apply-worker
  source loading and registry-backed scheduled execution. No source is selected as
  the winner and no historical records are deleted. Rows lacking recorded hardware
  evidence still require a separate identity review; the runtime guard is not a
  live inventory of every registered server.
- 11 host-reservation tests passed on Linux with real PostgreSQL. They include
  actual API/RBAC final registration concurrency with two receipt-bound transport
  addresses and the same UUID: exactly one source/credential pair, safe 409 for the
  loser, and no extra pair on replay of the successful request. Only the external
  catalog and credential filesystem adapter are faked in this API regression.
- Production Compose bundled gate passed in 171.98s; external PostgreSQL gate
  passed in 161.07s. Both use image netbox-sync-ux:host-reservations-20260922,
  actual production services, controlled SOAP/HTTPS peers and the existing worker,
  browser and populated upgrade scenario. New initial-probe duplicate check passes.
  This is not evidence of live ESXI-INFRA identity or ownership.
- The initial Compose failure correctly exposed a fixture identity collision:
  auth-test and the subsequently replaced full-sync peer reported the same hardware
  UUID. The test now explicitly verifies that duplicate is refused before replacing
  it with a distinct physical host; both preview summary and batched hardware
  properties report the new peer UUID consistently. No product guard was bypassed.
- Updated backup fresh-restore exact DDL expectation for the new reservation table:
  48 passed, 1 platform skip on Windows; Linux verification is recorded separately.
- Earlier in this iteration: frontend unit 74 passed, TypeScript/build passed,
  complete add-source wizard browser set 20 passed. No new product edits followed
  the image build; subsequent changes only strengthened fixtures/evidence.

### Item 12 limitations before publication

The reservation draft covers ESXi hardware UUIDs, not a verified durable Proxmox
cluster identity. Pending reservations deliberately do not expire: a cluster write
may already have happened. Administrative reconciliation of abandoned reservations,
legacy identity acquisition, and the agreed removed-source recovery flow are still
unfinished. Tombstoned sources retain their UUID and cannot be bypassed by a fresh
registration. A successful recovery test must be added when that flow exists;
current refusal tests are not a substitute. Do not publish this draft as completion.

### Safe existing-duplicate reconciliation order

1. Obtain the two stored provider UUIDs and current verified provider UUID without
   credentials, plus exact source IDs and NetBox site/cluster IDs. Names, address,
   DNS results and cluster label case do not establish identity or equal placement.
2. Read source-scoped NetBox provenance for hosts/VMs/interfaces/IPs, retained run
   history and lifecycle/uncertain-operation state. Obtain only reference ownership
   metadata (exclusive/shared), never credential contents.
3. If UUIDs or placement differ, retain both histories and report that specific
   conflict. If either source has uncertain writes, reconcile those before mutation.
4. Only after ownership is proved, propose an explicit administrator-selected
   canonical source and recovery plan retaining NetBox IDs and manual attributes.
   No generic DELETE or reassignment by display name is permitted.
5. Fence any approved transition with the shared apply lock, source revision and
   fresh ownership checks. Preserve history and shared credentials. Verify result
   before enabling a schedule. This transition is not yet implemented or executed.

Latest verification: affected Linux suite 166 passed without skips; expanded host
reservation suite 16 passed (including five post-probe address variants). The address
variants inject trusted probe evidence and do not claim real alias DNS/TLS coverage.


## Continuation — 23 September (supersedes earlier draft descriptions)

Preserved HEAD 18f48693f01ce0fcac1f413f2b25732fdc4d3a45 and all existing edits.
Docker desktop-linux / Engine 29.7.2 verified with authorized access. The old
host-claims test container was absent; a new uniquely named tmpfs-only PostgreSQL
was created with label netbox-sync.task=host-claims-20260923. No older resources,
volumes or VHD files were removed.

Implemented Admin-only same-namespace ESXi recovery with durable lifecycle journal,
root-only broker ownership metadata, unchanged NetBox IDs/history, scheduling off,
and UI confirmation/status reconciliation. Latest additional hardening rejects
incompatible object identity kinds and distinct objects sharing a provider identity;
exact repeats of one provenance fact are normalized. Final registration now holds
an advisory lock across side effects, not just the reservation INSERT.

Executed this continuation: 26 evidence/catalog tests; 58 Linux recovery, lifecycle,
identity and migration tests; 56 Linux registration/API/RBAC/catalog tests after the
new registration lock; 7 real deployment/grants tests. TypeScript/Vite passed in
Docker build netbox-sync-ux:host-recovery-20260923, manifest list
ac32d2552776d49c22f957e7842c3ae076bf86b523329423abd9d9fbd8c3abc3.
The two latest production Compose gates are still running at this checkpoint.
Earlier bundled production recovery cycle passed; do not substitute it for the new
image's final result. See host-identity-registration.md for exact supported recovery
and remaining limitations. No live identity/ownership conclusion has been added.

Still unfinished: abandoned-registration resume/release, legacy hardware identity
acquisition, cross-namespace duplicate remediation and Proxmox recovery. The other
original backend requirements remain as stated in the matrix except that item 3 now
has the bounded ESXi recovery flow described above. This is not completion of all
12 requirements and is not authorization to deploy.


### Final review checks for this checkpoint

- Combined affected Linux suite: **430 passed, 1 deselected**, no skips. The sole
  deselected Compose-render test passed separately on the Windows Docker host.
  Real PostgreSQL migration/grants, registration concurrency, source lifecycle,
  broker transport, backup/restore and manual/scheduled adapter tests are included.
- Frontend: **74 unit tests**, **22 complete wizard browser tests**, TypeScript and
  Vite build passed. Browser fixtures are distinct from production worker evidence.
- Actual pg_dump/pg_restore preserves reservation/recovery records. Fresh restore
  rejects orphan claims even with zero sources; restored-source credentials enter
  manifest validation; old schemas without restored_at remain supported.
- Production Compose bundled/external: **2 passed in 396.04s** on
  host-recovery-20260923; **2 passed in 482.28s** on host-recovery-final-20260923.
  Both include controlled ESXi/Proxmox worker scenarios and the API restoration
  cycle. The later source-link/nonblocking-reservation fixes have an additional
  18-test actual PostgreSQL/API run and a fresh reviewed image.
- The first reviewed-image smoke failed before runtime: it overlapped a still
  running smoke using the same explicit fixture subnet 93.184.216.0/24. This is a
  test orchestration collision, not product acceptance. Cleanup stayed scoped to
  each test project. Sequential reviewed-image repeat passed: **1 passed in 188.50s**.
- Final image: netbox-sync-ux:host-recovery-reviewed-20260923, manifest list
  9fc421ac648e8bae01d4ccb85691bd697910b88b571c8f934bf14435bd5c3370.
- Docker Engine 29.7.2 / Compose 5.5.0 / desktop-linux. No VM access, deployment,
  live writes, image-disk manipulation, global cleanup or push in this continuation.

Do not run two auth_compose_scenario rehearsals concurrently: projects are unique,
but their controlled HTTPS endpoint fixture uses an explicit common subnet. Production
Compose itself is not changed to that subnet; it is a test overlay.


## Saved implementation checkpoint

Implementation/regressions: `d42410b8456dd1d0e973646150fd7f723f0a60ca`.
Existing performance commit `18f48693f01ce0fcac1f413f2b25732fdc4d3a45` retained.
The reviewed image's complete bundled runtime passed after the network collision
was removed by running sequentially. It includes new-source registration, real
manual/scheduled controlled provider paths, same-source ESXi removal/recovery,
unchanged NetBox IDs/write counts/history and no-op replan. External PostgreSQL
passed in the preceding final-image run; the subsequent narrowly changed error-link
and advisory try-lock behavior additionally passed real PostgreSQL/API regressions.
`git diff --check` passed. No live identity/ownership was inferred or modified.

This checkpoint is not completion of the original 12-item backend assignment.
Remaining local implementation is listed above and in host-identity-registration.md.
Do not treat missing live UUID/NetBox ownership evidence as proof that the two
ESXI-INFRA entries represent the same physical server or may safely be deleted.


## Continuation after 8230f83 — registration and identity backend

Preserved commits d42410b/8230f83 and all prepared changes. No live connection,
push or deployment. Docker desktop-linux / Engine 29.7.2 remains available.

Implemented actor/nonce/UUID-bound continuation after uncertain registration,
immutable intent (0008), deterministic broker key and status reconciliation.
Fresh authenticated probe is mandatory after API restart. Added Admin-only legacy
ESXi identity review/confirm and two-source read-only audit (0009). A matching
historically source-owned host is required; neither empty inventory nor matching
names/address establishes ownership. Same source, credentials, NetBox IDs, history
and schedules are retained. Missing legacy mappings require explicit catalog
selection; identity verification does not manufacture them.

Review found a defect in the uncommitted identity proof: rebuilding the digest
from projected IDs discarded the original provenance digest. A regression changed
VM identity while preserving its NetBox ID and reproduced equal digests. Fixed by
chaining the original inventory hash into the configured-placement hash. The
regression now passes; it does not establish any cause of the live conflicts.

Local evidence collected so far:
- 209 affected Linux/PostgreSQL tests passed, no skips (identity, registration,
  recovery, lifecycle, catalog, backup, generation/revision fences and RBAC).
- 113 migration/onboarding/deployment tests passed, 1 Compose-render test deselected
  because the Linux test runner has no Docker CLI; that exact test passed on the
  Docker host. Populated 0007 -> 0009 upgrade and repeat retain old claims/recoveries.
- 11 actual PostgreSQL grant and pg_dump/pg_restore tests passed. Both new journals
  survive dump/restore; runtime roles cannot rewrite/delete their append-only rows.
- Dockerfile.web build passed, including the cached unchanged TypeScript/Vite
  frontend build, image netbox-sync-ux:identity-continuation-final-20260923,
  manifest list d4e80ccc12ce50d14fd3dcc372dac93b6302fefe888dc83545f0313f0d125f85.
- Initial production runtime run reached resume/restart, legacy proof, removal/
  recovery, manual and scheduled ESXi success but then failed its own empty-mapping
  assumption. Server correctly returned CATALOG_SELECTION_REQUIRED. The scenario
  now asserts that refusal and explicitly submits catalog choices before continuing.
  Final bundled/external rerun status is recorded below when available.

The live audit is still blocked by missing identity/ownership evidence; no approved
read-only route has been used to bypass the previous ERR_BLOCKED_BY_CLIENT refusal.
See host-identity-registration.md for exact minimal metadata and safe audit calls.
The whole 12-item assignment is not complete. In particular, NetBox retirement,
authoritative orphan reconciliation, IP scope mapping, PAM identity transition,
CM uncertain-run reconciliation and Microsoft AD acceptance are not supplied by
these registration changes. These limits are not claims that all local work is done.


### Final local gates for 766db17

- Final production Compose bundled + external PostgreSQL: **2 passed in 417.38s**.
  Both run actual API/probe/broker/lifecycle/discovery/apply/scheduler processes,
  controlled HTTPS 8443 ESXi and Proxmox (VM + LXC), required-read refusal,
  same-attempt continuation after API restart/DB refusal, one credential file and
  one source, legacy ownership verification, remove/recover, no-op replan,
  observation mode, mappings/revision checks and actual browser workflow.
- Separate final bundled installer upgrade + supported host backup create/verify/
  inspect/fresh restore: **1 passed in 155.49s** (external parametrization excluded
  intentionally for this bundled-only upgrade gate). The runtime worker mode skips
  that baseline branch, so this is an additional executed check, not inferred from
  the preceding workers run. Identity/policy/credential/onboarding state and service
  restoration are checked by the scenario; new journal contents additionally have
  the explicit pg_dump/pg_restore regression described above.
- `git diff --check` and staged diff check passed. Backend/regressions committed as
  `766db17`; original d42410b/8230f83 preserved. No UI implementation changes.
- No live-system access, deletion, reassignment, push, deployment, VHD operations or
  global cleanup. Test cleanup remained scoped to each unique Compose project.

This completes the current local registration-continuation and legacy-proof block,
not the full backend assignment or live duplicate remediation. The next required
ownership evidence is listed in host-identity-registration.md; no source should be
removed until it is available and reviewed. Other outstanding matrix items remain
explicitly open and must not be represented as completed or covered by this smoke.

## Continuation after 367efc2 — scoped IPAM and response loss (in progress)

The full 12-item assignment remains active. Existing commits and checkout are
preserved; no push/deployment/live connection or global cleanup occurred.
Docker desktop-linux, Engine 29.7.2 is available. The initial unprivileged Docker
attempt failed because the sandbox could not read Docker config/access its pipe;
the approved local operator invocation succeeded. This is not an Engine outage.

Implemented explicit existing-VRF rules, safe foreign-address observations and a
minimal EN/RU editor under existing Admin mappings. See network-observations.md.
VM/LXC lookup includes CIDR + VRF; old-client omission retains rules, explicit
removal retains existing IP assignments. Wrong host/revision, changed VRF and
uncertain runs remain blocked. No automatic VRF creation or MAC ownership bypass.
Planner version web-5a-6; rebuild existing plans. DB head remains 0009.

Executed so far:
- 143 related Linux/backend/real-PostgreSQL tests passed, including SDK-over-HTTP
  ESXi and Proxmox VM/LXC plan/apply/no-op replan and preserved foreign IPs/data.
- 39 complete directory authorization tests passed after adding actual HTTP
  Admin/Operator/Viewer enforcement for the VRF update payload. Test transports
  still simulate AD; this does not constitute Microsoft AD acceptance.
- 74 frontend unit tests, TypeScript, 31 Source Detail and 33 Sync workflow browser
  tests passed. EN/RU narrow-screen explicit VRF review/save tested.
- NetBox Community 4.7.0 image (digest
  1685e91c61bb4050089db2bb1603718820ae3ce0b266d4d069ff7c682f5d9c58): real Django
  migrations + IPAddress.full_clean/save against a dedicated isolated test DB.
  Two VRFs accept the same address; equal/different masks within an enforced VRF
  refuse. Model-test writes roll back. The first cold migration run was stopped
  while investigating duration; the bounded repeat completed successfully.
- Initial production bundled/external workers, scheduler, browser and populated
  upgrade: 2 passed in 444.84s using scope-continuation-20260923. This image predates
  the final foreign-existing-address projection; final repeat is required below.
- Final local image scope-final-20260923 built successfully (TS/Vite included),
  manifest list 562e4cbf78f96b33ef37f8b6203290d7637c103eb250a69a51250040927cdfd0.
  Final bundled/external repeat is running and additionally drops the actual
  accepted ESXi HTTP connection before a controlled failed remote write.

Response-loss gate now deliberately holds a real outbound write while the API
persists RUNNING and its digest, disconnects the original Unix HTTP client, reloads
the real browser, releases the controlled peer, reads the same terminal run and
restarts only the test-owned apply-worker. Proxmox success gate passed in the
initial production repeat: exactly one sync POST, same run/digest across reload
and worker restart. ESXi uncertain terminal after actual HTTP loss is added to the
final repeat; no source status is reset and no write is replayed.

This is not completed retirement/orphan reconciliation, Proxmox host identity
admission, PAM identity transition, CM historical-result reconciliation, or live AD
acceptance. No claims about live ownership or a live root cause follow from these
local tests. Those items still require implementation/evidence, not relabelling the
remaining work as already covered by this network/runtime block.

### Completed local VRF/HTTP-loss gates

- Final scope-final-20260923 production Compose: **2 passed in 429.41s**. Bundled
  and external PostgreSQL, actual provider/read/apply/scheduler workers, controlled
  HTTPS/SOAP endpoints and browser. Explicit VM/LXC VRFs survive populated installer
  upgrade with identical source rows, credentials/config/READY/policy and exact DB
  container/volume metadata. Shared lock, broker network:none, private API/DB and
  ordinary auth requirements remain unchanged.
- Real ESXi HTTP disconnect after durable RUNNING + digest, controlled remote
  refusal, matching OUTCOME_UNCERTAIN, worker restart, old-token/fresh-plan write
  refusal, retained lifecycle/diagnostic evidence. Proxmox success after actual
  disconnect and browser reload: same run/digest, exactly one POST; worker restart
  retains stored outcome. This does not prove the old live CM run's result.
- Complete Source Detail + Sync workflow combined repeat: **64 passed in 49.6s**.
  Updated screenshots: frontend/test-results/vrf-review-en.png and vrf-review-ru.png.
  An EN/RU network-scope-blocker copy addition after the runtime image build passed
  final local TypeScript/Vite and this combined browser suite; no backend change.
- Final narrow HTTP scope suite: **11 passed** (including propagation of a NetBox
  VRF-read refusal; no fake empty successful inventory). Final directory/RBAC
  suite: **39 passed**. Earlier broader suite: 143 passed; frontend units: 74 passed.
- Implementation: b8adfd63984cd08c32bf279f514f8cf8a7bffc11.
- Production regressions: ee3d05b98a2ccea0e374b9f97c914b36989b7424.
- No push, live access or deployment. No global cleanup at the end.

### Retirement boundary checked against real NetBox 4.7

`tests/netbox_guard_contract_scenario.py` passed in the pinned local NetBox image
and isolated test DB. An IP inserted on a VM interface after reviewing its VM's
last_updated leaves the VM version unchanged but enters Django's deletion collector
for that VM. All fixture writes roll back; no delete executes. This is a deterministic
interleaving/model counterexample, not a complete concurrent guarded-delete test.
It proves that parent If-Match alone cannot protect an earlier dependency manifest.
Atomic NetBox-side closure/creation-claim protection still needs implementation;
retirement is not silently downgraded to ordinary REST DELETE.


## Continuation after 680cfdb — atomic dependency and physical partial-write gates

HEAD and clean tree verified before changes. Prior VRF/response-loss commits are
preserved. No global resource cleanup, live access, deployment or publication.
Docker context desktop-linux / Engine 29.7.2; no VHD manipulation.

- Added an independent NetBox-side dependency transaction primitive under
  deploy/netbox_guard. It is deliberately not registered or reachable from Sync:
  ownership/creation claims, receipt persistence and lifecycle executor remain open.
- Real NetBox 4.7.0 + PostgreSQL test passed dependency change, manual-data change,
  concurrent GFK writer exclusion, bounded lock-contention refusal, retry and
  surviving-object SET_NULL protection. Final unknown-table/trigger negative checks also passed; the 45 standard
  triggers are pinned by full definition/function-body fingerprint. Redis is an unprivileged, network-isolated test companion;
  NetBox model callbacks are not mocked out.
- Related Linux retirement review and HTTP VRF tests: 26 passed. Existing review
  execution remains blocked, so this does not enable an unsafe REST DELETE.
- Extended the production runtime fixture to fail its third write after two
  committed mutations. External-PostgreSQL smoke exercises this path; bundled
  smoke retains the first-write-refusal scenario. Both keep actual client loss,
  durable Run ID/digest, worker restart and no-replay assertions. Full run: **2
  passed in 490.78s** using the previously verified scope-final-20260923 product
  image and current test-only fixture/scripts. No new product runtime code was
  needed for this gate.
- Historical CM still has no immutable full plan stored in sync_runs; digest and
  zero action counts cannot prove outcome. No old status has been reset.
- Proxmox identity research: stable-8 API2Tools derives subscription serverid from
  the SSH public key, not a hardware UUID. It is therefore not silently treated as
  equivalent to ESXi hardware identity; rotation/reinstallation/clone compatibility
  and overlapping multi-node reservations still require explicit implementation.
  Primary sources: https://github.com/proxmox/pve-manager/blob/stable-8/PVE/API2Tools.pm
  and https://github.com/proxmox/pve-manager/blob/stable-8/PVE/API2/Subscription.pm.

The full task is not complete. Retirement/orphan executor, historical-result
reconciliation, compatible PAM/Proxmox identity and Microsoft AD live acceptance
remain open; these tests do not constitute those gates.


Final continuation evidence:
- 26 retirement/VRF HTTP regressions + 28 planning/revalidation regressions passed.
- Real pinned NetBox model gate passed with normal callbacks and actual separate
  PostgreSQL connections, including unknown trigger/table refusal. This is a
  dependency-fence gate, not an executable retirement acceptance.
- Production external-DB fixture recorded exactly two successful mutations and
  three attempted writes; the third returned a controlled refusal. The API retained
  the accepted Run ID/digest as OUTCOME_UNCERTAIN after client disconnect and worker
  restart. Retry, fresh confirmation, schedule and mappings writes stayed blocked.
  Fixture-side evidence establishes partial writes in this test; it does not teach
  the product to infer a historical outcome from counters or assign SUCCEEDED.
- Bundled mode retained the first-write refusal scenario; successful Proxmox
  disconnect/reload, provider cycles, scheduler and populated upgrade remain part
  of the executed two-mode gate. Microsoft AD and historical CM were not accessed.
- Dependency fence committed as da72422d66c847c59aa7ef76e569f8fac7eb6da3.
- No TypeScript/UI implementation changed in this continuation. The production
  browser gate ran; unrelated visual suites were not repeated.


## Continuation after f7c466f — transactional retirement protocol

Implemented optional NetBox-side models/migration and transaction service (not yet
an HTTP/product workflow). Actual NetBox 4.7/PostgreSQL tests passed:
- non-superuser ObjectPermission constrained by source; wrong source/viewer refused;
- atomic creation + claim + idempotent receipt, conflicting nonce refused;
- exact generation and placement; changed cluster/foreign identity/manual child refuse;
- receipt failure rolls deletion and claim changes back;
- lost-response replay returns the committed receipt, two concurrent confirmations
  delete once, ordinary deletion/ID reuse cannot inherit a claim;
- leaf phases then empty cluster deletion; source-created VM can retire while manual
  cluster/common catalog remain; fresh create request establishes a new generation.
- original concurrent dependency fence repeated successfully without the plugin.
- `makemigrations --check`: no missing changes.

New journal backup gate passed real pg_dump/pg_restore of the four guard tables
against a separate preserved-state test DB copy. Restored retry returns the same
receipt; remaining inventory/claims do not change. FULL NetBox schema pg_restore
failed independently on its standard ltree trigger operator/search_path resolution;
no trigger rewriting or security relaxation was performed. See guard README.

The first cold NetBox migration exceeded the harness's 300-second preparation
budget during Django migration-state rendering, not during provider work. Preparation
now has a finite 900-second limit, then the scenario resets to 300 seconds. Product
120-second discovery deadlines and child cleanup remain unchanged.

No product HTTP route/creation interception/lifecycle worker integration yet; no
new Sync grants, secret mounts, egress or containers in production Compose. Existing
Sync CREATEs do not automatically acquire these claims. Historical managed identities
alone remain insufficient for retirement. Orphan processing, old UNKNOWN and identity
matrix entries are still active work. No push/deployment/live actions occurred.


## Continuation after 3813b32 — authenticated guard transport

- Added fixed NetBox API routes and durable installation UUID; real source-scoped
  permissions, ordinary object add permission, read-only and revoked token refusal.
- Added private Sync HTTPS client: pinned namespace, redirects forbidden, bounded
  response, no automatic write retries, safe refusal versus uncertain result.
- Tightened parent ownership: same placement is insufficient; malformed v2 records
  and reassignment to a manual NIC are rejected. Standard provider identity schema
  was not changed.
- Real NetBox HTTPS host/VM/NIC/IP/MAC/disk and phased receipts passed. 17 transport
  tests passed. Full transaction/journal restore gate passed; migration check passed.
- One repeat stopped on Windows CP1251 printing a NetBox emoji; the complete test
  was rerun successfully with PYTHONUTF8=1. This was a harness output failure.

No production hook, grants, mounts, egress or broker changes. Product retirement
coordination and authoritative orphan execution remain unfinished; existing source
removal is still retain-only. Full NetBox restore and Microsoft AD live acceptance
remain separate gaps. No push/deployment/live connection was made.
