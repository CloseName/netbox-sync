# Source lifecycle: immutable generations and confirmed closure

Implementation from base `1094800412e6f06aedeffde6e66336c4200680d9`.
This supersedes the admission workaround as the normal lifecycle. It does not
claim that the operator's AM/PAM/CM inventory has been inspected or repaired.

## States and authority

An active source retains its immutable Source ID. Retain-only removal keeps its
hardware claim and can recover the same ID only with existing identity/ownership
proof. Normal removal reviews the exact Guard-owned inventory, records SENDING,
disables synchronization, verifies the remote transaction receipt, tombstones the
source, cleans exclusively owned local credentials and records a final archive.
Only then is its active hardware claim released. History, old source rows,
receipts, mappings and provenance are not deleted. A subsequent registration
receives a NEW Source ID; old operations cannot authorize that generation.

`0013_source_archives` separates archives from active ESXi hardware reservations.
Released reservations remain audit records; a partial unique index permits only
one active `(provider, anchor)` claim. Source-instance uniqueness remains, so an
old registration attempt cannot reserve a released ID again. Proxmox uses its
existing identity contract; this does not invent an ESXi hardware UUID for it.

Guard migration `0004_source_closure` records a permanent source namespace seal.
CREATE and both root/full retirement dispatch use the same namespace advisory
fence. A completed receipt remains readable and idempotent; an unexecuted old
intent cannot write into a sealed namespace. Native unrelated NetBox writes are
not controlled by this Guard: shared Sync lock and uncertain-run checks remain
required to prevent already-running ordinary UPDATE operations from being
mistaken for stopped work.

NetBox deletion is atomic within its own transaction; receipt failure rolls it
back. Local steps are a resumable sequence, not a distributed transaction. An
uncertain response requires reading the original receipt. Only explicit Admin
continuation may resend a confirmed still-REVIEWED intent. Arbitrary retry/new
nonces are not a recovery method. PREPARED recovery attempts are abandoned in the
same local transaction as removal admission; CREDENTIALS_PENDING is blocked
because credential dispatch may already have happened.

A legacy client that explicitly requested credential retention is not silently
authorized to delete credentials. The operation remains SUCCEEDED (remote result),
not FINALIZED; its UUID stays reserved. The UI offers explicit cleanup consent.
Shared/noncanonical legacy credential files are retained by existing ownership
rules. Provider-side token/password revocation is never performed.

## Historical reconciliation, including AM

Admin opens **Sources → Review registrations**. The bounded list distinguishes
active/disabled, retained, removing, unresolved runs, pending recovery, pending
registration and closed archives. It also lists conflicting Source IDs for a
recorded UUID. A pending registration is not an empty source: its original actor
must resume the durable attempt in Add source; the list never discards its claim
or assumes that a cluster/credential write did not occur. There is no new
cross-user takeover privilege.

For AM, observed UUID `00000000-0000-0000-0000-ac1f6be2c4da` remains a conservative
collision key, not verified old ownership. An observed-only removed source now
leads to explicit historical closure, not an impossible same-ID recovery.
**Review archive** reads present objects and historical creation receipts,
including manually missing objects. Admin reviews the exact retained list and
confirms closure. Guard seals the old namespace without deleting infrastructure;
Sync cleans exclusive credentials and releases the active reservation. The next
connection check permits a new generation. Historical run outcomes remain
unchanged/UNPROVED; absence of objects never becomes proof of a successful run.

The reported SUP device #5, if unclaimed, must remain. Names, address equality and
UUID observations do not create deletion/adoption authority. A new generation
cannot take ownership of that device. Use a nonconflicting explicitly selected
placement or establish independent provenance through a separately reviewed
procedure; do not clear foreign identities or rename-match it into Sync.

A fresh audit exposes protected dependency model/ID/field references only after
native NetBox object-view permission checks. It does not return names, comments,
raw model data or secrets. The displayed dependency list is diagnostic; execution
still recomputes the complete closure under the existing DB fence. Unknown schema,
manual/foreign creation, changed dependencies and insufficient rights fail closed.

## Upgrade and restore

No historical tombstone is automatically converted into proof of remote closure.
Existing FINALIZED or SUCCEEDED records without a Guard seal require a separate
current-inventory archive review. The old receipt/state is preserved; a new intent
references it through supersession, rather than rewriting its historical result.

A Sync restore preserves archives, journals, credentials and released claims but
invalidates archive `verified_at`. New ESXi admission stops until Admin rechecks
the original receipt against the pinned Guard UUID. A missing/different receipt
or seal is a hard refusal; Sync must not recreate it from its backup. Guard DB
backup must include SourceClosure, CreationClaim/Receipt, RetirementIntent/Receipt
and GuardIdentity together with the NetBox inventory. A journal-only test is not
proof of a complete NetBox disaster restore.

Migration downgrade is intentionally unsupported. Installer activation failure
restores current/config and quiesces uncertain new runtime; it does not undo DB
migrations or external NetBox changes. Do not restart an older writer against
post-closure state or restore only the old Sync DB after a NetBox deletion.
Recover forward where possible; coordinated restore requires independently
verified NetBox and Sync backups and receipt reconciliation.

## Preserved boundaries and removed workaround

Broker stays literal network_mode:none; no DB/NetBox access. Lifecycle owns narrow
DB lifecycle writes and the shared apply lock, not a NetBox token. Retirement
worker alone uses the read-only NetBox configuration/CA and private Unix socket.
API/DB/workers gain no published ports, Docker socket or systemd control. Admin
checks remain server-side; Operator/Viewer cannot remove/archive/reconcile.

