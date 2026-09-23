# Retirement: review contract and execution decision

2026-09-22. This replaces the earlier comment-only proposal as a product target.
**Destructive execution is not implemented or enabled.** Local review/journal code is
`netbox_sync/retirement_review.py`. It is not wired into an API, an installer hook,
source removal, a worker loop, or a scheduler. Existing removal still retains NetBox.

## Implemented, locally reviewable boundary

`build_review` takes trusted, complete registry and NetBox evidence, not browser object
IDs. It returns exact resource/ID candidates, retained objects, dependency blockers,
and fingerprints. `RetirementReviewJournal.record` persists an immutable BLOCKED
review under a UUID and authenticated-actor reference. Identical retries return the
same document; reuse with different content/actor fails. The existing shared apply
lock and root-protected atomic/fsynced file store protect local writes. No credentials
or raw provider responses belong to the evidence. No new capabilities, mounts, DB
roles or NetBox token privileges were introduced.

Every review includes `ATOMIC_NETBOX_GUARD_UNAVAILABLE`; `execute` always refuses.
This is a durable **review**, not an executable deletion capability or a completed
source-deletion workflow. Deployment adapters for authoritative snapshots and Admin
confirmation remain to be implemented after the execution contract is selected.
The caller must establish Admin identity; this library is not an authorization endpoint.

Snapshot objects distinguish cluster, device, VM, interface, VM interface, disk, IP,
and MAC. Names are labels only. Each needs both exclusive source ownership and
separate proof that Sync created it. A managed v2 identity alone does not prove creation
and cannot authorize deletion of an adopted/manual object. Shared IP/MAC, manual
children, missing dependencies and outside references are retained/blockers.
Sites, cluster types, manufacturers, prefixes, VLANs and other common catalogs are
not candidate resource types.

Only a durable removal intention/tombstone can propose retirement. An absent row in
an incomplete or failed registry read, a disabled source, or missing discovery VM is
never an intention. A source absent even from a complete registry without tombstone
is an orphan requiring investigation. Any uncertain sync outcome blocks retirement.

A different current source using the same stable cluster ID blocks an old tombstone's
review even when it has the same display name, address or provider. This specifically
protects PAM/AM re-registered with new IDs in clusters 5/4. New registration in an empty
cluster is not recovery of the original source identity and does not transfer old
object ownership. Historical cluster-creation claims are not inferred from placement.

## Minimum NetBox-side guarded-delete proposal (not implemented)

Support NetBox Community **4.7.x only initially**, with a tested model/dependency
schema digest. Unknown versions/plugins/relations fail closed. An optional NetBox-side
extension exposes a narrow retirement endpoint, not arbitrary URL/model deletion.
It requires a dedicated NetBox permission/token and accepts a fixed manifest, nonce,
source identity, reviewed object IDs, before-fingerprints and deletion order. The Sync
API still requires Admin; the API/broker never receive the token.

Within one NetBox database transaction:

1. Serialize the nonce; an existing receipt must match the exact manifest digest.
2. Acquire bounded locks in deterministic order on every candidate and relevant
   dependency table. Parent row locks alone are insufficient for generic relations.
   Table-level locks must prevent concurrent inserts/updates in the enumerated relation
   set; arbitrary plugin tables are unsupported, not silently omitted.
3. Recheck ownership, creation claims, placement, all inbound/outbound relationships,
   and the exact current dependency closure. Use Django's deletion collector to
   compare the actual cascade and field updates against the reviewed manifest.
   Reject unknown fast-delete/queryset paths, foreign field updates, custom hooks or
   relationships whose effects cannot be bounded. Do not rely on NetBox returning a
   protection error for every possible relationship.
4. Perform exactly that validated deletion; persist an independent idempotent receipt
   and audit in the same transaction. If any check/write fails, roll back all changes.
5. Return the receipt. A lost response is resolved by reading/reusing the same nonce,
   never by issuing a new unguarded DELETE. The receipt survives removal of the objects.

This design needs a real NetBox 4.7 database/integration test including external
concurrent writers, GenericForeignKey dependencies and deletion signals. It is not
proven by a fake HTTP server. Lock timeouts and all unsupported relations return a
reviewable blocker. It may temporarily block other writers to relevant tables; that
operational trade-off must be accepted before installing an extension.

Sync must durably journal Admin intent before remote execution; serialize with
apply/scheduler and source gates; recheck registry revision/current ownership and
unknown outcomes; use the same remote nonce on recovery. Do not enable old tombstones
at upgrade. Every old source needs a fresh explicit review. Existing NetBox delete
permissions must not be expanded without deploying the narrow guard contract.

