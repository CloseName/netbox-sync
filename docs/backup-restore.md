> Set `ROOT` explicitly for operator commands; see [deployment paths](deployment-paths.md).

# NetBox Sync backup and fresh restore

Status: Backup Format v1 is the supported operator workflow for the canonical
Debian Deployment Foundation. Bundled PostgreSQL 16 is the primary tested mode;
external PostgreSQL is an advanced mode that requires compatible PostgreSQL client
tools and an operator-provided maintenance DSN.

Backups contain credentials and are highly sensitive. Keep the local directory
root-only, encrypt a copy with an approved external tool such as `age`, GPG, or the
corporate backup system, and move that encrypted copy off the NetBox Sync VM. NetBox
Sync does not invent an encryption format and does not delete or retain old backups
automatically.

## Host dependencies and preflight

Bundled PostgreSQL `create`, `verify`, `inspect`, `list`, and current-format restore
run with Debian Python 3.10+ standard library only. Do not install the application,
provider SDKs, Alembic or SQLAlchemy on the host. The installer checks GNU tar and
OpenSSL as well as Docker/Compose and util-linux. PostgreSQL `psql`, `pg_dump` and
`pg_restore` run in the **installed** bundled `postgres` container, with no published
DB port. GNU tar preserves owners/modes/xattrs; Python `fcntl` uses the existing
shared apply lock. Docker CLI/Compose and a reachable Linux daemon are required;
systemctl coordinates the real installed timer for maintenance. OpenSSL and Python
ssl validate TLS on restore. Application migration/role tooling runs only in the
existing dedicated tool containers. No Docker socket is added to app containers.

`preflight` is read-only and uses the selected root's current Compose configuration.
It checks tools, Compose/daemon, DB clients/connectivity/metadata, and the loaded
systemd timer before maintenance. `create` and `restore` repeat their checks before
stopping anything. A known prerequisite failure prints `BACKUP_PREFLIGHT_FAILED`
with a fixed actionable diagnostic; database exceptions, DSNs and secrets remain
redacted. This is a point-in-time check, not a promise against later runtime failure.

Only external-PostgreSQL DSN parsing and adaptation of pre-UI-6 restore bundles
(missing `config/broker.env`) need psycopg/libpq. Keep its real DSN parser; do not
replace it with shell parsing. For either advanced path prepare an isolated venv:

```sh
# Debian operator preparation; no global pip and no --break-system-packages.
sudo apt-get install python3-venv
: "${TOOLS:?Set the full reviewed code directory, normally ROOT/current}"
VENV="$ROOT/state/backup-libpq-v1"
sudo python3 -m venv "$VENV"
sudo "$VENV/bin/python" -m pip install -r "$TOOLS/requirements-backup.txt"
# Use "$VENV/bin/python" instead of python3 for the backup commands below.
```

Here `TOOLS` is the reviewed code directory (normally `$ROOT/current`, or the
pre-upgrade tool directory below). This environment is operator-owned, excluded
from backup, and is not mounted into any service. Preparation failure is a stop
condition. Older bundles remain supported; missing optional dependencies fail
before their restore maintenance window. External PostgreSQL additionally needs
compatible host `psql`, `pg_dump`, `pg_restore` and the protected maintenance DSN.

## Backup release 6639c38 before upgrading it

The original host script in `6639c38` imports psycopg unconditionally, then imports
`netbox_sync.deployment` for two constants. Python executes `netbox_sync/__init__.py`
first, transitively loading pynetbox, proxmoxer, pyvmomi, requests/urllib3 and
psycopg, then deployment's Alembic/SQLAlchemy.
Installing only psycopg would therefore not fix the complete host dependency chain.
The repaired tool obtains the password contract from the stdlib installer and loads
libpq only for the two advanced cases above.

Use the **reviewed repaired tool** against the **old active installation**. Do not
run `install.py`, including `--prepare-only`: preparation builds/provisions the DB
and can stop the timer. Do not modify `current`, generate config, rotate credentials,
change container names or replace a volume to make this backup. The tool selects
Compose files through the old `current`, so maintenance resumes the old services.
It records the active old release ID, not the repair tool's commit. On an unpackaged
host `application_version` may be `unpackaged`; the exact active release is authoritative.

