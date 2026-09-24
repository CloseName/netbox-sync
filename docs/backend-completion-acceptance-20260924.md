# Backend recovery delivery — 24 September 2026

This report supersedes the **remaining-work status**, not the historical evidence,
in backend-completion-progress.md and backend-recovery-20260924.md. Base:
`1aa0a2c809a7408852e0f9d807ca5fd77490d41e`, canonical main. Existing commits retained.
No browser checks, SSH, deployment, live provider/AD/NetBox calls or writes were made.
Publication is authorized by the latest task; operator live acceptance is separate.

## Requirement / correction / evidence / remaining acceptance

| # | Implemented behavior | Executed local evidence | Operator acceptance / actual limit |
| --- | --- | --- | --- |
| 1 AM/CM identity | Preserve valid summary UUID; hardware fallback uses the same strict validator. Separate missing UUID, invalid placeholder, invisible host, permission, transport and TLS errors through worker/API/RU/EN. No name/IP identity. | Real local pyVmomi SOAP fallback and bounded request count; Linux preview/probe tests; production probe/API. | Actual AM/CM response/permission branch is unknown. Retry connection only; record safe code and event. Missing/invalid hardware UUID needs ESXi administrator to verify SMBIOS System UUID and readable host hardware; do not replace with `ha-host`, address or guessed UUID. Respect each source's existing TLS choice; no global change. |
| 2 PAM records | Admin comparison includes each source ID, saved UUID/address, placement IDs, tombstone/active state, latest runs and unresolved/active counts. Separate current NetBox provenance review. Explicit original-source recovery keeps its namespace; other tombstones remain historical reservations. A registered disabled peer still blocks recovery. | PostgreSQL three-retained-record scenario, same-source restart/retry, changed identity/scope and concurrent recovery; real API Admin/Operator/Viewer checks. | Compare all three supplied PAM IDs. UUID equality alone is not physical proof. Choose original only with fresh authenticated identity and compatible proven provenance. No automatic merge, arbitrary winner or SQL reservation deletion. Unattributed/mixed legacy provenance still requires original creation/audit evidence. |
| 3 CM historical UNKNOWN | Admin reviews recorded runs and current guard evidence; optional explicit acceptance of current baseline is audited separately. Old UNKNOWN/PARTIAL and IDs stay unchanged; no old write replay. Schedule forced off, old READY plans invalidated, new successful MANUAL run required before scheduled execution. | PostgreSQL active/changed/unchecked/foreign actor refusals, retry/restart, run preservation, scheduled gate, actual SQL privileges; API roles and UI acknowledgements. | Current objects cannot prove all historical writes or distinguish later manual changes from old partial application. Before acknowledging, operator must establish that old writers have stopped. This is a limited baseline decision, never SUCCESS reconciliation. RUNNING rows and unfinished evidence remain blocked; this UI does not terminate a live writer. |
| 4 Missing placement | Bounded recent provider evidence from an otherwise failed missing-placement Discovery permits explicit mapping repair. Cluster 404 is treated as missing OR not visible; 403/transport/TLS never masquerade as absent. Retained owned device detached from missing cluster can supply recovery evidence only with exact source/UUID/site. | Controlled real HTTP 404 versus403; PostgreSQL mapping/UNKNOWN/revision gates, recovery tests; production worker placement cycle. | Resolve terminal UNKNOWN via #3 first, then fresh Discovery and explicit cluster selection/creation. No name adoption; confirm object visibility separately if NetBox filters it. |
| 5 Interrupted registration | Immutable secret-free registration request survives API/browser loss. Actor-bound saved-attempt UI checks original receipt, repeats credential verification and continues original source/nonce/placement. No stored browser password. | PostgreSQL restart/one credential file/concurrency/fingerprint/actor gates; actual API permission and production creation-response reconciliation. | Full continuation applies to new ESXi journaled requests. Older null requests or reservation-only records cannot reconstruct lost operator choices: retain them, obtain original request and receipt, never invent them or clear SQL. Proxmox physical-host reservation/recovery is not implemented: see identity limit below. |
| 6 Retirement | Native creation claims, bounded dependency review, original nonce/receipt, tombstone and exclusive credential cleanup. Definite refusals carry closed actionable codes; uncertain transport never authorizes retry. Read receipt then explicit original-intent continuation. Confirmed retirement permits original ESXi namespace recovery even after cluster deletion. | Actual NetBox4.7 and production retirement-worker TLS/Unix transport: deliberate lost request, receipt read, coordinator restart, explicit continuation, ten-object delete, history preservation, same-source restore; guard transaction/refusal suite. | Manual/shared/unclaimed objects remain. Original authenticated Admin owns a pending intent. An old intent is not transferable between admins. Do not infer creation ownership from v2 identity alone. |
| 7 Orphans | Removed source page has Admin inventory audit plus the same guarded retirement workflow using current revision. Already-removed source preserves original tombstone/history and does not repeat credential deletion. Audit lists exact model/ID, presence and claim status; no automatic claim/adoption. | Retained-source context/role tests; PostgreSQL tombstone preservation; actual production worker orphan retirement and recovery. | Records without source provenance cannot be safely discovered by name. Legacy creation-claim import is not implemented. Original receipt or independently authenticated NetBox creation audit is required before designing an import; consent alone is insufficient. |
| 8 IP observations | Existing observe policy keeps complete guests/NICs and all ambiguous address/prefix facts; explicit existing VRFs permit unambiguous assignments. No automatic VRF/Prefix/VLAN creation. | Actual NetBox HTTP/guard ESXi and Proxmox VM+LXC executors: overlapping /24+/32, no false IPAM assignment, no-op repeat, two VRFs, no-op repeat, scope removal preserves IP IDs, guarded retirement. | Providers in this real-NetBox test are synthetic inventories. Independent production-worker SOAP/HTTPS tests exercise provider transport against a controlled NetBox fixture; this is not one combined live-provider test. |
| 9 Local Admin destination | Confirmed policy/recent-proof errors remain distinct from session loss. Explicit retry after password proof, no automatic mutation. | Actual production API/auth Unix sockets: recent proof expiry leaves session valid, password confirmation has no policy effect, retry succeeds; idle/absolute expiry and revoke tested separately. | Supplied live logout was not reproduced; operator retests Allow destination in same session. |
| 10 AD/RBAC | Existing Group DN admission, individual roles/default Viewer, stable identities, role/session revocation and local emergency Admin retained. Operator schedule permission remains server-enforced. | Real OpenLDAP/TLS fixture through directory and HTTP auth, rename/disabled/revocation/outage/CA tests in full Linux suite; local-admin and LDAP upgrade preserving files/settings. | No Microsoft AD test. Check direct group membership, rename, disable/remove membership, revocation refresh window, trusted CA, DC outage and local emergency login. Nested group membership is intentionally not admitted by current contract. |
| 11 Actionable refusals | Lifecycle Unix boundary now preserves identity/recovery/retirement codes instead of collapsing them to CONTROL_UNAVAILABLE. RU/EN baseline/retirement/recovery actions, original result readback, explicit new review when evidence changes. | Actual local Unix transport with unknown exception redaction; API role matrix; frontend acknowledgement and closed-code tests; TypeScript/Vite. | No browser/visual acceptance performed at user's instruction. Old requests, absent provenance and unknown physical identity remain explicitly unavailable rather than falsely successful. |

