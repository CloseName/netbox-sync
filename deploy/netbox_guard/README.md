# NetBox-side guarded lifecycle (integration in progress)

This optional package is **not installed or enabled by NetBox Sync Compose**. It
has no HTTP routes yet. Sync still refuses destructive retirement. Do not install
it on a live NetBox as a completed product workflow.

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

These are internal service methods, not browser payload schemas. Remaining product
work includes narrow authenticated transport/serializers, trustworthy legacy claims,
Sync Admin confirmation, registry revision/generation fencing, shared lock/source
operation checks, durable multi-phase coordination, orphan reconciliation, upgrades
and explicit capability/preflight handling. Lifecycle/broker privileges and product
Compose have not changed. The broad table fence also needs an end-to-end execution
budget and its operational impact must remain explicit.

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
