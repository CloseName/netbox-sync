# NetBox Sync architecture

Status: the opt-in Web stack provides health, diagnostics, source visibility,
discovery, confirmed manual synchronization and durable run history. The existing systemd
registry-all scheduler remains the automatic execution authority. See
[Web deployment](web.md) for boundaries and startup commands.

## Current state, verified from code

- `netbox-sync = netbox_sync:main` is the installed entrypoint.
- `source_bootstrap` selects legacy, registry or registry-all configuration.
  Registry-all reads `enabled AND sync_enabled`, ordered by source ID. It rejects
  multiple legacy identity owners. It does not enforce per-source intervals.
- `orchestrator.run_sources` executes sequentially, isolates exceptions and
  SystemExit per source, and reports aggregate success/failure. In apply mode it
  records a separate durable run for every selected source. The CLI exits 1 if
  any selected source fails. There is no durable queue or automatic retry.
- `SourceExecutorDispatch` selects Proxmox or ESXi. Source secrets resolve at
  their connection boundaries; discovery produces shared domain objects.
- `execute_discovered_source` selects the NetBox read/write token at bootstrap.
  Proxmox full apply validates host, VM, VM network, LXC, LXC network and
  disappearance stages before writes. ESXi runtime builds a migration plan,
  filters MANAGED VMs, and prechecks VM plus VM network before either writes.
- ESXi REVIEW_REQUIRED, NEW, safe legacy and ambiguous candidates are not
  auto-adopted. ESXi host matching is reported; host networking is excluded.
  Controlled adoption/bootstrap helpers remain separate explicit operations.
- `SourceRegistry` uses psycopg, parameterized SQL, immutable SourceConfig,
  unique source_instance, reference-only credentials and optimistic updates.
  `initialize()` creates `schema_meta` and `sources`, with schema_version=1.
- `FileSecretResolver` supports env and logical file names beneath
  `/run/secrets/netbox-sync`. LegacyFileSecretResolver supports old absolute
  paths. NetBox credentials still use the existing bootstrap environment/file
  reader. No new secret provider is activated.
- `scripts/run-scheduled-sync.sh` is the tracked registry-all wrapper. It owns the
  sole scheduled flock on `/run/netbox-sync/apply.lock`; the manual apply worker
  contends on the same host inode.
- `compose.production.yml` is the clean-install topology: one application image,
  bundled private PostgreSQL, an internal DB network, ordinary provider/NetBox HTTPS
  egress, dynamic source secrets and no source-tree bind or `netbox_default`.
  Historical Compose files remain compatibility-only.
- Tests use fake NetBox/Proxmox/ESXi, plus opt-in live/isolated PostgreSQL tests.
  `.forgejo/workflows/ci.yaml` runs pytest and pylint >=9.0; these workflows are
  not GitHub Actions. CD still describes upstream-style PyPI publication.

## Lowest-risk layout

```text
netbox_sync/                 existing runtime, domain, adapters: unchanged
  application/                  new, opt-in transport-neutral contracts
docs/                           architecture, migration and development guides
migrations/                     Alembic environment and immutable revisions
deploy/systemd/                 tracked final service and 60-second timer
scripts/                        canonical and compatibility wrappers
tests/                          old suite plus foundation coverage
compose.production.yml          canonical bundled deployment
compose*.yml                    compatibility and optional overrides
alembic.ini                     migration paths, never credentials
requirements-migrations.txt     migration dependencies included in canonical image
```

WEB-1 adds `netbox_sync/api/` (FastAPI) and `frontend/` (React/TypeScript,
Vite). No top-level backend package is needed: API, application and worker code
can share the existing distributable Python package. Do not move stable modules
for cosmetic layering. Migration dependencies are installed in the canonical image
for explicit one-shot operator commands, never API startup. Web dependencies remain
an optional Python extra. Dockerfile.web builds the single canonical artifact plus
frontend assets; process credentials, mounts, users and capabilities remain separate.

## Component contracts

