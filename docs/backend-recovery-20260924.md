# Backend recovery acceptance — 24 September 2026

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
| PAM registration reports several owners | Supplied wizard observation; local registration code reviewed | HOST_IDENTITY_CONFLICT in admission means more than one source row has the same accepted recorded UUID; tombstones are included. Actual row IDs and UUID unknown | No arbitrary winner or reservation deletion | Prior PG admission gates; actual conflicting metadata still needed | Fails before placement, including after NetBox cleanup | Bounded record audit; explicit evidence-backed resolution and recovery |
| AM/CM host identity unavailable | Supplied wizard observation | Exact live rejection branch/value unproved. Preview reads summary UUID; Discovery also reads systemInfo. UUID validator rejects values with fewer than eight nonzero bytes | Do not relax validation or change identity from DNS/IP without evidence | Existing identity tests do not reproduce these hardware values | Wizard blocked, Discovery previously collected host | Obtain bounded identity evidence; compatible identity correction and collision tests |
| CM missing cluster shown as NetBox unavailable | New local regression fails with NETBOX_UNAVAILABLE after removing only target cluster | _resolve_target raises generic EsxiAdoptionError; worker maps it to connectivity failure | Dedicated missing-placement code, EN/RU; ambiguity mapped separately; no blanket HTTP catch | 48 focused tests pass, including real local HTTP empty result versus 403, no writes | Live cause still a hypothesis; no new live check | Repair-placement workflow must work without successful comparison; UNKNOWN remains separate gate |
| Historical CM UNKNOWN | Supplied two run IDs; code review | Historical run digest/counters do not contain immutable full intent and cannot prove success | No reset or automatic write replay | Existing gates retained | Still blocks plan/removal | Administrative evidence journal and resolution; insufficient evidence must remain explicit |
| Full provider → guard CREATE → retirement → re-add | Earlier components tested separately | Combined gate not yet passed; deleted cluster conflicts with old recovery placement contract | Existing isolated worker retained | Prior real NetBox transaction, receipt and worker gates, not combined acceptance | Not completed | Combined production ESXi/Proxmox tests and supported same-source re-add after confirmed deletion |
| Lost cluster CREATE response | Existing durable UNCERTAIN journal | Current reconcile reads catalog by name, cannot establish which request created object | Exact guard creation receipt needed, no repeated POST | Prior guard CREATE idempotency is not catalog integration proof | Not tested | Read-only creation receipt verification bound to original intent/actor/source |
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