## Confirmed defects and fixes

* The local-control allowlist discarded useful existing identity/recovery codes.
  Real socket tests now preserve only the closed public vocabulary; arbitrary
  remote exception text still cannot reach the interface.
* NetBox4.7 gives an optional JSON custom field the value `null` on a newly created
  physical NIC. Guard interpreted it as malformed ownership and refused Proxmox
  host-NIC creation. A real HTTP apply failed before correction and passes after.
  Only `None` means absent; malformed values and foreign provenance still refuse.
  Creation claim and parent ownership checks remain mandatory.
* Completed deletion invalidated old placement, which prevented recovery of the
  same namespace. Recovery now checks the exact final guard receipt and absent
  source objects, keeps the old source ID and requires explicit placement repair.
  A later restore/removal cannot reuse an earlier retirement generation.
* Fresh backup restoration must remove the two exact new gate views before its
  allowlisted tables. Restored baseline capabilities are invalidated while audit,
  original UNKNOWN history, policy and credentials are retained.
* Disabled but registered same-identity peers now block recovery; disabling a
  schedule/source does not release identity ownership.

## Scope of proof

Final backend Linux/PostgreSQL: **1479 passed, 40 opt-in/environment skips**.
Frontend: **84 passed**, TypeScript and Vite passed (existing large-bundle warning).
Final Dockerfile.web build manifest:
`sha256:e7d560946094139e287fcd76311e086c6881109505a468ffd740da089ee4f554`.