| Layer | Owns | Must not do |
|---|---|---|
| API (future) | request validation, response DTOs, access-control seam | run shell commands, expose raw registry records/secrets, reimplement reconciliation |
| Application | use-case policy, run context, confirmation and safe result contracts | depend on HTTP or mutate process environment per request |
| Worker | durable claim, invoke existing executor, record result | bypass prechecks, grant itself confirmation, run overlapping applies |
| Sync/domain | discovery, identities, planners and guarded appliers | depend on API/frontend |
| Registry/data access | source configuration and concurrency rules | hold plaintext credentials |
| PostgreSQL | registry and additive sync run history | become a second copy of NetBox inventory |
| Frontend | views of safe API DTOs and explicit operator intent | connect directly to PostgreSQL/NetBox/source APIs |
| SecretReader | resolve a SecretReference only at execution | serialize the resolved value |
| Scheduler | submit due work through the same application port | perform reconciliation or run beside an independent competing scheduler |

The new contracts do not hook into the existing CLI. `SecretReader` structurally
matches FileSecretResolver. `PreflightSubmitter` is deliberately read-only intent;
there is no implemented queue and no generic `confirmed=True` web command.

## Current request/run flow

```text
manual API request -> apply worker -> INSERT RUNNING -> existing confirmed guarded runtime
                   -> UPDATE terminal -> safe API result with run_id
systemd registry-all -> per source INSERT RUNNING -> SourceExecutorDispatch
                     -> guarded runtime -> per source UPDATE terminal
history GET -> read-only API role -> explicit DTO -> Runs frontend
diagnostics GET -> source/history readers + socket health -> safe aggregate DTO
systemd tick -> scheduler runtime -> registry + scheduled history -> due sources only
schedule PATCH -> API -> schedule-control socket -> column-limited PostgreSQL role
```

Allocate a UUID once per source execution. A multi-source scheduler iteration has
one run_id per source, not an opaque batch row. A repeated apply is never authorized
merely because its run_id matches. WEB-6 has no delivery retry or crash recovery;
an interrupted RUNNING row remains visible for later operator diagnosis.

Scheduled history persistence is isolated per source. Failure to create RUNNING
skips that source apply, records a bounded history-unavailable result, and continues
the batch. Failure to finalize history preserves the actual source execution result,
reports `FINALIZE_FAILED`, and continues. Neither write is retried and no raw database
exception is included in the runtime summary. The process exits nonzero after the
complete batch when either source execution or history persistence failed.

WEB-7 keeps liveness separate from diagnostics. `/api/v1/health` is constant-time
process liveness. `/api/v1/diagnostics` performs failure-isolated, read-only registry
and history checks plus exact health operations over the existing peer-authenticated
worker sockets. Health never invokes a worker child, resolves credentials, reads
NetBox, or executes discovery/apply. The API receives no new privilege.

Scheduled status is explicitly an activity inference, not systemd state: persisted
scheduled runs are compared with each enabled/sync-enabled source interval using a
minimum 30-minute safety window. The API never calls systemctl, DBus, Docker, or a
host command. Stale RUNNING is a bounded read-only warning after the configured
threshold (default two hours); it is never finalized, deleted, retried, or recovered.

WEB-8 derives scheduling from the latest scheduled `started_at`; manual runs never move
cadence. A source with no scheduled history is due immediately. A missed interval creates
at most one attempt on the next tick, never a backlog. A recent scheduled RUNNING record
prevents overlap; a record older than the shared WEB-7 stale threshold remains untouched
but no longer blocks a new due attempt. The host-level `/run/netbox-sync/apply.lock` remains
the final serialization boundary.

Registry-row conversion and schedule evaluation are isolated per source. An invalid row or
evaluation anomaly becomes the bounded internal `SCHEDULE_EVALUATION_FAILED` outcome, creates no
run-history attempt, and does not prevent healthy sources from being evaluated or executed. The
scheduler summary reports `evaluation_failed` separately from execution and history failures.

