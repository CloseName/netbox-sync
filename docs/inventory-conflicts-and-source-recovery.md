# Inventory conflicts and source recovery — work in progress

Base: `38cb0ff25fe3550131dd494abe2ac0f50f023a4a`. Local work only; no live connections, deployment or push.

## Implemented conflict handling

The source identity schema is unchanged. ESXi VM identity still prefers instance UUID,
then BIOS UUID, then MOID. MOID is retained separately as diagnostic provenance; it
is not a new ownership key. Different MOIDs sharing the effective UUID are not merged.
Repeated references to the same managed object within one host are collected once.
Repeated guest records for a NIC merge address facts instead of overwriting earlier facts.
Canonical planning/apply removes identical normalized address facts within one NIC only.
Different prefixes for the same address remain a conflict, including within one NIC.

Inventory ambiguity is returned as a BLOCKED plan with typed participants, rather than
caught as an arbitrary planner exception. Participants contain only VM name, effective
identity, provider object reference, host identity, interface identity/name and address.
No VM descriptions, credentials or provider response bodies enter this report.
NetBox failures are not suppressed. Public operation access retains existing server
permissions. Prepare still recomputes the plan and refuses `PLAN_BLOCKED / PLAN_FORBIDDEN`.
The planner version is now `web-5a-4`; old reviewed plans require rebuilding.

The current discovery/target contract has no per-NIC VRF or address-realm identity.
Different bridge names or VLAN IDs are therefore NOT proof of separate IP namespaces.
The report detects duplicate host addresses even when prefix lengths differ. Link-local,
loopback, multicast and unspecified addresses retain the executor's exclusion policy.

The EN/RU Plan screen presents a summary and expandable participant lists. Its confirm
button remains disabled for blocked plans. Opening a source Overview also reads the
existing authorized operation endpoint and surfaces a persisted blocked plan, even
without a successful run. PostgreSQL persistence and reload are tested. This does not
add operation evidence to the global Sources/Diagnostics aggregate; that remains a gap.
Existing operation-result retention/expiry is unchanged.

## Proven processing defects versus live evidence

Local regressions prove:
- repeated host.vm references could yield the same discovered VM more than once;
- repeated addresses within a NIC could become a false duplicate-IP exception;
- later guest records overwrote earlier addresses for the same NIC;
- Proxmox re-registration under a new source_instance with retained NetBox objects
  passed a name/IP review and then raised HostApplyError during planning. Recognized
  managed-name/IP candidates now return OTHER_SOURCE_OWNERSHIP before the executor.

These findings do NOT establish which specific VM/address caused either reported live
failure. Cloning, NetBox duplication and collector regression are not proven live causes.
The real conflicting participants can be determined only after deploying diagnostics.

## Executed checks

- Initial targeted backend: 50 passed; worker/collector compatibility: 59 passed,
  2 cross-UID opt-ins skipped in that invocation and executed separately.
- Full available networkless Linux backend at the intermediate checkpoint:
  1036 passed, 118 skipped. Opt-in DB, Compose, cross-UID and live tests are not
  implicitly covered. Later changes received the targeted reruns below.
- Final affected backend including real HTTPS/SOAP + actual production discovery-worker
  child under UID 10001: 98 passed. Covers successful PLAN, IP/identity conflicts,
  bounded timeout/reaping, prepare refusal, first sync/replan fixture paths and
  147-VM batch completeness/request-count equivalence. No live apply.
- Isolated PostgreSQL persistence/lifecycle/plan subset: 48 passed after correcting
  tuple/list canonical projection. Existing delete fencing, retained identity/history,
  exclusive/shared credentials and operation generation checks included. Temporary
  DB/container/network resources were removed after verifying their test labels.
- Complete affected Playwright file: 23 passed, including EN/RU conflict expansion,
  disabled confirmation, reload and Overview attention. The initial two failures
  were test expectations of an absent button instead of the existing disabled button.
- Frontend unit: 70 passed after adding the missing Interface translation.
- TypeScript/Vite passed; existing >500 kB bundle warning remains.
- No full production Compose image rebuild or actual-hypervisor acceptance claimed.

## Sequential stand acceptance — PLAN only

