# Backend recovery acceptance — 24 September 2026

Current recovery delivery and remaining limitations: [24 September acceptance](backend-completion-acceptance-20260924.md). Older checkpoint counts below are historical.

Base: `187056fbaf70ae1e9561d1aa6cc2c46c0b9441ff`, main, canonical origin.
Initial working tree clean. All previous commits retained. No AGENTS.md found in
repository or its parent chain. The previous README/container documentation is
already committed in this base, not an outstanding foreign edit.

The user subsequently instructed **no browser verification**. Live observations
below are supplied evidence, not newly executed acceptance. No SSH, live writes,
deployment or push has been performed in this continuation.

## Unified work and evidence matrix

| Symptom / requirement | Reproduction | Established cause | Correction | Regression / local gate | Live evidence | Remaining work |
| --- | --- | --- | --- | --- | --- | --- |
| PAM registration reports several owners | Supplied wizard observation; local registration code reviewed | HOST_IDENTITY_CONFLICT in admission means more than one source row has the same accepted recorded UUID; tombstones are included. Actual row IDs and UUID unknown | No arbitrary winner or reservation deletion | Prior PG admission gates; actual conflicting metadata still needed | Fails before placement, including after NetBox cleanup | Admin-only bounded conflicting record list implemented; explicit evidence-backed resolution and recovery remain open |
| AM/CM host identity unavailable | Supplied wizard observation | Exact live rejection branch/value unproved. Preview reads summary UUID; Discovery also reads systemInfo. UUID validator rejects values with fewer than eight nonzero bytes | Do not relax validation or change identity from DNS/IP without evidence | Existing identity tests do not reproduce these hardware values | Wizard blocked, Discovery previously collected host | Obtain bounded identity evidence; compatible identity correction and collision tests |
| CM missing cluster shown as NetBox unavailable | New local regression fails with NETBOX_UNAVAILABLE after removing only target cluster | _resolve_target raises generic EsxiAdoptionError; worker maps it to connectivity failure | Dedicated missing-placement code, EN/RU; ambiguity mapped separately; no blanket HTTP catch | 48 focused tests pass, including real local HTTP empty result versus 403, no writes | Live cause still a hypothesis; no new live check | Repair editor now accepts bounded recent failed-comparison provider evidence; UNKNOWN remains separate gate |
| Historical CM UNKNOWN | Supplied two run IDs; code review | Historical run digest/counters do not contain immutable full intent and cannot prove success | No reset or automatic write replay | Existing gates retained | Still blocks plan/removal | Administrative evidence journal and resolution; insufficient evidence must remain explicit |
| Full provider → guard CREATE → retirement → re-add | Earlier components tested separately | Combined gate not yet passed; deleted cluster conflicts with old recovery placement contract | Existing isolated worker retained | Prior real NetBox transaction, receipt and worker gates, not combined acceptance | Not completed | Combined production ESXi/Proxmox tests and supported same-source re-add after confirmed deletion |
| Lost cluster CREATE response | Existing durable UNCERTAIN journal | Name lookup cannot establish which request created object | Exact read-only guard creation receipt, no repeated POST | Actual NetBox 4.7 lost-response GET for cluster and VM; Linux catalog/API tests | Not tested | Full restart-resume wizard remains open |
| Orphans / historical unclaimed objects | Code audit | Active-list absence and v2 identity are insufficient creation proof | No name/IP adoption | Existing guard refuses unclaimed dependencies | NetBox manually cleared by user, devices retained | Authoritative reconciliation and evidence-backed historical ownership workflow |
| Duplicate ESXI-INFRA / reservations | Prior observations and PG tests | Live hardware IDs and ownership unknown; no winner established | Atomic UUID reservation and same-attempt continuation already present | Prior concurrency/restart tests; complete recovery still open | Two old records observed, not reconciled | Audit records, uncertain work, ownership and retained credentials before transition |
| PAM VM identity / Proxmox identity | Historical conflicts, local code | Shared VM UUID cause unknown; Proxmox nodes/name not physical identity proof | No incompatible identity switch | Existing conflict tests; live causes unproved | No current full-cycle evidence | Stable compatible identity evaluation; no host alias-based adoption |
| IP overlap / mask / VRF change | Existing observations and tests | IPAM ambiguity differs from full inventory visibility | Preserve observe policy, explicit VRFs, no arbitrary owner | Prior local coverage; repeat with actual guard apply required | Historical /16 and /24 observations existed, subsequently deleted | Current guard-enabled apply and scope-change regression |
| Local Admin reauthentication | Prior runtime coverage | Live logout cause not reproduced | Keep session and explicit proof controls | Prior production auth Compose gates | Login works; Allow destination not retested | Targeted complete action regression and supplied live follow-up |
| AD admission and individual RBAC | Prior implementation/tests | Group DN admission separate from individual role | Retain Viewer default, stable principal roles, local emergency Admin | Prior LDAP fixture/upgrade gates | Microsoft AD acceptance not complete | Rename/revoke/outage coverage review; no mock claim of AD acceptance |
| Manual/scheduled locks and lost apply response | Prior production runtime tests | No new confirmed defect from supplied data | Keep shared lock, no uncertain replay | Rerun affected combined guard cycle | Historical live outcomes insufficient | Manual then scheduled no-op with real NetBox guard |
| Upgrade / backup / restore | Prior Sync gates; external NetBox limitation | NetBox logical restore ltree failure; physical DB recovery reported separately | Never disable guard compatibility checks | Sync journal restore/upgrade passed previously | Full app and cross-journal consistency unproved | Joint application/claims/receipts/UUID restore and restart acceptance |