After this fix has been reviewed and published (or its full trusted Git commit has
been securely delivered to the existing checkout), run in **bash** as an operator:

```bash
set -euo pipefail
ROOT=/netbox-sync-test
: "${FIX_COMMIT:?Set the reviewed full host-backup-fix commit}"
[[ "$FIX_COMMIT" =~ ^[0-9a-f]{40}$ ]]
test "$(git -C "$ROOT/repo" rev-parse "$FIX_COMMIT^{commit}")" = "$FIX_COMMIT"
test "$(sudo readlink -f "$ROOT/current")" = "$ROOT/releases/6639c38b7b9fcf535624e06ecf91fa0ac7db3d6b"
TOOLS="$ROOT/state/backup-tools-$FIX_COMMIT"
sudo test ! -e "$TOOLS"
sudo install -d -o root -g root -m 0755 "$TOOLS"
git -C "$ROOT/repo" archive "$FIX_COMMIT" | sudo tar --no-same-owner -xf - -C "$TOOLS"
sudo python3 "$TOOLS/deploy/backup.py" --root "$ROOT" preflight
sudo python3 "$TOOLS/deploy/compose.py" --root "$ROOT" ps --status running --services
systemctl is-active netbox-sync.timer || test "$?" -eq 3
sudo python3 "$TOOLS/deploy/backup.py" --root "$ROOT" create
# Set exactly the complete bundle path printed by create; never pick an old bundle by guess.
: "${BUNDLE:?Set the newly created full backup directory path}"
sudo python3 "$TOOLS/deploy/backup.py" --root "$ROOT" verify "$BUNDLE"
sudo python3 "$TOOLS/deploy/backup.py" --root "$ROOT" inspect "$BUNDLE"
sudo readlink -f "$ROOT/current"
sudo python3 "$TOOLS/deploy/compose.py" --root "$ROOT" ps --status running --services
systemctl is-active netbox-sync.timer || test "$?" -eq 3
```

Stop on any failure; do not proceed to upgrade. If `TOOLS` already exists, verify
its provenance rather than overwriting it. Compare the before/after service list,
timer state and `current`; inspect must report release `6639c38...` and revision
`0005_source_tombstones`. Keep the complete protected bundle and its encrypted
off-host copy. No env file or private key needs to be printed. The checkout must
contain the entire reviewed commit; copying only `backup.py` into the old release
is unsupported. This recovery path is specifically exercised against `6639c38`;
it is not an unreviewed promise for arbitrary future/older installations.

## Persistent-state inventory

The required state is:

- a logical custom-format dump of database `netbox_sync`, including schema
  `netbox_sync`, `schema_meta`, `sources`, `sync_runs`, `alembic_version`, indexes,
  constraints and every application schema object;
- `${ROOT}/config`: the canonical env files, preserved byte-for-byte,
  including unknown operator keys;
- `${ROOT}/secrets/infrastructure`: the bootstrap and fixed runtime-role
  password files;
- `${ROOT}/secrets/sources`: exact logical filenames and broker xattrs;
- `${ROOT}/secrets/netbox`: onboarding `bootstrap.json`, control state and separate read/apply token files
  when configured;
- a manifest identifying the active immutable release and deployment/database
  metadata.

The release itself is optional and is not bundled. Retain the immutable source/image
identified by the manifest. The bundle excludes `current`, `releases`, `state`, the
PostgreSQL physical volume, Unix sockets, the shared lock, PID/container metadata,
logs, checkout files, caches, `node_modules`, and image layers. No runtime item under
`/run` is required after reboot or restore.

NetBox remains an external system of record and is not copied by this workflow. Its
managed v1/v2 custom-field identities remain in NetBox; restoring the exact
`source_instance`, source type, target settings, credential references, and secret
filenames preserves the corresponding NetBox Sync identity namespace without source
re-registration.

## Bundle Format v1

The default destination is `${ROOT}/backups` (0700). A complete directory is
published atomically only after verification:

```text
netbox-sync-backup-YYYYMMDD-HHMMSS/
  COMPLETE
  manifest.json
  checksums.sha256
  database.dump
  state.tar
```