## Limited alternative without a NetBox extension

Ship read-only reconciliation, a complete candidate/preserved-object report and a
BLOCKED review journal only. An operator may use NetBox's own reviewed administration
outside Sync, but Sync must not claim to coordinate or safely retry those deletions.
Even deleting a seemingly empty parent after a GET leaves a concurrent-write gap;
an ordinary REST DELETE cannot supply the above atomic guarantee. No automatic
cascade or mass cleanup is offered by this alternative.

Local implementation of the guarded-delete extension is authorized. Its installation
on the external NetBox is a separate deployment action. Review-only cleanup is the
current limitation, not a replacement for the requested executable workflow.
No extension was installed and no live object was deleted during development.

## Local NetBox 4.7 counterexample (23 September)

The pinned NetBox Community 4.7.0 image was tested against a dedicated local DB.
`tests/netbox_guard_contract_scenario.py` creates a VM/NIC, records the VM version,
then inserts a separate IP assigned through the NIC's generic relation. The parent
`last_updated` is unchanged, yet the IP enters Django's deletion collector for the
VM. All records roll back; DELETE is never executed. This is a deterministic
interleaving, not a threaded race or a passing atomic-guard implementation.

The installed API code rechecks If-Match under a parent row lock in
`perform_destroy`; that does not supply a dependency-manifest check. See the
[official 4.7 viewset](https://github.com/netbox-community/netbox/blob/v4.7.0/netbox/netbox/api/viewsets/__init__.py)
and [IPAddress generic assignment](https://github.com/netbox-community/netbox/blob/v4.7.0/netbox/ipam/models/ip.py).
The guard proposal remains an implementation gap, not a reason to ask again for
permission to perform already authorized local development. Installing such a guard
on an external NetBox would be a separately reviewed deployment action.


## Dependency-fence implementation checkpoint

`deploy/netbox_guard/dependencies.py` now implements a NetBox-side transaction
context, independently of Sync runtime dependencies. It is not a registered plugin,
HTTP endpoint, ownership claim, receipt store, or source-removal executor. No
production service loads it and ordinary REST deletion remains unavailable.

Within an independent PostgreSQL transaction it obtains deterministic SHARE ROW
EXCLUSIVE locks on the managed NetBox tables, then uses the actual Django Collector
(including fast-delete querysets and field updates). It fingerprints concrete
stored values without returning raw contents. Any external SET_NULL target,
unknown dependency, changed manifest, unknown table/plugin/SQL trigger, invalid
root or failed database read refuses. Contention has a two-second lock timeout;
individual statements have a ten-second timeout. These are not yet an executor's
end-to-end deadline. Only the pinned NetBox 4.7.0 model has been tested.

This deliberately conservative table fence protects generic relations that have
no database foreign key. It also temporarily blocks unrelated writers: it is not
a production-ready locking budget/topology. A narrower certified relation set,
overall execution deadline, broader schema validation, creation provenance,
idempotent transaction receipts, authorization and source lifecycle integration
still belong to the remaining executor work. None is inferred from this primitive.

Executed `tests/netbox_atomic_dependency_scenario.py` against the real NetBox
4.7.0 image with isolated PostgreSQL and Redis (normal model callbacks enabled):
changed cascade despite unchanged parent version; changed manual field; concurrent
IP generic-assignment insertion refused while fenced and successful after release;
existing writer causes bounded refusal; later retry succeeds; a surviving VM's
primary-IP reference blocks deletion closure. No retirement DELETE executes.
Cleanup removes only the scenario's exact fixture IDs in its fixed isolated DB.
The first attempts exposed missing pynetbox coupling and missing Redis in the
model harness; the guard was separated from Sync imports and Redis supplied.

The final repeat also passed refusal on an additional table and an additional SQL
trigger. Vanilla NetBox has 45 SQL triggers; the guard pins their full definitions,
function bodies and enabled states, not merely their names. The first strict hook
check intentionally refused that standard schema; the final version recognizes
only the exact checked migration fingerprint. No production deployment is implied.


## Transaction service checkpoint (after f7c466f)

The optional `deploy/netbox_guard` now has actual NetBox migrations, creation
claims/receipts and per-root retirement intent/receipt service methods. Real
NetBox/PostgreSQL deletion, transaction rollback, source-constrained permissions,
concurrent nonce replay and new-object generation were tested. See its README for
exact coverage and the independent full-schema ltree restore blocker. This advances
the server-side protocol; Sync's review remains non-executable because HTTP,
legacy claim proof and lifecycle/orphan coordination are not wired. No live plugin
was installed and no product token/service permissions were expanded.