## This continuation

Docker context desktop-linux. Initial disk report: images 10.81 GB, container
writable layers 1.358 GB, volumes 1.901 GB, build cache 6.836 GB. No obsolete
ownership proof was available; no cleanup or VHD manipulation performed.

Browser opening was initially rejected by automatic review (old live-access
prohibition); user then explicitly approved. The subsequent attempt timed out.
User then directed continuation without browser checks; no further attempt made.
A local edit approval briefly failed with an HTTP 403 service error, not an unsafe
action decision. A retry succeeded; no permission workaround was used.

ESXi API reference distinguishes summary.hardware.uuid and hardware.systemInfo.uuid:
[HostHardwareSummary](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.host.Summary.HardwareSummary.html),
[HostSystemInfo](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.host.SystemInfo.html).
Their availability does not establish the actual values on AM/CM. No provider
identity fallback or entropy-policy change has been made based solely on hypothesis.

Missing placement regression before fix: 1 failed, expected
NETBOX_PLACEMENT_MISSING, received NETBOX_UNAVAILABLE. After fix: 48 focused tests
passed. Controlled HTTP fixture confirms GET-only behavior and preserves 403 as
NETBOX_PERMISSION_DENIED. This is not real NetBox or full production acceptance.

## Placement recovery correction

A confirmed local deadlock existed independently of the live CM diagnosis:
placement editing required a SUCCEEDED Discovery, but comparison required the
old cluster to exist. Provider collection had already completed successfully.
Now only NETBOX_PLACEMENT_MISSING can retain a validated, bounded host projection
in the failed operation's private result. The public operation remains FAILED,
with result=null and the specific EN/RU error. No VM descriptions, credentials or
raw responses enter this evidence or diagnostic logs. The projection is not
ownership evidence and is not accepted by identity verification or prepare/apply.

The existing placement editor can use this evidence for 24 hours. It still checks
current source revision, exact discovery generation, explicit catalog choices,
shared lock and uncertain/active runs. Failed provider, permission, network and
TLS reads never supply this exception. Source ID, credentials and scheduling do
not change. UNKNOWN CM therefore still requires separate evidence reconciliation.

Checks on this code: 106 focused Linux/PostgreSQL tests; full Linux/PostgreSQL
**1393 passed, 47 skipped**; TypeScript and 74 frontend unit tests passed.
The 47 skips have the same opt-in categories listed in backend-completion-progress;
previous separate executions are historical, not rerun evidence for this diff.
Actual production Compose and real NetBox combined acceptance remain open.
Test database is uniquely labeled recovery-20260924-c472, network none, tmpfs,
no published port or named volume. Existing test databases were not restarted.

## Registration conflict explanation

Admission now retains a bounded list (at most 100) of conflicting registry Source
IDs and whether each has an unrestored tombstone. Only a server-authenticated Admin
receives this list; Operator keeps the general refusal and Viewer cannot invoke
the connection workflow. No credentials, actor IDs, raw provider results or
ownership transfer are exposed. The UI uses local EN/RU labels and validated IDs.

The wording now distinguishes equal recorded identifiers from proved identical
physical servers. Identity-unavailable wording also no longer asserts that ESXi
itself lacks a UUID. Neither change unlocks an ambiguous registration.

Real PostgreSQL + actual AuthPolicy/API: 21 admission tests passed, including
Admin/Operator/Viewer projection and no credential/source side effects. Frontend:
75 unit tests and TypeScript passed. These reports will identify the conflicting
records on a future operator-run attempt; the actual PAM IDs remain unknown here.

## Guarded catalog CREATE reconciliation

The guard now exposes an authenticated GET for an exact creation nonce. It returns
only a receipt belonging to the same NetBox principal, rechecks creation capability,
object permission, claim generation, source ownership and placement, and never
creates an object. Sync verifies the original canonical wire digest, source,
resource and nonce. A cluster's current selected name/type/site must also match
the protected original intent before it is accepted for registration.

