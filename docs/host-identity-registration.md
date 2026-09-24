# ESXi physical-host registration and source recovery

Current recovery delivery and remaining limitations: [24 September acceptance](backend-completion-acceptance-20260924.md). Older checkpoint counts below are historical.

Status: local implementation under review, not a live duplicate remediation.

Current BIOS UUID normalization, trust limits and tested update procedure: [AM UUID review](esxi-bios-uuid-acceptance-20260924.md).

## Identity and admission

ESXi registration requires one valid hardware UUID from the authenticated provider
preview. Display name, endpoint spelling, DNS resolution, IP, and local `ha-host`
MoRef are not identity evidence. Case normalization of the UUID is permitted.
DNS/IP/alias endpoints that report the same hardware UUID claim the same identity.
Destination policy, DNS pinning, TLS and provider authentication still run normally.

The connection check rejects an existing identity. Final registration repeats the
check while reserving the UUID atomically in PostgreSQL, before catalog writes,
credential creation or schedule insertion. The reservation binds source ID, actor
and registration nonce. A session advisory lock also fences side effects of two
concurrent requests for the same reserved attempt. A busy identity returns an
immediate conflict rather than waiting for SQL timeout. A pending reservation does
not produce a link to a source row that has not been created. Failed requests do not release
the durable identity reservation merely because no source row is visible.

The actor-bound registration-status endpoint can distinguish a committed source
from an uncertain reserved attempt after API restart. It does not expose secret
values or credential references. Successful registration leaves scheduling off.
A reserved attempt without a committed source is not proof that no cluster or
credential file was created. Explicit same-attempt continuation is described below. Automatic release is not
supported; do not delete its reservation or retry with a new source ID.

Legacy source rows without a recorded hardware UUID block new ESXi registration
with `HOST_REGISTRY_REVIEW_REQUIRED`. They are not assigned UUIDs from addresses or
names. The bounded Admin verification endpoint below can acquire identity only with
fresh provider evidence and matching existing NetBox host provenance. The runtime duplicate guard protects sources with recorded UUIDs; it cannot
prove equivalence of two legacy rows with no hardware evidence.

## Removed-source recovery

Removal preserves the source namespace, tombstone, run history and NetBox objects.
A matching new connection reports `HOST_SOURCE_REMOVED`. It must not register a
replacement namespace. Admin can instead review recovery inside Add source using
fresh credentials and an authenticated provider preview. Operator/Viewer cannot
invoke recovery endpoints or obtain a recovery-bound probe receipt.

Recovery currently supports ESXi sources whose original hardware UUID and exact
NetBox site/cluster IDs were recorded during onboarding. It verifies the same UUID,
original placement, complete bounded NetBox host/VM ownership inventory, and absence
of conflicting active-source ownership. Names do not authorize adoption. Duplicate
object identities, mixed ownership, changed placement, legacy provenance and
incompatible identity kinds block confirmation. Exact repeated provenance on one
object is a repeated fact; distinct objects with that identity remain a conflict.

Confirmation is explicit. A durable lifecycle journal binds actor, source revision,
proof digest and operation ID. The lifecycle worker holds the shared apply lock and
source gate, rejects active/uncertain runs, verifies broker ownership metadata and
restores the same source ID. New credentials have a deterministic attempt-scoped
key. The root-only Unix broker metadata operation reads no secret contents. Broker
remains `network_mode: none`; no API, worker network, or public port is added.

No NetBox objects or IDs are written by recovery. Manual fields and run history
are retained. Credentials belonging to other sources are not modified. Scheduling
stays disabled; old READY plans become STALE. Old confirmations cannot reactivate
a subsequently removed source. A lost response is reconciled through the same
actor-bound recovery-status endpoint, not an automatic repeat of synchronization.

A PREPARED attempt may be abandoned before any credential effect. Once its state
is CREDENTIALS_PENDING, a timeout does not authorize deletion. With unchanged
proof and the same credentials, the same attempt can be reviewed and retried after
restart. If evidence or credentials have changed, automatic reconciliation is not
yet supported: retain the journal and secret; do not fabricate a new attempt.
Proxmox recovery is not covered. Verified legacy ESXi sources can use the same
flow, retaining their namespace and the exact verified placement.

## Existing duplicate inspection

Do not select a winner by name, address, schedule, last success, or zero counters.
Obtain only the following authorized metadata before proposing remediation:

- Exact source IDs and provider hardware UUID evidence for both entries.
- Exact NetBox site/cluster IDs (labels differing only in case are inconclusive).
- Source-scoped host/VM/interface/IP ownership identities and NetBox IDs.
- Running/uncertain operations and retained run history for each namespace.
- Credential ownership classification: exclusive or shared, without secret values.

If UUIDs are unknown, identity remains unproved. If placement differs, do not merge
it automatically. If both namespaces own objects or any operation has an uncertain
outcome, resolve ownership/outcome before any source removal or recovery. Existing
source records and infrastructure must remain intact until an administrator reviews
a concrete transition. Cross-namespace ownership transfer is not implemented here.

## Local acceptance

Use disposable PostgreSQL and controlled SOAP/HTTPS endpoints, never live ESXi:

