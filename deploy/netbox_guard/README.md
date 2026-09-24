# NetBox-side guarded lifecycle

This optional package is **not installed or enabled by NetBox Sync Compose**. It
now exposes a narrow token-authenticated HTTP protocol when explicitly installed.
Guard-backed source retirement and present-inventory audit are implemented.
See [current acceptance and limitations](../../docs/backend-completion-acceptance-20260924.md).
Legacy objects without authoritative creation proof remain protected.

The locally tested target is NetBox Community 4.7.0 / Docker-5.1.1, image digest
1685e91c61bb4050089db2bb1603718820ae3ce0b266d4d069ff7c682f5d9c58.
Unknown plugins/schema/SQL-hook fingerprints fail closed. The independent package
needs Django/NetBox, not Sync runtime dependencies. It defines a creation-claim ledger and append-only receipt/intent records
(no general-purpose CRUD API): creation claims, creation receipts, retirement
intents and retirement receipts. Claims are invalidated on object deletion; the
independent receipts remain for audit.

## Implemented transaction service

- `create_owned` creates a new allowed infrastructure object and a claim/receipt
  in one transaction. It does not adopt existing IDs. Nonce/actor/source/payload
  fencing returns the same object after a lost response; conflicting retries fail.
  Foreign-object references are hashed by model/ID, never by display name.
- A claim records the exact object generation (`created`) and source/placement.
  Ordinary model deletion invalidates it; a new object reusing the ID cannot inherit
  the claim. Existing managed v2 identities are not retroactively creation proof.
- `review` freezes one exact root's deletion closure and hashes its stored values,
  actor, source and current cluster data. It refuses missing/foreign/shared claims,
  foreign v2 provenance, changed placement and external dependency changes.
- `retire` rechecks the same snapshot under the dependency fence. Only its verified
  Django Collector may delete. The count/type effects must match exactly. Claim
  invalidation and the independent receipt commit with the deletion. Receipt write
  failure rolls all of it back. A duplicate confirmation returns the old receipt.
- NetBox uses PROTECT for VM→cluster and SET_NULL for device→cluster. The caller
  must sequence confirmed leaf phases before the empty cluster; never assume an
  ordinary cluster DELETE removes that inventory. A manually provided/shared
  cluster may remain while its source-created child retires.
- Permissions are NetBox ObjectPermissions on `CreationReceipt` action `create`
  and `RetirementIntent` action `retire`. Constraints are checked against the
  persisted record **inside** the transaction; mere permission-name presence is
  insufficient. The test uses a non-superuser constrained to one source. No
  standard delete permission is granted to an application token by this package.

The fixed API uses standard NetBox serializers, ordinary constrained add permissions
plus source-constrained guard permissions, and a durable installation UUID on every
request. Read-only/revoked tokens cannot mutate; no generic delete endpoint exists.
The private Sync client requires verified HTTPS, forbids redirects and never retries
a write automatically. It is now connected to a separately isolated production retirement worker; see
`docs/source-retirement-integration.md`. Remaining
product work includes trustworthy legacy claims,
orphan reconciliation, complete provider/re-registration/upgrade gates and historical
claim migration. Sync Admin confirmation, revision/generation fencing, shared lock,
source/run checks and durable receipts are integrated. Only the new retirement worker
has the approved NetBox mount/egress; lifecycle remains DB-only and broker networkless.
Whole-source retirement has a 30-second budget, 10-second statements, 2-second lock
wait and a 10,000-object bound. The broad table fence still has operational impact.

## Executed local evidence

`netbox_retirement_protocol_scenario.py`: actual PostgreSQL/NetBox create, claim,
review, delete, rollback on receipt failure, nonce conflict, changed placement,
foreign provenance, manual child, concurrent confirmations, ID reuse, leaf→cluster
completion, new generation and retained common catalog/manual placement.
`netbox_atomic_dependency_scenario.py`: real concurrent generic-relation writer,
bounded contention refusal, changed snapshot, external SET_NULL, unknown table and
trigger refusal. `netbox_guard_generate_migration.py`: no missing migrations.

`run_netbox_guard_backup.py` is an opt-in operator harness against the verified
isolated networkless PostgreSQL fixture. It creates a separate template copy,
clears ONLY its four guard tables, then uses real pg_dump/pg_restore for those
journals. The restored receipt returns without another mutation; remaining owned
inventory and claims are unchanged. This is **journal recovery against preserved
NetBox state**, not a passing full-NetBox backup/restore test.

