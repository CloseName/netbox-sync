# Host-backup dependency fix verification

Base: `8de318cddd9b6fd916c24738906226e3a0098f9c`, clean `main` at entry.
No live VM access, push or deployment was performed. All runtime resources below
were disposable local Docker test resources with unique names.

## Reproduction and accepted recovery boundary

The rehearsal builds the actual production image from a Git archive of
`6639c38b7b9fcf535624e06ecf91fa0ac7db3d6b` and provisions its unchanged production
Compose plus external-ingress override. A separate Debian 12 operator-host harness
contains Python 3.11.2, systemd, GNU tar/OpenSSL, Docker CLI and Compose 2.40.3;
it contains no psycopg, provider SDK or pytest installation. The host Docker Linux
Engine is 29.7.2; host Compose model checks use 5.5.0. PostgreSQL image is 16-bookworm
(server 16.15). No Sync backend or DB ports are published.

The original old-release CLI fails with `ModuleNotFoundError: psycopg`. The repaired
CLI then runs `preflight`, `create`, `verify`, `inspect` against that same `current`.
Assertions cover real source/history rows, protected onboarding JSON, all config
and credential bytes/modes/owners, broker xattrs, release/deployment metadata,
unchanged `current`, same PostgreSQL container and physical volume, and restored
previously running services and actual systemd timer. A stopped DB gives an early
preflight failure without stopping timer/API. An initially inactive timer and
stopped discovery worker remain inactive after a subsequent successful backup.

The timer is real, using the tracked unit with a test-only delayed firing interval
so scheduled work cannot race the fixture assertions. systemd needs a privileged
**operator-host test harness** with a private cgroup namespace; only that harness
gets the Docker socket. App services keep the unchanged production Compose mounts,
capabilities and network boundaries, including the networkless broker. This is not
an application deployment topology or a recommendation to privilege app containers.
The fixture root is selected under a unique Linux volume mountpoint so host-side
Compose bind paths resolve identically through Docker Desktop.

A second clean Debian test prepares only the documented optional libpq venv from
`requirements-backup.txt`, exercises DSN parsing and idempotent pre-UI-6 restore
adaptation without application imports, and proves the system interpreter remains
without psycopg. Full restore database semantics retain the existing PostgreSQL
round-trip regression and TLS/metadata unit coverage. A full end-to-end fresh
restore on the live VM was not performed.

## Checks

- Clean Debian actual CLI/systemd rehearsal and optional venv: **2 passed**.
- Related Linux backup/restore, TLS, installer, ingress regressions: **135 passed**.
  Three Docker-CLI-only Compose checks skipped in that dependency-rich unit runner
  were separately run using the host CLI: **3 passed**, both ingress models valid.
- Isolated PostgreSQL custom dump/restore regression: **1 passed**, including
  multi-source/history/tombstones and operation reconciliation. The first local
  harness attempt omitted the test's required fixture password; the corrected
  harness with a nonempty protected test credential and TCP readiness passed.
- `git diff --check`: passed.

Reproduce the clean-host checks (local disposable Docker resources only):

```sh
docker build -f tests/Dockerfile.backup-host -t netbox-sync-backup-host:review .
NETBOX_SYNC_CLEAN_BACKUP_TEST=1 python -m pytest tests/test_backup_clean_debian.py -q
```

The test runner itself may have pytest; neither that interpreter nor its dependencies
are used to execute the host backup CLI. See [the operator recovery runbook](backup-restore.md#backup-release-6639c38-before-upgrading-it)
for the pre-upgrade commands. A reviewed repair commit must be published or securely
transferred first; this work does not authorize either deployment or automatic upgrade.