The protected catalog journal can reconcile a lost cluster response through that
GET. Missing, refused, changed or malformed proof leaves UNCERTAIN; no second POST
is sent. Changing the pinned guard UUID refuses. A confirmed cluster is not a
confirmed source: the registration status keeps identity uncertainty and reports
catalog_status separately. The UI no longer advises starting a new Source ID.
The existing exact same-attempt registration continuation remains required; the
full restart-resume wizard remains an explicit integration gap.

Requires upgrading the separately installed guard code as well as Sync; an older
guard without the GET route fails closed. No guard database migration, new
permission, Docker mount, network or trigger change is required. Full source
retirement, historical claims, and UNKNOWN resolution are not inferred from a
successful catalog receipt.

Executed: 44 catalog/transport regressions; 64 API/transport tests; combined affected
Linux/PostgreSQL selection 162 passed. Real NetBox 4.7/TLS/PostgreSQL gate passed
with post-commit serializer failures for both a VM and a cluster. Subsequent GET
returns the original ID, with unchanged POST count and exactly one created object.
The existing retry/conflict/retirement/token-revocation checks passed in the same
scenario. Private exception text is not returned; server diagnostic contains only
an event UUID and exception class.

Production Compose verification on this change: **2 passed**, bundled and external
PostgreSQL, using the actual product image and Compose topology. Includes actual
API/auth-worker RPC, guarded retirement-intent refusal, registration/catalog loss
reconciliation, session expiry/revocation and backup/restore checks provided by the
harness. This is not the complete provider -> guarded retirement -> re-add gate.
Frontend: 75 unit tests and TypeScript passed; Dockerfile.web built successfully.
Browser and live checks were not run, following the operator's latest instruction.


## Appeared cluster cannot bypass original creation proof

A further API regression demonstrated that automatic placement could resolve a
cluster appearing after the original request and skip the original CREATE journal.
Before correction all four regression variants reached registration without any
receipt read, including missing proof, uncertain proof and a different object ID.
The API now binds the original immutable intent and requests read-only reconciliation
before accepting that transition. Only CREATED proof for the exact resolved cluster
ID passes. The intent digest, actor, source and registration nonce remain unchanged.
Missing proof refuses; uncertain/mismatching proof stays REGISTRATION_UNCERTAIN.
No second cluster POST, credential file or source is created on these refusals.
An independently created matching cluster must not silently satisfy the original
request to create a new cluster.

Affected Linux/PostgreSQL registration, onboarding, catalog and reservation tests:
**136 passed**. The four new regression cases failed before correction. The real
API permission path is used; external effects in those four tests are controlled
fixtures. This does not establish an end-to-end resumed wizard or a live fix.

The updated production web image (manifest list
`sha256:155b33a2d3443d2eb2901410d95d332db213ec3cda770998505f37404c409627`)
passed the same bundled/external PostgreSQL Compose gate again: **2 passed**.

## ESXi preview hardware UUID fallback

A controlled reproduction now confirms a collection mismatch (not the live AM/CM
cause): with a missing/invalid summary UUID and a valid hardware.systemInfo.uuid,
Discovery selected the hardware UUID, while onboarding selected ha-host and rejected
admission. Four identity cases failed before correction. A fifth regression proves
that a hardware read refusal must propagate rather than appear as missing identity.

Preview now preserves its existing valid summary UUID fast path. Only if that UUID
is unusable does it read HostSystem.hardware once and use the same strict hardware
UUID validator as Discovery. No VM inventory or guest properties are read. Empty,
malformed, all-zero and low-information UUIDs remain rejected at admission; no DNS,
IP, display name or managed-object reference is accepted as host identity.
Existing source identities are not rewritten. Conflicting valid UUID fields still
need investigation; this change deliberately does not change the established
summary fast-path priority or select an owner for conflicting records.

Real local TLS/SOAP with pyVmomi verifies the selected UUID and request paths: six
requests including login/service reads on the usual path, seven with fallback,
and no VM/guest/config reads, with a 147-VM fixture behind the endpoint. This is a
local protocol regression, not evidence of the actual fields returned by AM/CM.

Final affected Linux/PostgreSQL/pyVmomi/probe selection: **101 passed, no skips**,
including the four explicitly enabled cross-UID bounded-worker cases that were
initially skipped without NETBOX_SYNC_TIMEOUT_TEST. Existing timeout/reaping,
147-VM batch completeness and duplicate-conflict regressions passed. No changes
to capabilities, schedules, TLS settings, egress or production Compose were made.
The last Compose image gate predates this isolated preview fallback; the fallback
itself was verified by the current real TLS/SOAP test, not claimed as live acceptance.

## Later UUID evidence

The AM eight-nonzero-byte rejection above is now reproduced and superseded by [the BIOS UUID compatibility review](esxi-bios-uuid-acceptance-20260924.md). Historical checkpoint statements are not the current UUID admission contract.