1. Same hardware UUID through different endpoint/display-name values: existing
   source error before additional credential or cluster writes.
2. Different hardware UUID with the same name: identity is distinct; placement
   validation still applies independently.
3. Competing registrations and repeated same-attempt requests: one reservation,
   no second source; actor-bound status after a lost response/API restart.
4. Sync, remove from Sync, reconnect: ordinary registration refused; Admin reviews
   and confirms same-namespace recovery; Operator and Viewer denied on server.
5. NetBox IDs, object counts, write count and run history unchanged by recovery;
   next PLAN has zero creates/updates and scheduling remains off.
6. Changed placement/identity/ownership, stale evidence or competing recovery:
   refusal without activation, arbitrary object adoption or secret deletion.

Production Compose tests execute the lifecycle through API, broker and workers
for both bundled/external PostgreSQL. Unit address variants inject trusted preview
evidence; they are not a claim of testing real corporate DNS aliases or TLS names.


## Explicit continuation after registration interruption

This backend workflow is limited to an ESXi attempt held by the same authenticated
actor, original source ID and registration UUID. Read `POST
/api/v1/sources/registration-status` first with `source_instance` and
`registration_id`. REGISTERED links to the existing source; UNCERTAIN with
`resume_supported: true` permits a fresh connection test with `registration_resume`
containing those same two fields. The ordinary probe, policy, TLS and provider
hardware checks still run. The same UUID is required, regardless of DNS spelling.

Use the new receipt to submit the original registration parameters and nonce.
An immutable digest fences placement and metadata before catalog/secret effects.
Changing a display label in a catalog reference is harmless; changing its ID,
source name or effective port is not. Final registration holds the existing UUID
advisory lock and repeats the active/removed/unknown-source checks. Operator may
continue only their own registration; recovery remains Admin-only.

Credentials use one deterministic attempt-owned broker key, with the same broker
operation ID. A DB refusal or lost response retains that file; retry never deletes
it and cannot create a second source. A changed password after a file has already
been created is not silently substituted. Keep the original attempt and request
administrative reconciliation. No automatic reservation release/expiry is offered.
Pre-0008 attempts may have old randomly named orphan files: they are retained,
not claimed or deleted by this workflow. The ordinary UI does not yet expose a
full restart-resume wizard; these are server contracts, not a new UI acceptance.

## Verify an existing ESXi source without historical hardware metadata

Admin invokes `POST /api/v1/sources/{source}/identity-review` after successful
Discovery. Evidence must be at most 10 minutes old and identify exactly one valid
hardware UUID. The read worker resolves the configured placement uniquely, then
reads a complete bounded host/VM inventory. An existing v2 source-owned host must
match the observed UUID in the configured cluster/site. Empty inventory, old
`ha-host` provenance, foreign/shared ownership, duplicate identities and ambiguous
placement do not prove historical ownership and block confirmation.

Review returns the exact source revision, discovery_id, observed UUID/time,
recorded UUID, placement IDs, owned object IDs, blockers and digest. Confirm with
`POST /api/v1/sources/{source}/identity-confirm`, copying revision, discovery_id,
digest and `confirmed: true`. The server rereads evidence, and lifecycle holds the
shared apply lock/source gate and rechecks revision, Discovery generation and
active/uncertain work. Only the proof journal and `settings.provider_identity`
change; READY plans are invalidated. Address, mappings, credentials, schedules,
NetBox objects and Source ID do not change. Missing legacy mappings still require
explicit valid catalog choices before they can be saved; identity proof does not
invent them. A repeated identical confirmation acknowledges its historical result,
without reactivating or mutating a subsequently changed source.

The inventory digest includes provenance, not just object IDs. Changes to VM
identity with the same NetBox ID invalidate review. Proxmox verification and legacy
identity schemas lacking sufficient evidence remain unsupported, not auto-adopted.

## Minimal read-only evidence for the two ESXI-INFRA entries

No winner has been established locally. The earlier authorized browser read was
blocked with ERR_BLOCKED_BY_CLIENT (no reason supplied); this is not bypassed.
No live removal, rebind or replay of uncertain work is authorized by this document.
After a separately reviewed deployment, an Admin can run Discovery sequentially
for `esxi-4b77b54e47284ce9b284` and `esxi-ad122549fb584d448ce7`, then call
`POST /api/v1/sources/identity-audit` with `sources` containing those two IDs.
This is read-only; it reports SAME_OBSERVED_UUID, DISTINCT_OBSERVED_UUIDS or UNPROVED,
individual proof/error, and never selects an owner or performs remediation.

Supply only that bounded report plus running/uncertain run IDs/statuses and
credential ownership classification (exclusive/shared/absent). For any proposed
cross-namespace transfer, additionally obtain source-scoped interface/IP IDs and
provenance from NetBox; this audit currently reads hosts/VMs only. Do not supply
tokens, passwords, cookies, env files, private keys, descriptions or full responses.
A timed-out Discovery cannot prove identity. If either source has no owned host,
or both namespaces own objects, retain both and resolve ownership explicitly;
there is no safe automatic deletion based on names, address or empty Runs.