The API retains no source UPDATE privilege. Its narrowly mounted schedule socket reaches
a dedicated worker with only a schedule-writer DSN. That worker accepts an exact typed
operation and conditionally updates only `sync_enabled` and `sync_interval_seconds` using
the expected previous values. It has no source secrets, NetBox token, apply capability,
Docker socket, systemd control, or host filesystem mount.

Legacy CLI consumes environment variables and prints text. WEB-1 must introduce
an injectable bootstrap adapter before concurrent request execution; do not set
os.environ per HTTP request and do not parse stdout into an API contract.
Initially use a single execution lane preserving the existing global lock.

## Safety and authorization boundaries

No deletes; stable v2 identities and existing Proxmox legacy ownership; no
name/fuzzy auto-adoption; no automatic VLAN/Prefix creation; no foreign IP/MAC
stealing; preserve manual fields and same-VM manual primary; retain disappearance;
global prechecks before writes; explicit confirmation; idempotency; REVIEW_REQUIRED
report-only; no silent legacy adoption of NEW objects. Preserve the current
difference: truly new Proxmox objects use existing guarded create policy, whereas
ESXi normal runtime reports NEW and uses separate confirmed bootstrap.

Global precheck means all stages within one source run, not an atomic distributed
transaction across sources or across all NetBox HTTP writes. A failure after the
first write can leave partial progress; future run history must report this.

Web apply needs explicit operation/scope and a server-side confirmation tied to
fresh plan, source and target. Authentication is deferred, not authorization or
confirmation checks. Reserve a request-principal dependency and middleware seam
for OIDC/LDAP/reverse-proxy auth. Until authentication exists, any API must bind to
loopback/private trusted access only; write APIs require a separate security review.

## Database ownership

NetBox Sync owns its configured application schema, not NetBox's database. Keep
the current schema and rows in place. Alembic baseline validates legacy v1 before
recording its revision; clean installs create the same tables. No schema rename,
copy, drop or automatic startup migration. `schema_meta.schema_version=1` remains
the legacy registry contract; `alembic_version` tracks application migrations.
Future additive Web tables do not require bumping legacy schema_version.
See [migration procedure](migrations.md) for backup, locks and failure handling.

## Secrets

Preserve all current references and mounts. API DTOs must be explicit allowlists,
not serialization of SourceConfig/SourceRecord/settings. Never include credentials,
DSNs, environment dumps, connection exceptions or raw API payloads. File paths and
usernames may also be sensitive: only disclose intentionally safe status.

Future protected-secret writes require a separate write port: atomic file replace
or encrypted storage, restrictive permissions, reference validation, rotation and
audit. Encryption keys cannot live alongside ciphertext in the registry. No such
write path or secret migration is implemented in WEB-0. The API should not mount
source/NetBox write secrets; the worker receives only those it needs.

## Observability convention

One JSON object per event: timestamp (UTC ISO 8601), level, component,
source_instance, run_id, error_code (nullable), message. The new event builder
uses fixed enums/messages and takes no arbitrary exception or payload. Only a
validated operator source identifier may populate source_instance; it must never
be populated from a credential. No root-logger reconfiguration or changes to
current stdout occur. This is not a universal sanitizer of existing runtime logs.

Stable codes are defined in `application/observability.py`: SOURCE_AUTH_FAILED,
SOURCE_UNREACHABLE, SOURCE_TLS_FAILED, SOURCE_CONFIG_INVALID, SOURCE_SECRET_MISSING,
NETBOX_AUTH_FAILED, NETBOX_UNREACHABLE, NETBOX_TARGET_INVALID, REGISTRY_UNAVAILABLE,
RUN_PRECHECK_FAILED, RUN_APPLY_FAILED, RUN_INTERNAL_FAILED. Keep their meaning
stable; messages can evolve. Map typed failures at adapter boundaries in a later
phase; never guess auth/TLS failure from arbitrary exception text. Unknown failures
use RUN_INTERNAL_FAILED with a generic message. Raw runtime logs are not API-ready.

## Compose and deployment transition