Separate runs on this implementation:

* 13 real PostgreSQL grants/dump/restore cases; the lifecycle role can INSERT audit
  and SELECT gate views, cannot change old run outcomes; unrelated roles denied.
* Actual host backup/create/verify/inspect/fresh-restore passed; prior services,
  source credentials, policy, onboarding and LDAP state preserved. Old sessions and
  accepted run-baseline capabilities revoked on restore.
* Pre-auth `897de2a` upgrade passed, including volume/container identity, enrollment,
  sources/history/credentials. `5acd4c1` local-admin→LDAP upgrade passed with retained
  settings/secret files across another upgrade. These are nonprivileged operator
  harnesses; a real systemd reboot is not proven.
* Actual NetBox4.7 production retirement-worker gate passed, including real HTTP
  provider executors and IP/VRF tests above. The broker ownership callback in this
  narrow fixture is a test boundary; real broker isolation/ownership is covered
  separately. Do not describe independent gates as one combined browser scenario.
* Real worker transport test passed, including explicit refusal and uncertain
  response; 55 local deployment/ingress tests passed, 4 Windows-only skips covered
  by the Linux run; 4 Compose-derived cross-UID timeout cases passed, with/without
  KILL; clean Debian optional isolated-libpq preparation passed without global pip.

The test runner initially supplied an empty bootstrap password to a repeated PG
check: preflight refused before DB work (13 failures). Supplying a random test-only
value in process memory made all13 pass. Upgrade fixture compared Docker mount
lists as ordered; normalize by Destination while still checking all mount values
and exact DB container ID. TLS smoke had a stale hardcoded16-field assertion;
compare the complete shared FIELDS contract instead. Neither fix relaxes product
checks or overrides product tmpfs/security parameters.

### Classification of the 40 skips

| Count / group | Reason in plain Linux runner | Separate coverage / remaining gap |
| --- | --- | --- |
| 2 auth_compose | Opt-in Docker | Real bundled/external production workers run separately. |
| 1 auth_upgrade, 1 ldap_upgrade | Operator Docker socket opt-in | Both historical upgrades passed, nonprivileged/no-systemd. |
| 1 backup_clean_debian systemd | Privileged host required | NOT run: permission covers nonprivileged operator container. Real host reboot/service-manager integration remains operator acceptance. |
| 1 backup_clean_debian libpq | Opt-in | Separate nonprivileged clean Debian test passed. |
| 1 backup_restore_docker | Opt-in wrapper | Supported host CLI full backup/restore covered by current auth Compose bundled gate. |
| 2 backup_restore_postgres +11 deployment_postgres +1 first_run_zero_source | Dedicated DSNs absent in broad suite | Dedicated scoped test databases: 13 grants/restore cases plus the separate zero-source case. Pytest reports the latter at the shared deployment _environment skip location. |
| 2 container_names_docker | Opt-in | Unchanged naming feature; not rerun. Actual upgrade preserves the same DB container/mounts. |
| 1 deployment_foundation +2 external_ingress | No Docker CLI in test image | Current host CLI Compose-model cases passed separately. |
| 1 esxi_live | Live endpoint/credentials absent | Intentionally not run. |
| 1 naming_migration_postgres | Separate naming DSN absent | Unchanged historical migration; not rerun. |
| 2 probe_compose | Opt-in | Corresponding provider SOAP/probe scenarios run through broader auth/full-worker gate. |
| 1 production_proxy | Opt-in | Three actual TLS Compose modes exercise the production proxy, tmpfs, SPA/API and authority boundary. |
| 1 retirement_production_worker +1 retirement_worker_runtime | Opt-in real NetBox/socket fixture | Both separately passed. |
| 3 tls_docker | Opt-in | Standalone/corporate/external run separately; results below. |
| 4 worker_timeout_docker | Opt-in Docker | All4 separately passed using Compose capabilities and no-KILL negative case. |

