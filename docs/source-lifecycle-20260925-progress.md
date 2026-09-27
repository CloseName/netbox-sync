# Source lifecycle replacement — 25 September 2026

Base: 1094800412e6f06aedeffde6e66336c4200680d9, canonical main, initially clean.
User authorizes implementation, isolated tests, commit and push; no live access/deployment.
Docker desktop-linux / Engine29.7.2 available after operator startup. Existing stopped test containers and all volumes kept; no ownership-safe obsolete cleanup was established. No VHD access.

## Confirmed defects

- Tombstones and active hardware claims are conflated: final retirement retains the UUID reservation.
- Observed UUID is a collision key but recovery requires proven ownership; routing observations into recovery creates the reported AM dead end.
- Local FINALIZED can be written before credential cleanup; retry after tombstoning can fail the old generation check.
- Old namespace retirement does not itself fence a late Guard CREATE.

## Contract being implemented

- Source ID is an immutable registration generation; after final archive new registration receives a new Source ID. Retain-only recovery preserves its original ID, but cannot reopen a final archive.
- Active hardware reservation and immutable registration history are separate. Only a verified final archive releases the active reservation, retaining the row/audit.
- Full removal uses existing immutable Guard intent, dependency transaction, exact receipt and shared apply lock. Local cleanup and archive are resumable phases; success requires completion.
- Legacy close is explicitly different: current scoped inventory, protected retained objects, unchanged historical outcomes and permanent namespace closure. It never promotes observed UUID to ownership or deletes unproved objects. Unknown historical placement remains protected.
- Guard seals closed source namespaces under the same source/dependency fences. Old requests cannot create in a new generation.
- Admin-only centralized lifecycle review replaces repetitive per-host admission exceptions; active duplicates remain blocked.

## Initial remaining gates (historical)

Implementation in progress. Migration/grants and backup compatibility; Guard native authorization/non-root import; PostgreSQL concurrency and receipt/cleanup crash points; actual NetBox4.7 multi-generation lifecycle; production Compose manual/scheduled provider and upgrade; final browser cycle; documentation, commit and push. No current-release success claimed yet.


## Resumed 27 September

Docker desktop-linux / Engine29.7.2. Prepared edits preserved; HEAD remains base.
Recovered previous session results: Compose failed on a fixture's fixed subnet
colliding with an existing project, not product ports. Harness now chooses an
unused fixture subnet without removing foreign resources. Guard cold preparation
budget was inconsistent with its 900s migration watchdog; operator harness now
allows bounded 960s preparation only, runtime deadlines unchanged.

Closed additional defects: identity verification/legacy observation exclude only
verified archives; pending registrations and collisions shown centrally; Proxmox
not classified by absent ESXi UUID; PREPARED recovery cancelled transactionally,
CREDENTIALS_PENDING refused; old retain-credentials approval requires explicit
cleanup confirmation. Native permission-checked dependency references added.

Recorded results: 534 backend passed + Docker-only skip closed separately; 15
real PostgreSQL grants/backup passed; 84 frontend unit passed; 57 Playwright passed;
production Compose full-worker/browser bundled/external 2 passed (410.89s), separate
host backup/restore branch 2 passed (205.33s); actual NetBox HTTP passed; final
retirement-worker real NetBox gate 1 passed (81.51s). Current final-image full-worker
rerun and four added browser cases are still in progress; do not count them yet.
See source-lifecycle-20260927.md for precise coverage boundaries.


## Final review

- Final backend image production Compose full-worker/browser bundled/external:
  2 passed (400.46s). Host backup/restore branch: 2 passed (205.33s).
- Explicit migration preservation: 6 passed; grants/logical backup: 15 passed.
- Final related browser selection: 64 passed. The first added malformed-response
  case had a test-only case-sensitive locator mismatch (Add source/Add Source),
  corrected and whole selection repeated. Screenshot review also found stored
  host errors did not change language; render now uses the message pair and the
  EN/RU archive test asserts that switch. No server boundary changed.
- TypeScript/Vite and final Docker image rebuild pass. Only known large-chunk warning.
- See the evidence map for separated real-NetBox, HTTP-fixture and UI gates. Live
  AM/SUP, full independent NetBox recovery and exhaustive power-failure combinations
  are not claimed to be verified. No deployment, SSH or live writes performed.

- Final real Guard protocol rerun passed: native refusal, changed dependencies,
  receipt-write rollback, lost-response idempotence, concurrent delete-once,
  generation/ID reuse and retained shared catalog/manual placement.
- Final image `netbox-sync-lifecycle:20260927-final` manifest list:
  `sha256:f23b03f64ae4ee0f92167f2ad1680e022900eac0aaf8853be53ad491bf841b29`.
  Networkless disposable runtime checked /, /sources, /sources/add,
  /sources/fixture/configuration, built JS/CSS and missing-asset 404.
- Before commits, canonical main and fetched origin/main both equal the base;
  no incoming divergence. All prepared task changes preserved.