The full vanilla NetBox schema dump/restore independently failed creating an ltree
trigger: `operator does not exist: public.ltree = public.ltree`. No schema/search_path
workaround was introduced. PostgreSQL documents the corresponding trigger-expression
and restricted restore search_path limitation:
https://www.postgresql.org/message-id/17134-41b9adb547cb6e8e%40postgresql.org
https://www.postgresql.org/message-id/CAKFQuwZtC_xPgf%2BWSSxDEC5oftUrvhyr8QzKGZuErMxM-CEpog%40mail.gmail.com
A supported complete external-NetBox recovery procedure remains a deployment gate.
Sync's own backup/restore code was not changed by this test.

## HTTP protocol checkpoint

The route prefix is `/api/plugins/netbox-sync-guard/`. Capabilities are read-only;
`objects/create/`, `retirements/review/`, `retirements/execute/` use fixed request
schemas. A receipt is read at `retirements/<nonce>/`. Requests pin
`X-Netbox-Sync-Guard-Instance` to the persisted UUID created by migration 0002.
Fresh unrelated NetBox databases cannot accept an old installation's intent.
A restored database deliberately preserves its installation UUID; clone handling
and deployment pinning remain coordinator work, not automatic URL-based trust.

`tests/netbox_guard_http_scenario.py` passed against real NetBox WSGI and PostgreSQL
over loopback HTTPS with a locally generated short-lived test certificate, verified
by the client (no insecure TLS). It covers scoped cluster/device/physical NIC/IP,
VM/virtual NIC/IP/MAC/disk; create replay; source/read-only/revoked-token refusal;
wrong namespace; VM→device→cluster receipts and retained shared catalog. It executes
Sync's GuardClient for capabilities, creation retry, review, execute retry and receipt.
17 focused transport tests cover no retry, safe refusals versus uncertain responses,
redirect refusal, bounded response, TLS and wrong namespace/nonce.

Protocol regression also passed same-cluster IP reassignment to a manual NIC and
malformed parent identity refusal. Matching placement alone does not grant ownership.
The guard journal backup test passed again after 0002, as did migration completeness.
The journal-only dump deliberately includes the four creation/retirement tables;
the preserved template DB retains its namespace. This still does not establish the
full vanilla NetBox schema restore gate described above.

HTTP CREATE retries are resolved before ordinary uniqueness validation using the
server's exact wire-request digest and the original receipt. Generation, ownership,
placement and current permission are still checked. A serialization failure after
commit is an uncertain response, not a definitive rejection. This was reproduced
and fixed against a real VM API request; retry creates no duplicate and preserves
a later manual comment. A changed retry is refused. Experimental older HTTP digest
records are not automatically converted; internal service receipts are unchanged.
The complete transport/review selection passed 32 tests under Linux.

## Read-only reconciliation of a lost creation response

`GET /api/plugins/netbox-sync-guard/objects/receipts/<nonce>/` reads an existing
creation receipt. It requires the same authenticated NetBox principal and current
creation/object permissions, the pinned guard UUID, an intact creation claim and
unchanged object generation/ownership/placement. It performs no CREATE or retry.
The returned original intent digest allows Sync to verify the exact source,
resource and request payload. Absence of a receipt does not establish that an
interrupted request could not have committed elsewhere; callers retain uncertainty.

The catalog worker uses this route for a protected registration-cluster journal.
The application verifies that current cluster name/type/site still match the
original request before marking that journal CREATED. It does not change manual
fields or claim a catalog match by name. The source registry is reconciled
separately. Existing installations need the new plugin code for this route, with
no migration or change to the certified 45-trigger schema. Old guard versions
refuse this new read path and must not trigger a fallback POST.


## Present-inventory audit and this code update

`POST sources/<source>/audit/` takes an exact nonce and preserves the pinned guard
identity. It requires existing source-constrained `retire` permission and view
permissions for each returned object. A persisted format3 AUDIT_ONLY intent is
checked with native NetBox `has_perm`; it cannot execute retirement format1/2.
The response contains exact model/ID, present/claimed flags and fingerprints, not
raw object/description/secret contents. It is current evidence, not proof of old
write completion. A retry is actor/source/nonce-bound; no claim adoption exists.

No plugin migration, trigger, new ObjectPermission action or identity rotation is
needed by this update. Preserve existing GuardIdentity and all claims/receipts.
The optional JSON `sync_identities=null` default is treated as absent; malformed
values, foreign identities and missing exact creation claims remain rejected.
Independent package installation is still owned by the NetBox operator; see the
conditional upgrade instructions in the Sync upgrade runbook. No automatic NetBox
container/image management was added to this repository.