Implemented foundation: one repository, one stable Compose project, one application
image used by API, workers, scheduler and one-shot database tools; PostgreSQL with a
persistent named volume;
frontend build assets served by API initially (separate web container only if
justified). No Redis: PostgreSQL job claims/leases are sufficient until measured
otherwise. DB remains private with no host port by default. External NetBox stays
an integration, not part of our schema or ownership.

The installer starts and health-checks PostgreSQL before role bootstrap, migration,
grants and long-running services. Application filesystems remain read-only and secret
mounts/credentials are role-scoped. Canonical service, file and Compose project naming
uses `netbox-sync`; pre-rename identifiers are accepted only by transition tooling.
Never run a historical scheduler alongside the canonical timer. Cutover requires explicit
operator approval, rollback plan and a tested database backup/restore procedure.

## Deferred and approval gates

WEB-1: minimal FastAPI health/read-only source DTOs and application adapter,
React/TypeScript shell, development Compose roles and integration tests. No
Sync Now/write controls until confirmation and lock/lease behavior are tested.
Then add durable jobs/history, source scheduling, protected secrets and the
remaining Web v1 workflows incrementally. Auth integration comes later.

Before production cutover: test migration on a restored copy, reconcile actual
server Compose/registry configuration, review unauthenticated exposure, and approve
scheduler ownership. Portable zero-source startup is provided by the foundation but
still requires a disposable Debian rehearsal. Python metadata now matches the actual
3.10+ syntax contract, and the fresh requirements include pyVmomi. See
[Deployment](deployment.md) for the supported clean-install path.

## ESXi production and multi-source contract

The standalone adapter has been exercised against VMware ESXi 6.7 build 20497097;
that is the production compatibility baseline, not a claim of support for vCenter or
every ESXi release. One API session is opened per source execution and reused while
the host, VM, device, guest-network, disk, and datastore inventory is mapped. Runtime
connect and pooled HTTP operations have a 15-second I/O timeout. The Web discovery
and apply workers additionally enforce whole-child deadlines. Scheduled sources are
still processed sequentially, so unavailable sources can lengthen a tick; parallel
apply is deliberately deferred in favor of the shared lock and failure isolation.

ESXi v2 identity is independent of display names and inventory placement:

- host: `esxi / source_instance / host / <validated hardware UUID or host MOID>`;
- VM: `esxi / source_instance / vm / <instanceUuid, BIOS UUID, or VM MOID>`;
- VM NIC: `esxi / source_instance / vm-nic / <VM external ID>:<device key>`.

UUID input is stripped and canonicalized to lower-case hyphenated form. Empty,
malformed, and all-zero VM UUIDs fall through deterministically. Host UUIDs also
reject placeholder-like mostly-zero values before using the managed-object ID.
Renaming a host, VM, or NIC label, changing power state or portgroup, and moving a VM
between hosts inside one future same-source inventory therefore do not change its
identity. Two sources may safely report the same name, MOID, or UUID because
`source_instance` is part of the namespace. Changing `source_instance` is creation of
a new ownership namespace, never an ordinary edit or implicit migration.

Malformed VM UUIDs fall back to another stable identifier. A VM or NIC without any
stable identifier/device key is omitted with a bounded, secret-free warning while the
remaining inventory continues; retain-only disappearance policy prevents deletion of
any previous NetBox object. Provider/session/root-inventory failures still fail the
source. Unknown VMware power states map conservatively to stopped/offline, never
active; suspended maps to paused.

NetBox targets come only from that source's immutable `site_slug`, `cluster_name`,
`cluster_type_slug`, `platform_slug`, `device_role_slug`, and `device_type_slug`.
Identity matches outside the target, duplicate identities, ambiguous targets, and
foreign IP/MAC ownership fail closed. Name-only legacy matches—including CONFLUENCE,
OWNCLOUD, MOODLE, KAYAKO, KAYAKOTEST, TESTRAIL, and YOUTRACK-7—remain
`REVIEW_REQUIRED` until a separate explicit adoption operation. ESXi sources always
use `legacy_identity_owner=false`.

