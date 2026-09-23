# ESXi physical-host registration and source recovery

Status: local implementation under review, not a live duplicate remediation.

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
credential file was created. Automated release/resume of such abandoned attempts
is not implemented yet; do not delete its reservation or retry with a new source ID.

Legacy source rows without a recorded hardware UUID block new ESXi registration
with `HOST_REGISTRY_REVIEW_REQUIRED`. They are not assigned UUIDs from addresses or
names. An administrative identity acquisition workflow is still required for these
rows. The runtime duplicate guard protects sources with recorded UUIDs; it cannot
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
Proxmox recovery and legacy identity acquisition are not covered by this flow.

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