Payload files are 0600. `database.dump` is produced by `pg_dump -Fc --no-owner
--no-acl`; it never contains cluster-level roles. `state.tar` is a GNU pax tar made
with numeric owners and the `user.netbox_sync.*` xattr namespace. Broker-created
source secrets require `user.netbox_sync.operation`, `user.netbox_sync.receipt`, and
`user.netbox_sync.complete`.

The manifest contains format/application/release versions, UTC time, Compose project,
PostgreSQL major, database/schema, Alembic revision, source/run/secret counts, exact
file metadata, config file names, and logical credential references. Broker xattr
values are fingerprinted because the rollback receipt is an authorization value; the
real values exist only in the protected tar. Passwords, tokens, DSNs, raw payloads,
and secret contents never enter the manifest or operator log.

Every payload plus the manifest has a SHA-256 entry. `COMPLETE` is written only after
the dump is listable with `pg_restore`, the tar is structurally safe, source file
references resolve, and all checksums pass. A failure removes only its hidden staging
directory and never touches a previous backup.

## Create, inspect, and verify

For a release containing the host-backup fix, run from the active release as root
(use the recovery section above before updating an older installation):

```sh
cd ${ROOT}/current
sudo python3 deploy/backup.py --root "$ROOT" preflight
sudo python3 deploy/backup.py --root "$ROOT" create
sudo python3 deploy/backup.py --root "$ROOT" create --output /protected/backup-target
sudo python3 deploy/backup.py --root "$ROOT" verify ${ROOT}/backups/netbox-sync-backup-TIMESTAMP
sudo python3 deploy/backup.py --root "$ROOT" inspect ${ROOT}/backups/netbox-sync-backup-TIMESTAMP
sudo python3 deploy/backup.py --root "$ROOT" list
```

`inspect` and `list` expose only timestamp, application/release, source/run counts,
PostgreSQL major, Alembic revision, total size, and checksum status. There is no delete
command.

Exit status is `0` only on success. Failures use a stable safe class such as
`BACKUP_FAILED`, `BACKUP_LOCKED`, `BACKUP_INVALID`, `RESTORE_LOCKED`,
`RESTORE_INVALID`, `RESTORE_TARGET_NOT_EMPTY`, or `RESTORE_INCOMPATIBLE`; raw database
or secret-bearing exceptions are not printed.

Create records whether the timer was active, stops it, waits boundedly for
`/run/netbox-sync/apply.lock`, and never kills an active apply. Once it owns that same
inode, it stops API, broker, discovery, apply, and schedule-control services.
PostgreSQL remains online. This short maintenance window prevents onboarding,
schedule, run-history, secret, scheduled, and manual-apply writes while the database
and filesystem snapshots are taken. It restarts exactly the previously running
services and restores the prior timer state on success or backup failure. A restart
failure makes the command fail even if a completed bundle remains useful.

For external PostgreSQL, install compatible client tools and provide the protected
value without putting it in argv or source control:

```sh
sudo --preserve-env=NETBOX_SYNC_BACKUP_DSN \
  "$VENV/bin/python" "$TOOLS/deploy/backup.py" --root "$ROOT" --postgres-mode external create
```

The maintenance DSN must dump all NetBox Sync objects. Restore also requires permission
to replace them and `SET ROLE netbox_sync_owner`; do not reuse a runtime reader. The
value is inherited only by the operator process/client tools and is never printed.

## Supported fresh restore

The supported target is a clean Debian host with the Foundation installed, its
intended immutable release active, PostgreSQL reachable, fixed roles bootstrapped,
and no source/history/operation/tombstone rows. First perform a no-write check:

```sh
cd ${ROOT}/current
sudo python3 deploy/backup.py --root "$ROOT" restore /protected/netbox-sync-backup-TIMESTAMP --check
sudo python3 deploy/backup.py --root "$ROOT" restore /protected/netbox-sync-backup-TIMESTAMP
```

Restore verifies format, checksums, archive paths/types, xattr contract, dump
readability, PostgreSQL direction, Alembic compatibility, canonical layout, and empty
`sources`/`sync_runs`/`source_operations`/`source_tombstones` before the first write. The empty check is repeated inside the
maintenance lock after all writer services stop; two datasets are never merged.