Final backend runtime gates: **2 production Compose full-worker modes passed**
(338.34s); both historical upgrades repeated (**2 passed,199.48s**); real NetBox production retirement gate repeated (**1 passed,40.44s**). Three TLS modes also passed (102.58s). These backend runs use identical final Python/migration code. A subsequent UI-only correction refreshes old removal/schedule gates immediately after baseline acceptance; its component regression, all84 frontend tests and TypeScript/Vite passed. The image above includes that correction; its TLS run is recorded below.
Production worker gates cover fresh provider plan/prepare/apply, repeat no-op,
nondefault8443, VM/LXC, mappings/revision conflicts and manual/scheduled lock paths.
Guard-native real NetBox ownership/deletion is a separate gate, not simulated by
making the HTTP fixture blindly return success. The historical direct-removal test
now asserts SOURCE_RETIREMENT_REVIEW_REQUIRED and unchanged history/credentials;
it must not bypass the mandatory guard to reproduce an old unguarded workflow.

## Non-negotiable remaining evidence

**Proxmox physical host identity.** Current supported readonly paths use node names
and VMIDs scoped to the source. Neither selected `GET /nodes/{node}/status` nor
cluster status supplies the ESXi-like hardware proof used by registration recovery.
Official implementation references:
[Nodes.pm](https://github.com/proxmox/pve-manager/blob/master/PVE/API2/Nodes.pm),
[Cluster.pm](https://github.com/proxmox/pve-manager/blob/master/PVE/API2/Cluster.pm).
This is an observation about the selected paths, not a claim that every PVE API
lacks any identity. A new independently attested stable identifier and compatibility
contract is needed. DNS/IP/node names, corosync node IDs and renewable certificates
are not silently substituted. Physical-host duplicate reservation/resume/recovery
for Proxmox remains incomplete; normal Proxmox discovery/plan/apply is tested.

**Legacy provenance.** A registry record, matching UUID/name and current v2 fields
are not proof that Sync created an object. Importing historical claims requires
original immutable receipts or independently verified creation audits. This patch
exposes concrete references and preserves them; it does not manufacture claims or
provide an unsafe override. No baseline decision permits deleting unclaimed objects.

**Old incomplete registration.** Migration0011 cannot recreate a missing original
request. Old null/pending records are visible and remain reserved; request/receipt
recovery is required. No automatic administrative takeover of another actor's
pending operation is provided.

**NetBox installation/recovery.** Guard code must be updated separately while
preserving GuardIdentity, claim generations and all four journals. Its tested
version is exactly NetBox4.7.0. Complete external-NetBox logical restore previously
failed on an ltree trigger; journal-only restore is not a substitute. Operator
must establish a supported complete backup/recovery procedure and actual plugin
mount/image layout before updating that separate product. Sync's own restore passes.

**Network boundary qualification.** Broker remains `network_mode: none`; no API
NetBox/provider token mount, Docker socket, port publication or capabilities were
added. Bundled lifecycle is DB-only by network. Existing external-DB topology uses
an egress network for database reachability; it does not implement destination-only
OS firewalling. This task neither broadens it nor claims it is an IP-level ACL.

Automatic review rejected an earlier proposed custom NetBox permission-constraint
evaluator. That edit was not made. The implemented audit uses the existing native
`has_perm` against a persisted, source-constrained guard intent instead. It writes
an AUDIT_ONLY journal record (cannot execute either deletion format), not an
infrastructure object. There is no pending permission request.

## Sequential operator acceptance (no automatic writes)

1. Follow [upgrade runbook](source-sync-upgrade-runbook.md), verified backup first,
   compatible separately installed guard next, rebuilt Sync last. Confirm same DB
   volume, completed onboarding, local Admin, policy and source credentials. Stop
   if namespace, permissions, image/version or metadata differ unexpectedly.
2. Sign in as local Admin. Allow one intended destination: session remains valid;
   if recent proof expired, confirm password and explicitly retry the policy action.
3. AM, then CM: connection preview only. Record safe error and event, if any. Valid
   evidence enables placement; refusal distinguishes missing/invalid identity or
   denied inventory. Do not change host UUID or lower identity validation to pass.
4. PAM: compare the three exact supplied IDs, their histories, saved placement,
   active/removed state and inventory evidence. Do not choose by name or newest ID.
   With proven original ownership and fresh identity, explicitly recover that
   original source; expect same Source ID/history and schedule off. Mixed/absent
   proof must refuse with exact references retained for further investigation.
5. CM old UNKNOWN: ensure old writers cannot run. Review the two supplied run IDs
   and present inventory. Either preserve blockage, or explicitly accept a baseline
   with all3 acknowledgements. Expect UNKNOWN unchanged, new audit actor/time,
   schedule off and old plans unusable. A RUNNING record must still refuse.
6. Fresh Discovery, explicit mapping editor, select/create intended cluster. Confirm
   Source ID unchanged, no name auto-adoption, failed403/TLS cannot create placement.
   Build a fresh plan. First inspect only; then operator may deliberately accept a
   reviewed new plan. Never replay the old CM operations.
7. For each provider, verify host + VM/LXC + NIC inventory, IP observations and
   explicit VRFs; repeat plan must not create duplicates. Schedule only after a
   successful new manual run. Check lock conflict with a concurrent manual request.
8. Use a deliberately disposable source with proven creation claims. Review the
   complete deletion manifest, confirm once, read result after reload. Expect only
   owned infrastructure deleted, manual/shared data retained, original history and
   tombstone kept. Re-add through recovery of original namespace and new placement.
   For previously removed retained sources use Ownership reconciliation first,
   then the same separate manifest confirmation. Do not use live PAM/CM as a cleanup
   experiment without reviewing the exact affected objects.
9. Close/reopen an incomplete new ESXi registration. Continue the original saved
   attempt as its actor, enter credentials afresh, inspect exact placement, confirm.
   Expect one source/credential/cluster, not a new namespace. Old null requests are
   explicitly unsupported rather than silently reconstructed.
10. Microsoft AD: admitted direct group member appears in synchronized list as
    Viewer; assign Operator individually, rename preserves identity/role; remove
    membership/disable and verify session invalidation within configured refresh;
    DC outage/invalid CA fail closed while local emergency Admin still works.
    Operator can schedule/register, cannot recover/delete/manage users/policy.

All observations should contain only event/run/source IDs, safe codes, durations,
object references and version metadata. Do not collect secrets, env values,
provider descriptions or raw HTTP bodies in a support report.


Last UI review: accepted baseline now remounts the removal-state reader and refreshes
source, diagnostics and schedule immediately. Removed-source review no longer has a
no-op completion callback. This prevents an obsolete UNKNOWN blockade from remaining
visible until a manual reload. The component test executes the actual callback and
checks that the resource reader receives a new generation.


Final rebuilt-bundle production TLS rerun: **3 passed in95.14s**, standalone,
corporate and external. All final-source tests described above are accounted for;
only the explicitly UI-only reader-refresh fix follows the backend worker gates.
No tests or browser checks were run against the operator's VM.

Implementation commits:
* `027403bc6edfc8b131982c8d6e49aa644f17752e` — backend, migrations, guard and regressions.
* `5309b37afe1ad64e25ae51c6908da7cc47d42569` — recovery/continuation UI and regressions.
Documentation follows in a separate commit; use the final published SHA from the
delivery response as RELEASE_COMMIT, not an intermediate implementation SHA.
