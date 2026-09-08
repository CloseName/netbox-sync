# NetBox Sync

Synchronize infrastructure from multiple virtualization sources, including Proxmox VE and VMware ESXi, to NetBox. NetBox Sync is for operators who need deterministic inventory reconciliation, explicit review boundaries, and conservative production automation.

## Features

- Multi-source Proxmox VE and VMware ESXi inventory
- Guarded discovery, canonical planning, and confirmed apply
- Stable, source-scoped identities and idempotent reconciliation
- Retain-only disappearance handling with no delete path
- Web UI for onboarding, diagnostics, plans, run history, and scheduling
- Isolated discovery, apply, schedule, and secret-broker processes
- Per-source cadence backed by PostgreSQL run history
- Versioned backup, verification, and fresh-restore workflow
- Source-scoped credential references with root-protected secret storage

## Supported sources

- Proxmox VE: hosts, QEMU VMs, LXC containers, disks, interfaces, MACs, and IPs
- VMware ESXi: standalone hosts, virtual machines, interfaces, MACs, and IPs

Additional providers can be added behind the same source, discovery, plan, and apply boundaries.

## How it works

```text
Source -> Discovery -> Canonical Plan -> Guarded Apply -> NetBox
```

Discovery reads provider inventory. Planning compares it with NetBox without writing. Apply revalidates the plan and performs only confirmed, allowlisted changes.

## Safety model

- No object deletion
- Retain-only disappearance policy
- No fuzzy-name or name-only automatic adoption
- No stealing foreign IP or MAC assignments
- No automatic VLAN or prefix creation
- Fail-closed ownership and conflict checks before the first write
- Idempotent second apply
- Source-scoped identities and disappearance isolation
- One shared host lock for scheduled and manual apply

## Architecture

The Web/API process has no provider secrets or apply authority. Dedicated Unix-socket workers handle discovery, confirmed apply, and schedule changes. A root secret broker supports create-only credential onboarding without exposing a read API. PostgreSQL stores sources and run history. A fixed systemd tick invokes the sequential scheduler, while per-source cadence is evaluated from persisted scheduled runs.

See [Architecture](docs/architecture.md) for the complete process and privilege model.

## Quick start

The supported production path is the canonical Deployment Foundation on Debian with Docker Compose and PostgreSQL 16.

```sh
python3 deploy/install.py --check
# Review generated configuration and the deployment runbook first.
sudo python3 deploy/install.py --release-id <release-id>
```

This prepares `/opt/netbox-sync`, protected configuration and secret directories, the `netbox-sync` Compose project, and tracked `netbox-sync.service` / `netbox-sync.timer` units. It does not request provider credentials or perform an automatic migration of a legacy installation.

## Deployment

Follow [Deployment](docs/deployment.md). Existing installations must use the explicit [Naming migration](docs/naming-migration.md) procedure; canonical runtime code reads only `NETBOX_SYNC_*` product-global variables.

## Configuration

Sources are registered independently with a stable `source_instance`, provider settings, NetBox target, and logical `SecretReference(provider="file", key="...")` values. Logical source secret filenames and registry references are deliberately not renamed during product migration. Web onboarding creates new source secrets through the broker and registers new sources disabled for sync by default.

Provider-specific `PVE_*` variables and existing NetBox-specific `NB_*` variables remain provider/boundary contracts rather than product-global names.

The historical single-Proxmox environment workflow is documented separately in [Legacy Proxmox mode](docs/legacy-proxmox-mode.md).

## Backup and restore

Use the supported workflow in [Backup and restore](docs/backup-restore.md). Backup bundles contain credentials and must be encrypted before off-host storage. Current tooling reads valid pre-rename v1 bundles and migrates legacy environment, schema, roles, and xattr metadata through explicit compatibility boundaries.

## Development

```sh
python -m pip install -e .
python -m pip install -r requirements-dev.txt
python -m pytest
pylint netbox_sync tests

cd frontend
npm ci
npm test
npm run typecheck
npm run build
```

PostgreSQL integration suites require explicitly configured disposable test databases; they never default to production.

## Documentation

- [Architecture](docs/architecture.md)
- [Deployment](docs/deployment.md)
- [Database migrations](docs/migrations.md)
- [Backup and restore](docs/backup-restore.md)
- [Web/API and provider runbooks](docs/web.md)
- [Naming migration](docs/naming-migration.md)
- [Development](docs/development.md)

## Roadmap

The v1 scope is safe Proxmox VE and VMware ESXi inventory reconciliation, source onboarding, diagnostics, scheduling, run history, and recoverable deployment operations. Future integrations should reuse the same identity, privilege-separation, planning, and confirmation contracts.

## License

Licensed under the GNU General Public License v3.0. See [LICENSE.txt](LICENSE.txt).
See [Project provenance](docs/provenance.md) for derivation and history details.

Clean zero-source installation and browser-based NetBox setup: [First-run Bootstrap](docs/first-run.md).

## Production HTTPS installation

Use the [DNS/TLS clean-install runbook](docs/clean-install-tls-runbook.md) and
[TLS/CA security boundary](docs/tls.md). The canonical installer requires an explicit
public HTTPS FQDN. Standalone nginx uses an operator-supplied certificate/key;
[external/shared ingress mode](docs/external-ingress.md) instead exposes a protected
host Unix upstream and leaves public TLS to the operator-managed ingress. API uses
a separate private Unix socket in both modes. NetBox remains external, with optional explicit
corporate CA trust. No ACME, NetBox deployment or operator authentication is bundled.
