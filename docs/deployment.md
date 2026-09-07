# Canonical v1 deployment foundation

This is the supported clean-install foundation. It is code-ready but does not
authorize a production cutover. Rehearse it on a disposable Debian host and a
restored database before changing an existing installation.

## Topology

`compose.production.yml` defines one stable Compose project (`netbox-sync`), one
application image and separate API, discovery, apply, schedule, secret-broker and
transient scheduler processes. Bundled PostgreSQL 16 is the default. Its deterministic
volume is `netbox-sync-postgres-data`, it is attached to the private `netbox-sync-db`
network and it has no host-published port. The API also joins a dedicated Web bridge
for its loopback-published port. Discovery, apply and scheduled execution
also join `netbox-sync-egress` for normal HTTPS connections to providers and NetBox.
There is no NetBox Docker-network dependency. The broker uses only the internal DB network and the
schedule worker has DB access only.

The runtime boundaries remain separate. In particular, the API has no source-secret
or NetBox-token mount and no schedule/run writer DSN. Migration/owner and bootstrap
credentials are mounted only read-only into explicit root one-shot tool containers.
The transient scheduler also runs as root with all capabilities dropped so it can read
root-owned 0600 source/NetBox files; it receives no host-control socket. All persistent
source credentials use the shared broker directory; onboarding a source requires no
Compose edit.

## Host layout

```text
/opt/netbox-sync/
  releases/<release-id>/       immutable packaged release
  current -> releases/<id>     atomic active-release link
  config/                      generated service-specific env files (0750/0600)
  secrets/infrastructure/      generated database passwords (0700/0600)
  secrets/sources/             broker-managed source secrets (0700/0600)
  secrets/netbox/              read-token and apply-token files (0700/0600)
  backups/                     protected complete Backup Format v1 bundles (0700)
  state/                       future persistent operator state
/run/netbox-sync/               shared apply lock (0750)
```

Release directories and code are normalized to 0755 directories, 0644 data/code and
0755 executables. Secret creation uses exclusive `O_CREAT|O_EXCL`, explicit 0600 and
`fsync`; it never changes process-global umask. The installer never overwrites an
existing password. Do not copy secrets into a release directory.

## Fresh Debian foundation

Prerequisites are Python 3.10+, Docker Engine with Compose v2, systemd, `flock` and
`install`. The installer itself uses only the Python standard library; database and
migration code runs inside the application image.

From an unpacked reviewed release:

```sh
python3 deploy/install.py --check
sudo python3 deploy/install.py --release-id <release-id>
```

`--check` is read-only. Every install requires an explicit release ID; an existing ID
may be reused only when its packaged content is identical. `--prepare-only` performs
image/database preparation while leaving `current` unchanged and the timer stopped.
`--no-start` activates prepared files and installs units without starting application
services or the timer. `--no-systemd` omits unit installation; an upgrade still uses
the existing timer and shared-lock coordination when systemd is present.

The normal flow is explicitly split into PREPARE and ACTIVATE. PREPARE copies and
validates an immutable release, creates a protected staged configuration, validates
and builds the Compose artifact, starts/waits for PostgreSQL, bootstraps roles, checks
legacy object ownership, migrates and reapplies grants. It does not change `current`.
ACTIVATE publishes the staged config, atomically switches `current`, installs units,
starts the long-running services, verifies that they and API liveness are ready, and
only then enables the timer.

Existing config values and unknown operator keys are retained verbatim. Missing known
keys are appended, while the installer-owned image/config-directory fields track the
prepared release. Existing passwords are reused. No env file is evaluated as shell.
This means a repeated install does not blank NetBox URLs, replace custom external-DB
DSNs, delete sources, reset secrets or remove history.

The generated `compose.env` and service env files are Docker env files, **not shell
scripts**. Never use `source file` or `. file`; libpq values may contain spaces. Pass
them only with Compose `--env-file`/`env_file` as the tracked wrapper and installer do.

The zero-source state is valid: API/UI liveness does not require a source or live
NetBox, workers can wait for requests, and a scheduled registry-all tick evaluates
zero due sources without provider execution. NetBox URLs and token files are populated
later by the reviewed bootstrap/onboarding procedure; diagnostics may report them
unavailable meanwhile.

## Database lifecycle and roles

The one-shot services provide the supported host-venv-free operations:

```sh
docker compose --env-file /opt/netbox-sync/config/compose.env \
  -f /opt/netbox-sync/current/compose.production.yml --profile tools \
  run --rm --no-deps netbox-sync-db-roles
docker compose --env-file /opt/netbox-sync/config/compose.env \
  -f /opt/netbox-sync/current/compose.production.yml --profile tools \
  run --rm --no-deps netbox-sync-migrate
docker compose --env-file /opt/netbox-sync/config/compose.env \
  -f /opt/netbox-sync/current/compose.production.yml --profile tools \
  run --rm --no-deps netbox-sync-db-grants
```

Role bootstrap is fixed and idempotent. `netbox_sync_owner` owns migrations;
`netbox_sync_web_reader`, `netbox_sync_discovery_reader`,
`netbox_sync_apply_registry_reader`, and `netbox_sync_registry_reader` are readers;
`netbox_sync_registration_writer` can select and insert the exact source-registration
columns; `netbox_sync_run_writer` can select/insert/update only run-history lifecycle
columns; `netbox_sync_schedule_writer` can select/update only the two schedule columns.
Runtime roles receive no DELETE, TRUNCATE, DDL, role administration or writes to
`schema_meta`. PUBLIC schema/table/sequence and owner default table privileges are
revoked before the explicit grants are reapplied.

