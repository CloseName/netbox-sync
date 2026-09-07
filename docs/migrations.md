# PostgreSQL migration procedure

WEB-0 introduces Alembic, isolated from synchronization. Never run this procedure
against production without an approved backup and restored-copy rehearsal.

Use the supported versioned bundle in [Backup and restore](backup-restore.md). Restore
recreates fixed roles through tracked provisioning, restores a logical custom-format
dump, runs only known forward Alembic revisions, and reapplies the grant matrix. It
rejects newer schema revisions and never merges a populated registry.
No migration has been run against production by this change.

## Tooling and execution

The canonical deployment runs the migration from the packaged application image; host
Python and a host virtual environment are not required:

```sh
docker compose --env-file /opt/netbox-sync/config/compose.env \
  -f /opt/netbox-sync/current/compose.production.yml --profile tools \
  run --rm --no-deps netbox-sync-migrate
```

For development only, `python -m pip install -r requirements-migrations.txt` followed by
`alembic -c alembic.ini upgrade head` remains supported. In that mode supply
`NETBOX_SYNC_REGISTRY_DSN` and `NETBOX_SYNC_REGISTRY_SCHEMA` through the operator's
protected environment. The canonical one-shot instead reads its owner password from
the protected infrastructure-secret directory and builds the connection internally.
Do not put either credential in alembic.ini, command arguments, logs or source control.
Do not use `stamp` to bypass validation. Offline SQL generation is rejected because
existing-table validation requires a live PostgreSQL connection.

## Baseline behavior

- Clean schema: create sources and schema_meta using a frozen v1 definition.
- Existing v1: validate exact columns, types, nullability, defaults, primary keys,
  source_instance uniqueness, safety checks and schema_version. Do not rewrite
  source rows, timestamps, identities, flags, references or settings.
- Partial/unknown/drifted schema: fail and roll back. Investigate on a copy; do not
  "repair" production by deleting tables or manually stamping a revision.
- Alembic version table lives in the selected registry schema, not public.
- A transaction-scoped PostgreSQL advisory lock serializes these migration
  processes. DDL and the revision marker commit together. Lock waits are bounded.
  Legacy initialize() does not take this lock: keep administrative DDL/bootstrap
  stopped during migration. Runtime never invokes migrations automatically.
- Repeating upgrade head does nothing after success. Downgrade is deliberately
  rejected. Use additive, reviewed forward fixes; do not autogenerate drops.
- Revision `0002_sync_run_history` adds only `sync_runs`, its constraints and
  indexes. It does not update `sources`, `schema_meta`, identity metadata or the
  legacy registry version (`schema_version=1`). An existing exact v1 registry is
  first validated/stamped by the baseline in the same migration transaction,
  then receives the additive history table. A partial, drifted or newer legacy
  schema still fails closed before WEB-6 DDL is committed.
- Revision `0003_netbox_sync_naming` is a schema-neutral marker after the explicit
  operator database/schema transition. It accepts only canonical `netbox_sync`, plus
  uniquely named schemas inside the separately guarded `netbox_sync_test` database;
  it creates, updates and deletes no application rows or objects.
- Current SourceRegistry.initialize() remains unchanged for compatibility. Once
  migrated, operators use Alembic for schema evolution rather than extending
  initialize(). Future revisions must remain independent of mutable runtime code.
- Before Alembic begins, the canonical migration command verifies ownership of the
  database, registry schema and all existing registry tables. Existing objects must be
  owned by `netbox_sync_owner`; a mismatch fails before DDL. Ownership is never silently
  reassigned by the migration command.

The migration owner is provisioned separately from runtime roles. The tracked
`netbox-sync-db-grants` operation reapplies the exact least-privilege matrix after
migration; see [Deployment](deployment.md#database-lifecycle-and-roles).

## Validation

Unit tests validate revision discovery, offline rejection, frozen schema and drift
checks without a server. Opt-in integration tests exercise a clean install,
populated legacy adoption, repeated upgrade, unknown version and rollback. Set
`NETBOX_SYNC_TEST_POSTGRES_DSN` only to a disposable database named `netbox_sync_test`.
Tests create unique schemas and remove only their own schemas on cleanup. Never
point this variable at a production database. PostgreSQL tests may skip when the
test DSN is absent; such a pass is not evidence of a live migration rehearsal.

WEB-6 adds opt-in round-trip coverage for RUNNING/terminal lifecycle, duration,
counts, snapshots, newest-first listing and filters. The migration owner remains
separate from the runtime run-writer role. Exact runtime grants and the production
rollout checklist are documented in [Web deployment](web.md#web-6-durable-run-history).

The connection-sharing/transaction approach follows the
[official Alembic cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html#sharing-a-connection-across-one-or-more-programmatic-migration-commands).

## UI-6 forward revisions

`0004_source_operations` follows `0003_netbox_sync_naming` and adds bounded latest
PLAN/DISCOVERY slots with a composite source/kind key and unique generation UUID.
`0005_source_tombstones` follows it and is the current head. It reserves removed source
IDs without deleting source/history rows or creating a cascading relationship.
Historical migrations remain unchanged; downgrade remains deliberately unsupported.

The credential-reference trigger is invoker-security with a fixed `pg_catalog` search
path. It takes a shared transaction gate before new reference assignments and rejects
references reserved by a tombstoned source. Removal holds the matching exclusive gate
while checking exclusivity and cleaning up; concurrent assignment cannot steal a file
being removed. Unchanged-reference schedule/lifecycle updates bypass unnecessary checks.
Tracked grants give only the required readers access to tombstones and operations.
Runtime services never migrate or obtain DDL/DELETE/TRUNCATE authority.

New schemas, populated upgrades, repeated upgrade and actual role-forbidden writes are
covered by PostgreSQL integration tests. Restore rehearsals invalidate interrupted work
and READY review context; see [backup/restore](backup-restore.md).