The write sequence is:

1. stop the timer, acquire the shared lock, and stop writer/control services;
2. extract config/secrets into root-only staging and validate exact paths, uid/gid,
   mode, and xattr fingerprints;
3. after proving the target is the exact empty Foundation schema, drop only the
   allowlisted Foundation tables and schema without `CASCADE`, restore with
   `pg_restore --no-owner --no-acl --role=netbox_sync_owner`, and rename a verified
   legacy `infra_sync` schema to `netbox_sync` when restoring a pre-rename bundle;
4. run the tracked Alembic tool forward to target head and reapply tracked grants;
5. create a transient root-only password view containing the target bootstrap password
   and restored runtime passwords; the tracked `restore-role-passwords` operation
   rotates runtime roles first and bootstrap last;
6. preserve the clean target's allowlisted host-local Compose project, image, bind
   port, volume, lock, and canonical path values; then atomically replace `config`
   and `secrets`, preserving portable operator keys, logical source refs,
   infrastructure passwords, NetBox token separation, owners, modes, and xattrs;
7. compare source/run counts, credential references, and Alembic head;
8. start ordinary API/control workers and require API health plus Diagnostics.

The scheduler timer remains stopped. Run Diagnostics, Run Discovery, and Build Plan
for each source. Confirm identity resolution and expected `NO_CHANGE` or
`REVIEW_REQUIRED`, then explicitly enable the timer. Restore never invokes apply.

Filesystem publication uses staging and per-directory atomic renames. Database plus
filesystem restore cannot be one transaction. If a restore stage fails, timer and
writers remain stopped, success is not reported, and the fresh target is considered
dirty: diagnose or recreate it before retrying. There is no automatic DB rollback.

## Compatibility and limitations

- Backup Format v1 is accepted by this v1 tool. Unknown future formats are rejected.
- Valid pre-rename Format v1 bundles retain their original manifest identity,
  `infra_sync` schema and `user.infra_sync.*` receipts. Restore translates reviewed
  product-global environment keys, preserves unknown/operator keys and logical source
  filenames, renames the restored schema without data rewrite, and accepts either
  complete xattr namespace. New bundles and broker writes use only NetBox Sync names.
- The backup Alembic revision must be in the target tool's reviewed chain. The same
  revision restores directly; an older known revision migrates forward. A newer or
  unknown revision is rejected before writes. Downgrade is never attempted.
- Logical restore from PostgreSQL 16 to 16 or a newer server major is allowed for
  rehearsal; an older target is rejected. Client/server tools must be compatible.
  Physical volume copying is unsupported.
- Fresh restore is supported. Replacing a populated/unknown installation is not.
  There is intentionally no `--replace-existing`; use a fresh VM or a separately
  reviewed disaster runbook and pre-restore backup.
- Fresh restore reproduces portable operator config and unknown keys. It deliberately
  retains the clean target Foundation's Compose project, application image, web port,
  PostgreSQL volume, apply-lock directory, and canonical config/secret paths. Review
  external-DB or future host-local values while the timer is stopped. Backup and
  application upgrade remain separate operations.
- xattrs are mandatory for broker-created source secrets. A filesystem without
  working `user.*` xattrs is unsupported and fails closed.

## Recovery rehearsal checklist

Backup:

1. confirm health and protected free space;
2. create the bundle;
3. run `verify` and `inspect`;
4. encrypt and copy it off-host; retain the immutable release from the manifest.

Restore:

1. build a clean Foundation at the same or reviewed newer release;
2. run `restore ... --check`, then `restore`;
3. confirm Health, Diagnostics, Sources, and Run History;
4. run read-only Discovery and Build Plan for Proxmox and ESXi;
5. verify permissions/xattrs and expected identity/no-change behavior;
6. enable the timer explicitly and observe one scheduled tick;
7. reboot and repeat health/history/source checks.

For upgrades, the future handoff is: verified backup, prepare immutable new release,
forward migration, then activation. The installer does not silently combine backup,
restore, and upgrade.