Migration remains explicit and never runs during API startup. Revision 0001 creates or
strictly validates the registry v1 baseline; 0002 only adds `sync_runs`. There is no
downgrade path. Always back up and rehearse a restored copy before production migration.

## Scheduled execution and locking

The tracked service calls `/opt/netbox-sync/current/scripts/run-scheduled-sync.sh` every
60 seconds. That wrapper invokes the full canonical Compose file, so existing long-lived
containers belong to the same model and do not appear as orphans. It never uses
`--remove-orphans` and never bind-mounts source code.

The wrapper is the **only** scheduled `flock` owner. It locks
`/run/netbox-sync/apply.lock`; the manual apply worker mounts only `/run/netbox-sync` and
opens the same inode. A still-running oneshot cannot be started again by the timer, and
the shared lock remains the final barrier against manual/scheduled overlap.

## Safe upgrade and failure behavior

For an existing canonical install the installer stops the timer, then waits up to two
minutes for `/run/netbox-sync/apply.lock`. It never kills an active apply. Holding that
same lock prevents manual and scheduled writers throughout database preparation and
activation; there is no second deployment lock.

A release-copy, config-merge, image-build, PostgreSQL-readiness, ownership, migration
or grants failure leaves the previous `current` and live config untouched. The timer
remains stopped so an operator can investigate safely. A bounded activation failure
restores the previous symlink and config where possible; any uncertain failure is
reported as failure and never restarts the timer. Database migrations are forward-only
and are **not** automatically rolled back. Back up and rehearse before every upgrade.

The known legacy
`/etc/systemd/system/infra-netbox-sync.timer.d/web8-fixed-tick.conf` is not deleted
automatically. Remove that exact reviewed override during the existing-host transition,
then run `systemctl daemon-reload` before activation. Unknown overrides are never
deleted by the installer.

## Optional external PostgreSQL

Bundled PostgreSQL is intentionally the default. For an operator-managed PostgreSQL,
combine `compose.production.yml` with `compose.external-postgres.yml`; the override puts
the bundled service behind an inactive profile and moves DB-only consumers/tools onto
the egress bridge so they can reach the operator endpoint. Supply service DSNs in the protected
generated env files and set `NETBOX_SYNC_DB_HOST`/`NETBOX_SYNC_DB_PORT` for one-shot tools.
The external server must provide the bootstrap database/user for initial role creation.
Do not expose or reuse NetBox's database.

## Existing-install transition and deferred work

Do not switch an existing deployment automatically. Follow the explicit
[naming transition](naming-migration.md): back up database/config/secrets, migrate a
staged config copy, transition database/schema/roles, build a pinned image, install
the tracked units, and validate shared-lock contention before enabling manual or
scheduled apply. The small `compose.yml` path remains a single-source compatibility
entrypoint, but it also uses canonical product/package/path naming.

Before migrating an existing registry, the migration command verifies that the
database, selected schema and every existing table in that schema are owned by
`netbox_sync_owner`. Missing schema is valid for a clean install. A legacy owner mismatch
fails before Alembic DDL with safe operator guidance; the installer never performs a
hidden ownership takeover. Reassign ownership only through a separately reviewed,
backup-backed transition procedure.

Interactive onboarding, RBAC/LDAPS, TLS/reverse proxy,
resource limits, run-history retention and stale-run recovery are deliberately deferred.
The supported logical backup/fresh-restore workflow is documented in
[Backup and restore](backup-restore.md). Run history remains unlimited and stale
RUNNING rows remain diagnostic-only.

## UI-6 runtime capabilities

The installer generates `broker.env` with `NETBOX_SYNC_LIFECYCLE_WRITER_DSN`, registry
schema and the existing apply-lock path. `discovery.env` adds
`NETBOX_SYNC_OPERATION_WRITER_DSN`. These root-protected configurations accompany the
matching image/migrations/grants; do not mix UI-6 API and historical worker protocols.

| Role | Additional allowed capability |
| --- | --- |
| netbox_sync_operation_writer | SELECT source identity/enabled; SELECT/INSERT/UPDATE operation slots |
| netbox_sync_lifecycle_writer | SELECT sources/operations/runs/tombstones; UPDATE source enabled/sync_enabled; INSERT tombstone identity/name/credential state; UPDATE cleanup state |
| netbox_sync_apply_registry_reader | SELECT operation review context only |
| web/registration/schedule roles | SELECT tombstone evidence needed by existing adapters |

Runtime roles still have no DELETE/TRUNCATE/DDL, identity rewrite, schema ownership or
role administration. Actual PostgreSQL tests assert forbidden table/column writes.
Provider subprocess environments strip the new writer DSNs. API receives neither writer.

Production broker now joins only `netbox-sync-db` (internal), mounts the same apply-lock
directory as manual/scheduled execution and retains root filesystem/secret protections.
It has no provider/NetBox egress network or Docker socket. Development compose.web.yml
uses the existing external DB network and requires its own narrow lifecycle DSN.
Lifecycle is a new fixed broker protocol, not an arbitrary file deletion service.
For an isolated manual-acceptance clone, use the [bridge runbook](historical-ui-test-bridge.md).
