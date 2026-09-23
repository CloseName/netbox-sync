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
| 1 NetBox retirement | Existing review-only journal; guarded remote deletion not implemented. |
| 2 Orphan reconciliation | Durable authoritative reconciliation/periodic executor missing. |
| 3 Remove/re-add/recover | Bounded Admin ESXi same-namespace recovery implemented/tested; legacy, Proxmox and cross-namespace recovery unfinished. |
| 4 Cluster creation | Live cause unconfirmed; previous controlled test is not reproduction. |
| 5 IP scopes | Explicit observations supported; VRF/scoped assignments remain missing. |
| 6 PAM VM identity | Still ambiguous; no identity schema changed or conflicts bypassed. |
| 7 CM uncertain run | Reconciliation state machine missing; do not replay old writes. |
| 8 PLAN latency | Confirmed redundant reads reduced locally; live root cause not established. |
| 9 AD/RBAC | Earlier fixture evidence only; fresh Microsoft AD acceptance pending. |
| 10 Reauthentication | Earlier implementation retained; this iteration runtime gates pending. |
| 11 Apply response loss | Earlier same-run UI checks retained; restart/runtime fault gate pending. |
| 12 Duplicate hosts | UUID admission/atomic reservation/runtime guard and ESXi recovery tested. Legacy identity acquisition, abandoned-attempt resume and live ownership audit remain. |

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