## UI-6 state and recovery

The reviewed chain now ends at `0005_source_tombstones`; the Foundation inventory has
six tables, adding source_operations and source_tombstones. Dumps preserve tombstones,
source identity and durable operation state. Manifest credential references cover active
sources only: a removed source may retain its original DB references even when its
exclusive local files were explicitly removed. Remaining secret files still retain the
existing tar/mode/owner/xattr verification contract.

Fresh restore rejects any source, run, operation or tombstone rows, including orphan
lifecycle evidence. The exact empty-schema cleanup also removes the known invoker trigger
function without CASCADE. After migration/grants, restored RUNNING operations become
FAILED/OPERATION_INTERRUPTED and READY plans become STALE; results are cleared. Work is
not resumed and old confirmation context cannot become applicable. Existing uncertain
sync-run history remains unchanged and continues to block removal conservatively.

Reviewed pre-UI-6 bundles are extended only in validated staging with new operation and
lifecycle role passwords/DSNs and broker.env. Current bundles preserve their configuration.
No runtime receives migration-owner credentials. External client tools are executed by
the same resolved absolute binary path whose version was checked, avoiding PATH mismatch.
Bundled Docker transport and PostgreSQL logical restore tests are separate evidence.

## Bootstrap state and new control services

Backup quiescence now includes lifecycle and Bootstrap workers. The existing protected
`secrets/netbox` inventory contains bootstrap.json and its lock file; state and separate
tokens remain one verified atomic document. Restore retains READY setup truth, not a
claim of present NetBox reachability. Expired VALIDATING state is reconciled to ATTENTION
on status lookup. Revalidate the destination before using a restored deployment.
Older bundles gain missing Bootstrap/runtime socket settings only after validated
staging; absent bootstrap.json means FRESH, never inferred readiness from old env files.
The filename broker.env remains for compatibility but only the lifecycle worker reads it.
See [first-run recovery and clean-VM checklist](first-run.md).

## TLS material in Backup Format v1

[TLS hardening](tls.md) supports legacy in-root `secrets/tls` and `secrets/ca` entries.
TLS directory/files preserve root:10001 0750/0640; CA directory/file preserve
root:root 0755/0644. These are bounded exceptions to root-only source/infrastructure
secret rules, not a general relaxation. Only fullchain.pem, privkey.pem and optional
netbox-ca.pem are accepted there. Legacy in-root backups contain the TLS private key. New corporate `/etc` TLS
material is outside the application backup and must be protected separately. Restore
validates the prepared target TLS selection without writing to the operator directory.

Prepare a fresh HTTPS target using the [runbook](clean-install-tls-runbook.md) before
restore. Public URLs must match; a different hostname fails before DB restore. Old
pre-TLS bundles (no public URL, TLS settings or TLS directory) retain the prepared
target's supplied material. Merely missing files in a TLS-enabled legacy bundle
does not identify it as a pre-TLS backup. Host paths are
rewritten for the target, files are validated before DB restore, and API post-restore
diagnostics use the Unix socket. No TLS private material is put in env files.

External/shared ingress restore preserves the prepared target's mode and local
socket directory. It requires no duplicate public server certificate. The mode-aware
Compose selector is used for maintenance/startup; socket files are not backed up.
See [the ingress contract](external-ingress.md).

New backups record deployment identity. Restore requires explicit `--root`, including
`--check`; recorded paths never select the destination. See [path contracts](deployment-paths.md).

For a standalone legacy target, an external-ingress or explicit corporate-layout
source intentionally omits public TLS from the bundle. When both archived legacy
filenames are absent, restore validates and copies the prepared target pair into
staging. It never reads the source-host TLS directory or uses manifest paths as
write destinations. Unknown/ambiguous layouts and invalid corporate directory
metadata fail closed. A partial pair is never repaired through this fallback;
a legacy standalone source must contain its complete expected pair.

Corporate targets retain their operator-owned material; restore validates it in
place without changing contents, modes or modification times. Target layout wins.
Public URL equality, hostname, expiry, key match and protection checks still apply.
Old v1 manifests without deployment identity remain supported: this decision uses
the verified archived configuration, not the optional identity metadata.