After a separately reviewed deployment:
1. Open ESXI-AM-QA2 (`esxi-169610c2cd1c4abfac2c`). Build exactly one new PLAN.
   Wait for completion; record operation ID, time and phase durations.
2. If blocked, expand every conflict and record the displayed VM/host/NIC identifiers
   and conflicting value in an access-controlled acceptance record. Reload the page,
   then open Overview and verify the problem remains visible. Confirm must be disabled.
3. Only after the first operation finishes, repeat PLAN for ESXI-PAM-QA
   (`esxi-302fb3e24e1e40a8880e`) and collect the same evidence.
4. Do not prepare/apply, remove/re-add sources, edit NetBox identity metadata, or retry
   ESXI-CM-QA uncertain operations. A timeout or generic error is an acceptance failure,
   not permission to retry writes. A blocked conflict with identifying evidence is an
   expected diagnostic outcome, not proof that the underlying inventory is repaired.

## Delete/re-add: confirmed architecture and remaining implementation

Removal keeps the sources row and Run History, disables enabled/sync_enabled, and
creates a durable source_tombstones reservation. Credential cleanup is optional and
only permitted for proven exclusive broker-owned references. NetBox ownership metadata
and objects are untouched. Removal holds the shared apply lock and source gate and
refuses active or uncertain/partially-applied runs. Current UI already explains retention.
The old source_instance cannot be registered automatically. A newly generated ID is a
new ownership scope even if address, credentials and names are unchanged.

A local real-pynetbox HTTP regression synchronizes fixture ESXi/Proxmox objects and
then plans the same inventory under another source_instance. It proves no automatic
acquisition, writes or object changes; it is NOT a complete deletion/recovery workflow.
The Proxmox exception was reproduced before the ownership-conflict correction.

**Administrator-confirmed recovery is NOT implemented by this change.** No recovery
endpoint, permission, migration or rebind write has been added. The combined user task
is not complete. Remaining gates include a full DB-backed remove/re-add workflow,
trusted recovery preview/confirmation, concurrent/partial/idempotent recovery tests,
active-other-source rejection and the global Sources/Diagnostics status projection.
Do not publish this checkpoint as completed source-recovery functionality.

Required safe design for the remaining implementation:
- Build a server-produced, expiring recovery proposal through a read-only provider/
  NetBox worker. Include old/new source revisions, placement fingerprint, exact retained
  object IDs and ownership snapshots, and stable provider identity evidence. Never
  accept a browser-supplied owner/object list as authoritative.
- ESXi hardware UUID can contribute evidence; a fallback MOID, address or name cannot
  prove server continuity. Existing Proxmox node-name/VMID data does not prove the
  physical server/cluster is the same. Legacy sources without sufficient anchors must
  remain blocked with an explicit insufficient-evidence explanation.
- Prefer reactivating the reserved original source identity over rewriting every NetBox
  identity. Preserve the tombstone as historical evidence and append a recovery audit
  event; do not delete history. This needs an explicit DB lifecycle state transition,
  not deletion of the tombstone or reuse by ordinary registration.
- Require a server-checked administrator permission and explicit review of the proposal.
  Under the shared apply lock and ordered source gates, recheck both revisions,
  tombstone status, placement, worker inactivity/uncertainty and current ownership.
  Reject active other owners or ambiguous identities. Credentials remain source-scoped;
  lifecycle receives references only, never provider secrets or NetBox tokens.
- Commit registry/recovery-journal changes atomically with an idempotency key. Keep
  automatic sync disabled. Partial external effects require reconciliation, never a
  blind replay. Old credential cleanup is a separate proven-exclusive broker action.
- Validate same server, replacement server at same address, same names/different IDs,
  changed placement, active foreign owner, duplicate confirmation and crash boundaries.
  Preserve NetBox IDs, manual fields and provenance throughout. No live writes here.

## Separate managed-cleanup design (not implemented)

A future cleanup proposal must enumerate exact owned object IDs, current ownership
fingerprints and dependency edges. Require a separate administrator permission and
confirmation independent of source removal/recovery. Revalidate ownership and
references under the shared lock immediately before each permitted action; journal
partial/uncertain outcomes and stop rather than retry blindly. Shared sites, clusters,
prefixes and foreign objects never enter the set merely through name matches. Default
source removal remains retain-only. This checkpoint introduces no NetBox deletion.