Host hardware, physical NICs, disks, datastores, and VM disks are discovered. Normal
ESXi runtime currently manages identity-matched VM fields and VM networking; host
matching is report-only, host networking is unsupported, and datastore detail is not
expanded into a NetBox storage model. NEW VMs are visible as canonical `CREATE`
planning intent but normal runtime does not create them implicitly: the established
confirmed bootstrap helper remains a separate operator action. Missing VLANs and
prefixes are reported and never auto-created. Missing NICs/VMs are retained, never
deleted. These boundaries are intentional and must not be inferred from discovery
completeness.

Each registry row carries its own username and opaque token/password references.
Onboarded sources receive distinct logical file-secret keys, resolved only at the
provider boundary; there is no global credential fallback for registry sources. The
legacy environment loader remains an explicit single-Proxmox compatibility path.

## Proxmox production contract

The production validation baseline is Proxmox VE 9.1.9. The adapter consumes the
cluster status, node status, disk, storage, network, QEMU, QEMU config/guest-agent,
and LXC config endpoints through one proxmoxer client per source execution. The client
is reused for the source rather than recreated per guest. Proxmoxer's HTTPS backend
supplies a five-second request timeout by default, and the Web discovery/apply
supervisors enforce bounded child lifetimes. QEMU guest network lookup remains one API
call per VM. Sources execute sequentially; parallel execution remains deferred.

The registry source is the configured Proxmox API scope and may return multiple nodes;
workloads moving between those nodes retain identity. Host identity uses the provider
node key because the audited API does not supply a more reliable immutable host UUID.
A Proxmox node rename is therefore an identity change requiring explicit migration;
FQDN or cosmetic NetBox display changes never authorize adoption.

Proxmox v2 identities are source-scoped and display-name independent:

- host: `proxmox / source_instance / host / <node key>`;
- QEMU: `proxmox / source_instance / qemu / <positive VMID>`;
- LXC: `proxmox / source_instance / lxc / <positive VMID>`;
- QEMU NIC: `proxmox / source_instance / qemu-nic / <VMID>:<netX key>`;
- LXC NIC: `proxmox / source_instance / lxc-nic / <VMID>:<netX key>`.

VMIDs accept only positive integers or strict decimal strings. Booleans, zero,
negatives, empty/fractional/coercible values, and other text are rejected. Rename,
status, node placement, CPU/memory/disk, MAC, bridge, VLAN, and NIC display-label
changes do not alter identity. Older LXC v2 NIC identity used the guest-visible name
(for example `eth0`). Matching now reads only that exact source-scoped LXC identity
and rewrites it to the provider `netX` key on the next managed update. It cannot match
another source, kind, VMID, or an unmanaged name-only interface.

`legacy_identity_owner=true` is a bounded migration permission for existing Proxmox
v1 records such as `node:VMID` and `node:lxc:VMID`; it is not name adoption, and v2 is
always preferred. Registry-all bootstrap permits at most one runnable legacy owner.
New sources default to false, so a second Proxmox source cannot claim those unscoped
historical identities. Moving ownership requires an explicit migration review because
v1 itself has no source_instance.

Malformed QEMU/LXC VMIDs or config/resource objects and malformed individual `netX`
records are omitted with bounded source-scoped warnings while valid siblings continue.
Retain-only policy means omission never deletes a prior NetBox object. Unavailable or
malformed guest-agent data removes only learned guest IP evidence; it does not remove
the VM or enable the agent. Provider/session, node-root, and target failures still fail
the source. Unknown states map conservatively to stopped; suspended maps to paused.

Existing guarded planners/appliers still enforce exact target Site/Cluster, duplicate
identity, foreign IP/MAC, name-only adoption, and primary-IP checks before writes.
Missing VLANs/Prefixes are not created. Invalid, loopback, link-local, multicast, and
unspecified addresses are rejected by shared network boundaries. Proven same-VM manual
primary IPv4 is preserved; unverifiable/foreign ownership blocks. Disappeared workloads
and NICs are retained, never deleted, and manual fields/custom fields are preserved.