The unused LegacyAdmission UI component is removed. Historical decision endpoints
and records stay compatible; the new central process supersedes per-add-source
isolation prompts. Restore, uncertainty checks, creation claims, source scopes,
manual field protection and existing token/CA validation remain in force.

## Local evidence and limits (27 September)

- Linux related backend selection: **534 passed**, one Docker-CLI skip, separately
  executed on the Docker-enabled host: **1 passed**.
- Real PostgreSQL role/migration/logical-backup suite: **15 passed**. Includes
  immutable archive fields, narrow verified_at permission, restored admission fence.
- Real NetBox4.7 HTTP: scoped token/audit/view rights, protected external primary-IP
  dependency hidden without view permission; exact metadata after permission;
  manual missing cluster/VM and retained host, changed archive refusal, lost
  response receipt, late CREATE/root DELETE refusal. Passed locally.
- Real production retirement-worker/NetBox TLS/PostgreSQL gate: **1 passed**,
  including three ESXi generations and Proxmox VM/LXC inventory, apply/empty
  repeat-plan, source retirement, retained history and new reservation. Provider
  inventory here is synthetic; this is not a live hypervisor test.
- Guard pg_dump/restore gate passed for journals against a preserved isolated
  NetBox template, preserving Guard UUID and closed namespace. The previously
  observed vanilla NetBox full-schema ltree/search_path restore issue is outside
  this gate; a supported full NetBox restore remains an operator prerequisite.
- Production Compose bundled/external gates passed with real workers, controlled
  HTTPS/SOAP provider and NetBox HTTP fixtures, browser plan/prepare/apply/replan,
  scheduler success/refusal/uncertainty and populated installer upgrade. A separate
  host CLI path passed create/verify/inspect/fresh restore and service-state recovery.
- Frontend unit suite: **84 passed**; TypeScript/Vite and image builds passed.
  Browser lifecycle/wizard suite: **64 passed**, including EN/RU archive review,
  old credential-retention consent, dependencies and new-ID re-registration.
- Explicit migration 0012 → 0013 selection: **6 passed**, preserving unsealed old
  FINALIZED history and its active claim. No automatic closure is inferred.

Do not combine these into a claim of one browser session against a real provider
and real NetBox: real Guard/model deletion and the complete worker/browser flow
are separate local gates. Actual AM ownership, the operator's full NetBox backup
and deployment topology still require operator acceptance. Deletion remains bounded
at 10,000 objects/30s Guard work, with a 45s child boundary and bounded cleanup.
A larger or repeatedly timing-out tree is refused/rolled back, not partially
reported as removed. No arbitrary-size background batch deletion was introduced.


## Requirement-to-evidence map

| Scenario | Executed local evidence | Boundary |
| --- | --- | --- |
| Add, plan/apply, empty repeat plan | Production workers/browser with controlled provider HTTP; real NetBox inventory runner | These are separate gates, not a live ESXi browser session |
| Full removal, release, new registration | `test_retirement_production_worker.py`, `test_source_archive_postgres.py`, wizard remove/re-add | Actual NetBox deletion/receipt and PostgreSQL claim; UI uses controlled API |
| Repeated generations | Three ESXi generations and Proxmox VM/LXC in `real_guard_inventory.py` | Provider inventory is synthetic |
| DNS/IP aliases and UUID collision | Host-registration/identity regression selection | Identity comes from verified provider metadata, not DNS/IP equality |
| Old records without UUID, exact observed AM | `test_legacy_admission.py`, exact AM archive PostgreSQL and EN/RU browser cases | No promotion of observations into ownership |
| Manually absent cluster/VM, retained host | Real `netbox_guard_http_scenario.py` | Current absence does not rewrite run history |
| Uncertain/partial previous operations | PostgreSQL lifecycle/journal tests and production worker refusal | Refuses closure until original result is reconciled |
| Lost response/restart | HTTP receipt test; tombstone/cleanup crash-point tests; browser reload/response-loss | Selected durable interruption points, not exhaustive process/power failure injection |
| Concurrent workers/scheduler/registration | Real Guard concurrent confirmation and SQL fences; PostgreSQL admission/lock tests; production scheduler refusal | No claim of exhaustive all-interleaving stress testing |
| Late old-generation work | Real Guard late CREATE/root-delete refusal; released-claim and source-gate tests | Ordinary external NetBox UPDATE still needs the Sync shared lock/uncertainty gate |
| Foreign/manual/shared data | Real protected dependency/view tests; ownership protocol; shared-credential tests | No automatic adoption/deletion of unproved objects |
| Roles and NetBox scopes | API Admin/Operator/Viewer regressions, native constrained NetBox token checks | No new administrative privileges assigned automatically |
| Preserve-infrastructure archive | Exact AM PostgreSQL/browser, real Guard changed-manifest and retained-object checks | Explicit separate Admin action |
| Upgrade, backup, restore | Populated production installer upgrade; host CLI backup/create/verify/inspect/restore; PostgreSQL grants/dump; 0012 migration | Real failed-upgrade rollback is not newly injected; existing installer failure unit checks remain. Full external NetBox disaster restore is still an operator gate |

Builds use production Dockerfile.web and the independently operated Guard Dockerfile.
The final UI-only translation/error-display changes were checked by the complete
64-case browser selection and rebuilt image; backend/Compose topology is unchanged
from the passing production worker runs. Existing Vite bundle-size warning remains.