Each registry row has its own immutable source_instance, endpoint, TLS choice, target,
username, and opaque secret references. The resolver accepts logical keys under a fixed
root, and runtime resolves only the selected source. Web onboarding creates distinct
keys, defaults automatic sync off, and cannot edit source_instance. The legacy
environment loader remains an explicit single-source compatibility path.

Deferred limitations: node-rename migration, broader PVE version certification,
cluster-topology redesign, parallel discovery, guest-agent N+1 optimization, and final
live Multi-Source Validation.

## Multi-source system contract

Every managed identity is the tuple `source_type / source_instance / kind / external_id`.
Names, IPs, MACs, cluster labels, and host display names are evidence or managed values,
never sufficient ownership. The registry enforces globally unique source_instance, and
ordinary update paths cannot change id, source_instance, or source_type. A new
source_instance is a new namespace; there is no implicit ownership migration.

| NetBox object | Stable identity | Cross-source behavior |
|---|---|---|
| Proxmox host | source + instance + `host` + node key | foreign identity/name/IP blocks or requires review |
| Proxmox QEMU | source + instance + `qemu` + VMID | same name/VMID remains independent |
| Proxmox LXC | source + instance + `lxc` + VMID | cannot claim QEMU or another source |
| Proxmox NIC | workload identity + `qemu-nic`/`lxc-nic` + `netX` | foreign name/MAC/IP never adopted |
| ESXi host | source + instance + `host` + validated UUID/MOID | same UUID/MOID remains independent |
| ESXi VM | source + instance + `vm` + validated UUID/MOID | same name/UUID remains independent |
| ESXi NIC | VM stable ID + provider device key | labels, MAC, and portgroup are non-identity |
| IP/MAC | assignment ownership plus managed parent identity | an existing foreign assignment blocks before write |

Target resolution is repeated from each immutable SourceConfig. Site, Cluster name/type,
Platform, Device Role, and Device Type are never borrowed from another source. Clusters
with the same display name remain distinct through Site and type scope. An identity found
outside its configured target is a conflict, not a move. Same-name objects in one target
remain unchanged and require review; NetBox Sync never adds source suffixes to display names.

Proxmox management-IP matching is now review evidence rather than ownership. This closes
the last historical path that could have added a second provider identity to an existing
Device. Existing verified v1/v2 identity is required for automatic host updates. IP/MAC
conflicts are evaluated before writes and are never reassigned between sources. Sequential
ordering can determine which of two simultaneously new sources first encounters an
otherwise-free shared network value; the second then fails closed. A cross-source global
transaction or parallel preflight is deliberately not claimed.

Provider selection uses an immutable source-type dispatch table. Failure of one provider,
object conversion, credential lookup, history finalize, or scheduled execution is recorded
for that source and does not stop later eligible sources. A global Registry failure remains
fatal because no source can be selected safely. A malformed registry row is isolated by the
scheduler loader. One source's `REVIEW_REQUIRED` or `BLOCKED` plan prevents writes only for
that single-source execution; it is not a whole-batch authorization token.

Scheduler decisions, manual confirmation, plans, run UUIDs, and diagnostics are keyed by
source_instance. Fixed ticks evaluate each current registry row; manual runs do not affect
cadence. History start failure skips only that source, while finalize failure preserves the
execution outcome and continues. Diagnostics may degrade the aggregate while retaining each
healthy source's independent status, latest success, scheduled state, and warnings.

Web onboarding stores one registry row plus random, collision-resistant logical secret keys.
The broker writes into the single configured source-secret directory, already mounted read
only into discovery/apply/runtime containers. Directory bind mounts expose later files, and
FileSecretResolver performs no value cache, so a newly registered source or credential file
is available without a Compose edit, wrapper edit, per-source mount, or service restart.
Registry/source reads are also per request/tick rather than cached. Web-created sources start
enabled with automatic sync disabled and legacy identity ownership disabled.

The global `/run/netbox-sync/apply.lock` remains the final writer barrier for every provider
and trigger. Manual and scheduled execution do not have provider-specific locks. Sources are
processed sequentially: two sources are operationally inexpensive; five accumulate provider
and guest-agent latency; ten can exceed short source intervals. Run History durations and the
complete tick duration must be reviewed before increasing source count. Parallel apply,
distributed transactions, and catch-up backlogs are intentionally out of scope.

## Backup and restore boundary

Backup Format v1 owns logical PostgreSQL application state plus canonical `config`
and `secrets`. It does not copy the PostgreSQL physical volume, runtime sockets/locks,
containers, images, releases, or checkout. A root-run coordinator stops the timer,
acquires the same apply-lock inode, and pauses control-plane writers before coupling
`pg_dump -Fc` with a GNU tar that preserves numeric ownership, modes, and broker
xattrs. A verified bundle becomes visible through one atomic directory rename.

Fresh restore is the only supported write mode. It rejects populated targets and
unknown/newer Alembic revisions, restores as `netbox_sync_owner`, migrates forward,
reapplies grants, rotates fixed role passwords from restored protected files, and
publishes filesystem state from staging. Runtime health is required, while the timer
remains stopped for explicit read-only validation. See
[Backup and restore](backup-restore.md).

## UI-6 durable operations and source lifecycle

`source_operations` is separate from authoritative `sync_runs`: at most one latest
PLAN and one latest DISCOVERY slot per source, each with a generation UUID, timestamps,
closed status/error and canonical result (8 MiB maximum). A source transaction advisory
gate and composite key deduplicate starts; a per-source/kind session advisory lock owns
execution. The discovery supervisor authenticates Unix peers, forks short request
handlers and detaches provider work from the response socket. Closing a browser does
not cancel accepted work. Other sources and the other operation kind remain independent.
There is no global operation queue or persistent discovery history.

Completion updates only the same RUNNING UUID. A discarded late completion records
`OPERATION_COMPLETION_DISCARDED` with source/UUID only, without replacing the latest
slot or inventing a sync run. A RUNNING slot older than 180 seconds is interrupted on
lookup only if its executor lock is free. Provider work retains its existing 120-second
child timeout. DB connections have bounded connection/statement/lock and TCP liveness
settings. A process still holding an executor lock is conservatively treated as active;
an operator must investigate an unresponsive supervisor, not force a concurrent retry.
Results expire after 24 hours on lookup; plans become STALE. No automatic resumption.

Manual confirmation and Apply bind the current READY generation as well as the existing
digest and single-use token. The source gate prevents generation replacement during
revalidation/write; Apply still uses the original shared filesystem lock and replans
before writing. A failed newer plan cannot reactivate an older plan. Scheduled execution
continues through its existing wrapper/lock and is not disabled by read-only planning.

Removal uses the same apply lock, a source transition gate and a credential-reference
gate. Active PLAN/DISCOVERY or RUNNING/OUTCOME_UNCERTAIN/PARTIALLY_APPLIED run evidence
blocks removal. The transaction disables the source and automatic sync and commits a
tombstone; NetBox objects, the original source row and history remain. Source identity
is reserved. API/scheduler adapters exclude tombstones without redefining run history.
Explicit local credential cleanup follows the commit through the existing root broker.
Only exclusive broker-owned files pass reference, inode, mode and receipt checks;
shared/ambiguous files remain. Cleanup failure cannot undo removal or imply revocation.
There is no provider-side revocation, restore, purge, actor identity or new RBAC model.

## Bootstrap control and literal broker isolation

[First-run architecture](first-run.md) adds a separate NetBox bootstrap worker with
protected atomic file state and bounded read-only validation. It has no DB role or
provider secrets. The API receives only a secret-free projection over its Unix socket.
The UI-6 lifecycle writer now runs in a separate worker: internal DB access, shared
apply lock, broker socket, no source/NetBox file mounts. Broker networking is literally
`network_mode: none`; no PostgreSQL connection or lifecycle DB import remains.
Existing source gates, tombstones, history retention and grants are unchanged.
