> Current production deployment uses [nginx HTTPS and a private API Unix socket](tls.md).
> Follow the [clean-install runbook](clean-install-tls-runbook.md). Loopback ports and
> older deployment limitations below describe historical WEB stages or development,
> not the canonical production Compose path. UI-6 and Bootstrap are implemented.

# WEB-3: protected source onboarding, health and source visibility

> Deployment note: `compose.production.yml` and [Deployment](deployment.md) are the
> canonical clean-install path. Historical `compose.yml`/`compose.web.yml` commands in
> phase-specific sections remain compatibility and audit records.

## WEB-3 security boundary

WEB-3 adds only Test Connection and explicit registration of a new source. It
does not enable sync, update/delete existing sources, adopt inventory, run
discovery or change the systemd scheduler. Existing WEB-1/2 read paths remain.
The sections below describing read-only WEB-1/2 behavior apply to those endpoints;
onboarding writes have the separate privileges and restrictions in this section.

### Flow and request contracts

1. Choose Proxmox or ESXi; enter a bare hostname/IPv4 address and verify_ssl.
2. Enter Proxmox user@realm, token name (without user prefix), token secret;
   or ESXi username/password. No URL, port or path is accepted for WEB-3 inputs:
   this preserves the existing bare-host runtime connection contract. Existing
   registered sources and WEB-2 address display are not modified.
3. POST /api/v1/sources/test-connection authenticates and reads only Proxmox
   version or ESXi service content. ESXi uses an ephemeral authenticated SOAP
   session (HTTP POST for login/read/logout), not inventory mutation. Connect/read
   timeouts are five seconds; an isolated non-root child is killed and reaped after
   a 15-second whole-operation deadline, including DNS and the initial version GET.
   No registry/broker write occurs. No NetBox call occurs.
4. A successful test returns an unpredictable onboarding_token, valid for ten
   minutes and one registration attempt. Credentials remain in bounded
   process-local memory only (maximum 128 pending items); expiry timers discard
   them. The form clears credentials when the test settles. All connection fields
   are disabled in flight. Change connection calls POST /api/v1/sources/cancel-onboarding
   with the opaque token, revokes its server-side credential handoff, clears the browser
   token, and requires a new test. Cancellation uses the same Host/Origin/CSRF boundary,
   is idempotent, and does not call the registry or broker. No browser storage is used.
5. Review source_instance, name, site_slug, cluster_name, platform_slug,
   device_role_slug, device_type_slug, cluster_type_slug, verify_ssl and
   sync_interval_seconds. Confirm automatic synchronization stays disabled.
6. POST /api/v1/sources includes this metadata, source_type/address bound to the
   tested connection, onboarding_token, and confirm_sync_disabled=true. Backend
   revalidates it. Success is HTTP 201 with only the existing safe SourceDTO.

Defaults are enforced server-side: enabled=true, sync_enabled=false,
legacy_identity_owner=false, settings={}. Callers cannot override them.
Duplicate source_instance is HTTP 409 SOURCE_ALREADY_EXISTS, never an upsert.
Token replay/expiry is ONBOARDING_TOKEN_INVALID/409. Failed registrations consume
the token; retest only after reviewing any uncertain outcome. A successful test
is historical evidence, not continuing source health or permission to sync.

Credentials with leading/trailing whitespace are rejected because the existing
file resolver strips whitespace. Proxmox uses two file references; ESXi uses the
same password file reference for token_id and token_secret as SourceCredentials
already supports. Username remains in the existing registry username column,
which the existing runtime requires; password/token material remains only in
protected files. Username and references are never in public DTOs. Credential
container repr() is suppressed, without changing runtime fields or resolution.

### Root broker, socket and mounts

The opt-in netbox-sync-secret-broker service runs UID/GID 0:0, supplementary GID
10001, with cap_drop ALL, no-new-privileges, read-only root filesystem and
an internal DB network in production. Its mounts include the dedicated source-secret
directory, shared Unix-socket volume and shared apply-lock directory. It has no TCP listener and no Docker socket.

The Web/API remains UID 10001, cap_drop ALL, no-new-privileges and read-only. It
receives only the socket volume read-only, not the source-secret directory.
The socket is root:10001 mode 0660, in a root-owned directory not writable by
group/others. Linux SO_PEERCRED must identify UID 10001 before a request is read.
The broker uses the supplementary group to set socket ownership without adding
CAP_CHOWN. Container smoke tests exercise this exact restriction.

Original credential operations are create and rollback; UI-6 adds fixed source lifecycle requests. There is no read/list endpoint. Clients
send a logical key, never a filesystem path. Keys must match
`^[A-Za-z0-9][A-Za-z0-9_-]{15,127}$`: no dots, slashes, backslashes or percent
encoding. Onboarding generates src-<normalized-instance>-<kind>-<random-hex> keys.
References remain SecretReference(provider='file', key=<flat-logical-name>).

The configured secret root must be an absolute root:root 0700 directory. Every
directory component is opened with O_DIRECTORY/O_NOFOLLOW. File creation uses
dir_fd, O_CREAT|O_EXCL|O_NOFOLLOW, mode 0600, root:root, bounded 4096-byte values,
complete writes, fsync(file), and fsync(directory) before success. Existing files
are never overwritten. No plaintext broker payloads are logged.

Rollback requires the exact operation ID, logical key and random receipt from
creation. These are stored as root-protected user.netbox_sync.* extended file
attributes, together with a completion marker, fsynced before acknowledging.
Rollback checks the receipt, operation, owner, mode, regular-file/link status and
open-descriptor/path inode consistency immediately before unlink. Failed-create
cleanup checks the created inode and all successfully written attempt xattrs too.
The filesystem must support user extended attributes; unsupported
storage fails closed. Secret contents and runtime reference formats are unchanged.
A same-operation create retry can recover its durable receipt without overwriting
content. The client retries once with the same operation/key after transport
failure; broker restart does not erase completed-file ownership evidence.

The broker holds nonblocking exclusive flock locks on the secret-root and socket
directory inodes before binding. A second broker sharing either directory fails
startup without replacing the live socket. The directory must have no other writer:
do not modify it from the host while onboarding is active. Python/Linux has no
portable unlink-by-descriptor primitive; a privileged external writer could still
race the final stat/unlink or copy receipt xattrs onto a replacement. This is not
claimed to protect against a hostile host administrator. Read requests have an
absolute five-second receive deadline, not a resettable per-byte budget.

### Failure and reconciliation policy

Secret creation must finish before INSERT. A failed secret step rolls back only
earlier successful creations from that attempt; no registry INSERT is attempted.
A definitely rejected SQL statement rolls back only this attempt's receipts.
A separate adapter transaction boundary encloses INSERT, fetch and commit.
Returned-row/domain conversion occurs outside that boundary. Any conversion error,
including ValueError/TypeError, triggers reconciliation, never definite rollback.
A connection/commit uncertainty triggers an exact source_instance lookup using
the writer connection. If the full stored configuration matches, registration
is treated as committed. Otherwise—including a failed lookup or an absent row
after an uncertain commit—secrets are retained and REGISTRATION_UNCERTAIN/503 is
returned. An absent row alone does not prove that a delayed commit cannot occur.
Rollback failure is also reported as uncertain, never silently successful.

There is no distributed transaction between PostgreSQL and the filesystem.
Process crashes during an incomplete file write, or loss of the API process's
attempt context, can leave an unreferenced secret. No broad cleanup is implemented.
Operators must reconcile exact registry
references before handling these files. Do not delete a file merely because the
browser reported failure. Durable completed-file receipts support safe retries,
but automatic background recovery after API crashes is not claimed by WEB-3.

### Database permissions (operator-only; never executed at startup)

Keep NETBOX_SYNC_REGISTRY_DSN on the WEB-2 SELECT-only role unchanged. Supply a
separate NETBOX_SYNC_REGISTRATION_DSN only for registration. The writer checks
schema_version=1 and reuses SourceRegistry's canonical validation/encoding/decoding
with an explicit adapter-owned INSERT transaction, never initialize(), migrations,
UPDATE, DELETE or UPSERT. Existing runtime SourceRegistry semantics are unchanged.

The writer role needs CONNECT on the database, USAGE on the registry schema,
SELECT(key,value) on schema_meta, SELECT on sources (the writer retains RETURNING *
and existing reconciliation uses SELECT * to load SourceConfig), and INSERT on these columns:

```text
id, source_instance, name, source_type, address, enabled, sync_enabled,
sync_interval_seconds, verify_ssl, site_slug, device_role_slug, platform_slug,
device_type_slug, cluster_type_slug, cluster_name, username, token_id_provider,
token_id_key, token_secret_provider, token_secret_key, legacy_identity_owner, settings
```

No sequence grants are needed (IDs are text). No UPDATE, DELETE, TRUNCATE, schema
CREATE, ownership, role administration or migration rights should be granted.
Review inherited/PUBLIC privileges separately. The reader gets no new grants.
These privileges narrow the writer, but do not enforce new-source flag defaults
against a compromised writer credential; those defaults are application policy.

### Operator deployment steps — not performed by this change

- Prepare /opt/netbox-sync/secrets/sources outside the repository, root:root 0700.
  Set NETBOX_SYNC_SOURCE_SECRET_DIR to that absolute directory. Do not chmod
  existing unrelated secrets. Compose defaults are development paths only.
  Host root:root ownership assumes rootful Docker without UID remapping; verify
  actual host ownership and extended-attribute support before enabling the broker.
  xattrs are mandatory: operator storage preflight must exercise create/setxattr/
  getxattr/fsync/rollback on this dedicated filesystem before enabling onboarding.
- Provide the isolated writer DSN through protected configuration; do not print
  or commit it. Docker administrators can inspect container environment.
- Start the web and onboarding profiles in the same Compose project. No broker
  dependency is added to the existing scheduler; registration fails safely if
  broker/writer configuration is absent. Read-only views still work.
- Preserve loopback publication (production uses NETBOX_SYNC_WEB_PORT=8001).
  Set NETBOX_SYNC_WRITE_HOSTS to exact browser-visible host:port values, including
  the chosen SSH tunnel endpoint, e.g. 127.0.0.1:18001. Do not use wildcards.
  For Vite development, explicitly allow the browser's 127.0.0.1:5173 authority;
  the default 8000 allowlist is for direct API-served frontend access.
- Apply the reviewed compose.yml directory mount during deployment: the same
  NETBOX_SYNC_SOURCE_SECRET_DIR is mounted read-only at /run/secrets/netbox-sync-sources in
  the runtime, read-write in the broker, and never in the API. Existing individual
  mounts remain, including /run/secrets/netbox-sync/esxi_netbox_sync_password. A Docker
  smoke test found that a read-only parent mount cannot create the absent legacy
  child mountpoint, so the dedicated directory uses a separate sibling path.
  FileSecretResolver retains /run/secrets/netbox-sync as its first lookup and falls
  back to the new directory only for a missing file, never for permission/validation
  errors. Custom resolver roots stay isolated unless a fallback is explicitly supplied.
  Both use identical flat logical references; do not rename old keys. New sources
  remain sync_disabled. No live deployment is performed by this change.

### Unauthenticated write protection and limitations

Writes require an allowlisted Host, matching Origin scheme/authority,
X-NetBox-Sync-CSRF: same-origin, JSON content type, bounded Content-Length and a
same-origin/none Sec-Fetch-Site value when present. No permissive CORS is enabled.
The custom header forces cross-origin browser preflight; Origin/Host checks reject
cross-site requests even if a caller bypasses preflight. This is not user
authentication: local non-browser callers can forge headers. Keep the service
loopback/SSH-only and restrict local host access. Do not publish it externally.

### Mandatory onboarding egress policy

Only ASCII bare hostnames/canonical IPv4 inputs are accepted. Protocol/port are
fixed to HTTPS/8006 (Proxmox) or HTTPS/443 (ESXi). No redirects are followed by
either adapter. The Proxmox probe is a narrow http.client GET, not proxmoxer.

Defaults permit RFC1918 destinations; public endpoints require operator allowlisting.
Loopback, link-local/metadata, unspecified, multicast, reserved and other special-use
addresses remain denied even when allowlisted. Single-label/container-local names
require an exact hostname allow entry. Normal internal DNS names resolving only to
approved private IPs work by default. Operator variables are comma-separated:

- NETBOX_SYNC_ONBOARDING_ALLOWED_CIDRS
- NETBOX_SYNC_ONBOARDING_DENIED_CIDRS
- NETBOX_SYNC_ONBOARDING_ALLOWED_HOSTS
- NETBOX_SYNC_ONBOARDING_ALLOWED_SUFFIXES

Any nonempty allow configuration becomes a restriction: every answer must match an
allowed CIDR or the approved hostname/suffix. Denied CIDRs always win. Prefer narrow
CIDRs/exact hostnames; allowlisting a public hostname authorizes its public DNS answers.
The production broker has literal `network_mode: none`; these variables apply only to the Test Connection child.

DNS is resolved once, every answer is checked, and one approved IPv4 answer is pinned
for every subsequent socket lookup in the isolated child. Original hostname/SNI and
certificate verification are preserved. No proxy environment is inherited; alternate
host/port lookups fail. IPv6-only endpoints are unsupported. DNS rebinding cannot
switch to a newly resolved address within this attempt. Network routing and operator
allowlist correctness remain deployment responsibilities.

The short-lived probe child inherits UID10001 and container hardening, but not registry
DSNs or broker configuration. Credentials travel through stdin, never argv/environment.
Dependency logging is disabled only in that child; stderr is discarded, stdout is a
small allowlisted result, and HTTP wire debugging is disabled. Parent/operator logs
are unchanged. The 15-second parent deadline covers DNS, all TLS/HTTP/SOAP calls and
logout; forced termination can leave a remote session until the server expires it.
No live connection tests are part of the mandatory suite. Do not enable core dumps;
Python does not guarantee zeroization of immutable strings.

Onboarding state is process-local: use the current single-worker startup.
Restarts invalidate pending tokens. There is no source editing, rotation, delete,
Sync Now, adoption, discovery UI, authentication or scheduler change. Future
WEB-4 should address durable onboarding recovery, authentication and full browser
workflow coverage before broadening deployment or write functionality.

The optional Web/API shell does not execute discovery, plans or sync. Existing
CLI execution, registry-all selection, identities, confirmations and systemd are
unchanged. Only file-secret lookup gains the compatible missing-file fallback.
No production cutover or migration is part of this change.

## Boundaries

`api/app.py` constructs FastAPI and maps application results to explicit frozen
Pydantic DTOs. `application/health.py` owns transport-neutral status aggregation
and accepts an injectable registry probe. `api/database.py` implements that port
with psycopg. Environment is read once by `api/settings.py` at factory bootstrap,
never mutated by requests. Neither routes nor health checks invoke sync helpers.

`frontend/src/` separates `api`, `types`, `components` and `pages`. React with
strict TypeScript fetches real health data on load or manual refresh; there is no
polling, fake inventory or action control. Failure replaces stale status with an
explicit error. Requests use a relative URL and a 15-second browser timeout.

## Endpoints and status semantics

| GET endpoint | Purpose |
|---|---|
| `/api/v1/health` | Cheap process liveness; no database connection |
| `/api/v1/system/health` | API, application, database, registry, NetBox configuration and overall status |
| `/api/v1/version` | Installed package version, without Git; `development` if not installed |

The system endpoint returns HTTP 200 when it successfully produces a report,
even when the report says `unavailable`. Container health uses liveness, not
external dependency readiness. Status values are `healthy`, `degraded`,
`unavailable` and `unknown`.

Database checks use SELECT 1, registry schema_version=1, and a LIMIT 0 projection
of non-secret source columns. They do not fetch source records or credential
references. Connections enforce read-only transactions, a 3-second connection
timeout and 2-second statement timeout. These are per-operation limits, not an
absolute request deadline (especially with multi-host DSNs).

An existing unbaselined registry v1 is readable: Alembic is neither required nor
invoked. Empty/missing/incompatible registry schemas report unavailable; no
tables are created or repaired. This is a basic readability check, not a full
constraint/schema audit. Database and registry failures use REGISTRY_UNAVAILABLE;
a readable database with an unreadable registry is reported separately.

NetBox is always `unknown`: only the presence of URL and token/token-file
configuration is checked, without opening a secret file or making a request.
Overall `healthy` means database/registry readable and NetBox configuration
present, NOT successful NetBox authentication, source connectivity or sync.
Missing database configuration or incomplete NetBox configuration is degraded;
an unavailable database/registry makes overall status unavailable.

Transport errors use `error: {code, message, request_id}` with fixed safe messages.
Unknown exceptions return API_INTERNAL_ERROR, never exception text. Each request
gets a fresh server UUID in X-Request-ID; client IDs are not reflected. JSON API
logs include component=api and request_id; run_id and source_instance remain null
because no run occurs. Paths, query strings, payloads and raw errors are not logged.
Use the documented `--no-access-log` flag to prevent separate Uvicorn URL logs.

## Local development

From the repository root, using Python 3.12 or 3.13:

```sh
python -m pip install -e ".[web]"
python -m pip install -r requirements-dev.txt
uvicorn netbox_sync.api.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

In a second terminal (Node 24 is used by Dockerfile.web):

```sh
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. Vite proxies `/api` to localhost:8000. Production assets
use the same origin as FastAPI, with no CORS middleware or wildcard origins.

```sh
npm run typecheck
npm run build
```

To serve the built shell locally, set NETBOX_SYNC_WEB_DIST to the absolute
`frontend/dist` directory before starting FastAPI. Only its index and assets are
served; there is no arbitrary file browser or SPA catch-all.

## Configuration

| Variable | Use |
|---|---|
| NETBOX_SYNC_REGISTRY_DSN | Existing registry connection convention; optional for degraded local startup; secret, never print it |
| NETBOX_SYNC_REGISTRY_SCHEMA | Existing registry schema convention; required for a configured registry |
| NB_API_URL | Presence-only NetBox configuration signal |
| NB_API_TOKEN / NB_API_TOKEN_FILE | Either counts as configuration present; neither resolved or returned |
| NETBOX_SYNC_WEB_DIST | Optional new API static-build directory; preset in Web image |
| NETBOX_SYNC_WEB_PORT | Optional new Compose loopback port, default 8000 |

Use a dedicated read-only PostgreSQL role with schema USAGE and SELECT access to
schema_meta and the queried sources columns. Do not grant migration/registry
write permissions. The API does not need source or NetBox secret mounts.

## Optional Compose role

```sh
docker compose -f compose.yml -f compose.web.yml --profile web up -d --build netbox-sync-api
```

Use the same existing Compose project name/configuration. Legacy compose.yml
still requires its existing environment values at interpolation time. For an
isolated local API-only check, `-f compose.web.yml --profile web` works alone;
this is not a second production stack or scheduler.

Dockerfile.web builds React assets and installs the optional web extra into the
same Python package. FastAPI serves the assets; no separate frontend container
or Redis is needed. The existing CLI Dockerfile is deliberately unchanged; a
shared deployed API/worker image is a future approved transition.

The API binds a host loopback port, runs non-root with read-only root filesystem,
dropped capabilities and a temporary /tmp. Healthcheck reads liveness only.
Compose forwards existing registry configuration and NetBox URL/token-file
presence (not token contents), and mounts no secrets. It does not create a DB,
change PostgreSQL healthchecks, or attach to production networks automatically.
Arrange private connectivity to the existing PostgreSQL endpoint using the
operator's actual network configuration; localhost inside a container is not
the host database. Never run migrations as part of API startup.

## Validation and limitations

```sh
pytest -q
pylint --fail-under=9.0 --max-line-length=120 netbox_sync
git diff --check
python -m build --wheel
```

API tests use injected fake connections, not production services. Existing
PostgreSQL/live ESXi integration tests remain opt-in. Frontend validation is
strict type-check plus production build; browser automation is not yet added.

Authentication is intentionally absent. Keep this API on loopback or a trusted
private access path; do not publish it directly to the Internet. No write API,
source CRUD, secret management, Sync Now, Plan, queue, worker, scheduler, or run
history is implemented. Reverse-proxy authentication/rate limiting/log policy
and production image/network validation remain deployment gates.

## WEB-2 source visibility

The shell has System Health and Sources navigation using local React state, not
a new routing/state framework. Refresh returns to System Health; source selection
is not a persistent URL. List and details fetch real API data with a 15-second
browser timeout, loading, empty and safe error states. No source connection test
is performed. Credentials are not loaded; no editing controls exist.

| GET endpoint | Response |
|---|---|
| `/api/v1/sources` | `{ "sources": [...] }`, including an empty list |
| `/api/v1/sources/{source_instance}` | One source DTO, exact instance match |

Both use the same explicit projection:

```text
source_instance, type, name, address, enabled, sync_enabled, verify_ssl,
sync_interval_seconds, site_slug, cluster_name, platform_slug, device_role_slug,
device_type_slug, cluster_type_slug, legacy_identity_owner, status
```

Target values are configured slugs/names, not live-resolved NetBox objects.
`type` maps from the `source_type` database column; `status` is derived, not stored:
disabled when enabled=false; sync_disabled when enabled=true and sync_enabled=false;
otherwise enabled. No status claims health/authentication. The configured interval
is not evidence that the existing systemd scheduler enforces per-source intervals.

SourceVisibilityService maps to immutable SourceView objects. PostgresSourceReader
selects only the 15 stored fields above (source_type instead of type; no status).
It never selects id, username, token_id_provider, token_id_key,
token_secret_provider, token_secret_key, settings, created_at or updated_at.
No SourceRegistry objects, credential resolvers, initialize calls or Alembic are
used in the read path. The registry version check and source query execute in a
read-only transaction with the same configuration and timeouts as WEB-1.

The API returns SOURCE_NOT_FOUND/404 for absent or invalid instance identifiers,
REGISTRY_UNAVAILABLE/503 for missing configuration, invalid schema, unsupported
registry version or database errors, and SOURCE_DATA_INVALID/503 for malformed
public metadata. Envelopes include the server-generated request ID; no driver
messages or queried instance strings are included in error messages/logs.

Addresses containing userinfo, query strings, fragments, encoded characters or
non-root paths are rejected rather than exposing potential credentials. This
conservative policy can reject a valid path-based endpoint: correct the public
address design before relaxing it. No generic sanitizer can detect a secret
deliberately stored as a display name or hostname; public metadata fields must
not be used to store credentials. An invalid row fails the complete list closed.
There is no pagination yet; intended for the existing small registry.

## Registry access and production viewing

compose.web.yml remains unchanged: supply NETBOX_SYNC_REGISTRY_DSN and
NETBOX_SYNC_REGISTRY_SCHEMA through the operator's protected environment/.env
configuration. Never commit or print a populated DSN. No DSN-file loader or new
secret mount is introduced. The DSN is visible to Docker administrators through
container configuration; protect host access accordingly.

Use a dedicated PostgreSQL login with CONNECT on the NetBox Sync database, USAGE
on the application schema, SELECT(key,value) on schema_meta, and column-level
SELECT on sources for the 15 projection columns plus id (WEB-1 health currently
reads id in a LIMIT 0 projection). Grant no table-wide source SELECT if credential
reference access should be prevented at the database layer. Do not grant writes,
schema CREATE, role administration or migration ownership. An operator must
review/apply permissions separately; WEB-2 never creates roles or changes grants.

The API must have private network reachability to PostgreSQL. Docker's localhost
is the container itself. Use the operator-managed private network/address; do not
publish PostgreSQL to the Internet. A supplied DSN is shared by health and source
visibility. Existing unbaselined registry v1 works without migration.

The reported production binding is 127.0.0.1:8001 -> container:8000. The checked-in
Compose default remains 8000; use NETBOX_SYNC_WEB_PORT=8001 for that deployment.
View it through an SSH tunnel, replacing the example user/host:

```sh
ssh -N -L 18001:127.0.0.1:8001 operator@netbox-sync-server
```

Open http://127.0.0.1:18001 and select Sources. Locally, run the API and Vite as
above, supplying only a disposable registry connection if testing data access.
This remains unauthenticated: never expose it publicly. Source addresses and
target metadata are operationally sensitive even without credentials.

## WEB-2 tests

```sh
pytest -q tests/test_api_sources.py tests/test_api_sources_postgres.py
cd frontend
npm test
npm run typecheck
npm run build
```

Node's built-in test runner tests source response validation and client errors;
no frontend test framework dependency was added. PostgreSQL tests require
NETBOX_SYNC_TEST_POSTGRES_DSN explicitly targeting database `netbox_sync_test`.
They create a unique netbox_sync_test_* schema, initialize fixture data only in
that disposable database, and drop that exact schema during cleanup. Never point
the test variable at production. Ordinary tests skip PostgreSQL when unset.

Recommended WEB-3: authentication/access-control foundation and broader UI/DB
integration coverage before adding write operations. Keep source CRUD, secret
writes, execution and scheduler cutover under separate explicit approval.
# WEB-4 read-only discovery worker

The API controls discovery only through `/run/netbox-sync-discovery/worker.sock`; it has no
source-secret or NetBox-token mount. The root supervisor reads the minimum read-only mounts,
then launches provider and NetBox reads as UID/GID 10001 with a restricted environment and a
120-second deadline. The worker publishes no port and joins only `netbox_default` for outbound
provider and NetBox access. Results are ephemeral.

The API retains its already-reviewed WEB-3 `NETBOX_SYNC_REGISTRATION_DSN` as an explicit exception.
That role remains registration-only; it is not supplied to the discovery worker and is removed from
the discovery child's environment. Neither API nor discovery receives registry sync/apply authority.

For production database `netbox_sync`, create the distinct reader role and grant only:

```sql
CREATE ROLE netbox_sync_discovery_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION;
ALTER ROLE netbox_sync_discovery_reader SET default_transaction_read_only = on;
REVOKE ALL ON DATABASE netbox_sync FROM netbox_sync_discovery_reader;
GRANT CONNECT ON DATABASE netbox_sync TO netbox_sync_discovery_reader;
REVOKE ALL ON SCHEMA netbox_sync FROM netbox_sync_discovery_reader;
GRANT USAGE ON SCHEMA netbox_sync TO netbox_sync_discovery_reader;
REVOKE ALL ON ALL TABLES IN SCHEMA netbox_sync FROM netbox_sync_discovery_reader;
GRANT SELECT (key, value) ON netbox_sync.schema_meta TO netbox_sync_discovery_reader;
GRANT SELECT ON netbox_sync.sources TO netbox_sync_discovery_reader;
```

Configure `NETBOX_SYNC_DISCOVERY_REGISTRY_DSN` with that role. Do not reuse the Web registration
or sync runtime role. Configure `NETBOX_SYNC_DISCOVERY_NB_API_URL` and mount a separate NetBox API
token at the host path in `NETBOX_SYNC_DISCOVERY_NB_TOKEN_FILE`. Its NetBox role needs view-only
permissions for DCIM devices, interfaces, sites, roles, platforms, device types, IPAM IP addresses,
prefixes and VLANs, and virtualization clusters, cluster types, VMs and VM interfaces. It must have
no add/change/delete permissions.

Mount only the legacy source-secret directory and WEB-3 source-secret directory, read-only. Start
the `web` and `discovery` profiles together. Smoke-check health and a protected discovery request,
then verify NetBox audit logs contain no POST/PATCH/PUT/DELETE. Never use an apply-capable NetBox
token for this worker.
# WEB-5 manual synchronization boundary

Manual synchronization uses a dedicated local Unix-socket apply worker. The API never receives
source credentials, a NetBox apply token, Docker access, systemd access, or a registry writer role.
The worker accepts only `prepare` and `apply` operations for one validated `source_instance`.

The worker registry role is read-only:

```sql
GRANT CONNECT ON DATABASE netbox_sync TO netbox_sync_apply_registry_reader;
GRANT USAGE ON SCHEMA netbox_sync TO netbox_sync_apply_registry_reader;
GRANT SELECT ON TABLE netbox_sync.schema_meta, netbox_sync.sources
TO netbox_sync_apply_registry_reader;
```

Do not grant this role `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, sequence access, DDL, or schema
ownership. The existing registration role remains separate.

Create a separate NetBox token for WEB-5. Based on the guarded executor paths it needs `view`
for Site, Device Role, Platform, Device Type, Cluster Type, Cluster, Prefix and VLAN; and
`view`, `add`, and `change` for Device, Device Interface, Virtual Machine, VM Interface,
MAC Address and IP Address. Do not grant `delete` on any model. Validate the precise NetBox
permission codenames against the deployed NetBox version before enabling the worker.

The canonical systemd unit calls the tracked
`/opt/netbox-sync/current/scripts/run-scheduled-sync.sh`. That wrapper owns the only scheduled
flock and contends with the manual worker on `/run/netbox-sync/apply.lock`. Only
`/run/netbox-sync` is mounted into the worker; broad `/run`, Docker socket, and secret-broker
socket mounts are forbidden. Historical host-managed wrappers must be disabled during cutover.

An enabled source remains manually eligible when `sync_enabled=false`; this flag continues to
control automatic registry-all scheduling only. Manual synchronization never changes either flag.

# WEB-6 durable run history

WEB-6 adds one shared PostgreSQL history model for confirmed manual attempts and
scheduled registry-all apply. It does not add a scheduler, retry, rollback, raw-log
viewer or full-plan archive. Every selected scheduled source has a separate record;
one source cannot overwrite another source's outcome.

`netbox_sync.sync_runs` stores a UUID run ID, historical source instance/type,
manual or scheduled trigger, UTC lifecycle timestamps, duration, closed status,
canonical plan digest/version, eight action totals, an allowlisted error code and
safe message, and `created_by`. It has no foreign key to `sources`, so source
decommissioning cannot erase history. It stores no credentials, secret references,
DSNs, provider payloads, NetBox responses, exception text, tracebacks or full plans.

The lifecycle is deliberately non-transactional with NetBox:

```text
manual POST /sync -> apply worker INSERT RUNNING -> existing confirmation/lock/
replan/apply flow -> UPDATE exact run terminal -> response includes run_id

systemd registry-all -> for each source INSERT RUNNING -> existing source apply
-> UPDATE exact run terminal -> continue next source
```

If the scheduled history INSERT fails, that source is not applied without its
audit start record; it is reported as a safe history-unavailable failure and the
batch continues. If terminal UPDATE fails, the actual source execution outcome
is preserved separately from `FINALIZE_FAILED`, and the batch continues. Neither
failure is retried, and raw database errors are never printed. A crash or lost
database connection can still leave `RUNNING`; automatic abandoned-run cleanup
is deferred rather than guessing the NetBox outcome.

An abrupt process or database failure can leave `RUNNING` visible. WEB-6 does not
guess success or retry it. Operator diagnostics/recovery for abandoned records is
deferred. Both write-capable runtime boundaries fail closed at startup when
`NETBOX_SYNC_RUN_WRITER_DSN` is absent; the API and discovery child never receive it.

Read-only endpoints are:

- `GET /api/v1/runs` with bounded `limit` (default 50, maximum 200) and optional
  `source_instance`, `source_type`, `trigger`, `status`, and cursor filters;
- `GET /api/v1/runs/{run_id}` for one public UUID.

Rows are ordered by `(started_at, run_id)` descending. Public DTOs explicitly list
safe fields. Invalid filters return `RUN_FILTER_INVALID`/422, a missing run returns
`RUN_NOT_FOUND`/404, and unavailable storage returns
`RUN_HISTORY_UNAVAILABLE`/503. The frontend Runs page provides loading, empty,
safe-error, summary and detail states without rendering raw backend errors.

## Run-history database roles

Keep the existing API reader and apply registry reader unchanged except for the
explicit history read needed by the API role. Run writes use a separate login.
The following is a grant template; substitute operator-selected role names and
manage passwords outside source control. Execute it only after the migration:

```sql
CREATE ROLE netbox_sync_run_writer LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION;
ALTER ROLE netbox_sync_run_writer SET default_transaction_read_only = off;
REVOKE ALL ON DATABASE netbox_sync FROM netbox_sync_run_writer;
GRANT CONNECT ON DATABASE netbox_sync TO netbox_sync_run_writer;
REVOKE ALL ON SCHEMA netbox_sync FROM netbox_sync_run_writer;
GRANT USAGE ON SCHEMA netbox_sync TO netbox_sync_run_writer;
REVOKE ALL ON ALL TABLES IN SCHEMA netbox_sync FROM netbox_sync_run_writer;
GRANT SELECT ON netbox_sync.sync_runs TO netbox_sync_run_writer;
GRANT INSERT (run_id, source_instance, source_type, trigger, started_at, status,
              plan_digest, planner_version, created_by)
ON netbox_sync.sync_runs TO netbox_sync_run_writer;
GRANT UPDATE (finished_at, duration_ms, status, plan_digest, planner_version,
              create_count, update_count, no_change_count, review_required_count,
              blocked_count, ignored_count, unsupported_count, retain_only_count,
              error_code, error_message_safe)
ON netbox_sync.sync_runs TO netbox_sync_run_writer;
```

Do not grant this role `DELETE`, `TRUNCATE`, DDL, schema ownership, sequence
access, or writes to `sources`, `schema_meta`, or `alembic_version`. UUIDs are
generated by the application, so no sequence permission is needed. Grant the
existing Web/API reader only:

```sql
GRANT SELECT ON netbox_sync.sync_runs TO netbox_sync_web_reader;
```

The API continues using its reader DSN. Supply the separate protected
`NETBOX_SYNC_RUN_WRITER_DSN` to the apply-worker container and to the host-managed
scheduled registry-all environment only. It is intentionally absent from the API,
discovery worker/child and secret broker. No Compose service receives Docker or
systemd control as part of WEB-6.

## WEB-6 production deployment gate

Do not run these steps automatically or against production without approval:

1. Back up the registry database and rehearse `alembic upgrade head` on a restored
   copy, including the existing-v1 adoption path.
2. Stop apply execution for the migration window; run the additive migration with
   the protected migration-owner DSN. Confirm revision `0002_sync_run_history`.
3. Create/review the narrow run-writer role and add `SELECT` on `sync_runs` to the
   Web reader. Store new DSNs in the operator-managed secret/environment facility.
4. Add `NETBOX_SYNC_RUN_WRITER_DSN` independently to the apply-worker and scheduled
   registry-all environments. Do not add it to API or discovery.
5. Rebuild/recreate the Web API/apply worker as required. Do not redesign or
   replace the current systemd timer/wrapper.
6. Smoke-test API list/detail, then a confirmed manual run and its matching UUID.
7. Observe one scheduled Proxmox and one scheduled ESXi history record, including
   isolated failure behavior, while preserving shared-lock contention.
8. Restart/reboot API and workers and confirm prior rows remain visible.
9. Audit container environments, grants and logs for DSNs, tokens, raw provider
   failures and other secret values before enabling normal operation.

# WEB-7 read-only diagnostics

`GET /api/v1/health` remains lightweight process liveness and is still the container
healthcheck target. `GET /api/v1/diagnostics` is a separate operator snapshot with
closed overall/component/source states. It reads the existing source projection and
`sync_runs`, checks both worker sockets with an exact `{"operation":"health"}` request,
and returns partial HTTP 200 diagnostics when one dependency is unavailable.

Worker health is answered in the root supervisor request loop before source lookup.
It accepts no source, starts no child, reads no registry row, source secret or NetBox
token, and performs no discovery/apply. The API uses a one-second socket timeout and
accepts only `{"ok":true,"result":{"status":"ok"}}`. Raw socket errors and paths are
not returned.

Scheduled Activity is inferred from persisted scheduled runs. It does not claim that
the systemd timer is loaded or active. An enabled/sync-enabled source becomes delayed
when its latest scheduled attempt is older than twice its configured interval, with a
minimum 30-minute threshold. No scheduled history is `UNKNOWN`, not a false failure.

RUNNING records older than `NETBOX_SYNC_DIAGNOSTICS_STALE_SECONDS` are reported as
`STALE_RUNNING`; the default is 7200 seconds and accepted bounds are 300 through
604800 seconds. At most 100 stale records are returned. Detection is SELECT-only:
WEB-7 never updates, deletes, finalizes, retries, or clears an abandoned run.

Source rules are deterministic: no runs or disabled source is `UNKNOWN`; latest
success without warnings is `HEALTHY`; latest failure with an earlier success,
delayed activity, or stale RUNNING is `DEGRADED`; a terminal failure with no prior
success is `UNHEALTHY`. Worker/history partial failures degrade the aggregate;
unreadable registry makes it unhealthy because source evaluation is unavailable.

History diagnostics use a fixed number of indexed queries (`DISTINCT ON` latest per
source plus a bounded 100-row stale query), not one query per source. Existing source/time,
status, and trigger indexes are used; no migration or new database permission is
required beyond the WEB-6 API reader's SELECT on `sync_runs`.

Deferred from diagnostics: abandoned-run cleanup, recovery/retry, live systemd
status, raw logs, notifications, RBAC/LDAP, and broader UI redesign. Do not give the
API Docker socket, DBus/systemd access, run-writer DSN, apply token, source secrets,
or host write access for diagnostics.

# WEB-8 per-source scheduling

The tracked base timer now contains the final fixed 60-second tick; a clean install needs no
drop-in. The tracked wrapper invokes registry-all under `/run/netbox-sync/apply.lock`; systemd
does not calculate individual source schedules. Existing installations must remove/reconcile
historical timer drop-ins during a reviewed cutover, never during an ordinary application update.

The runtime loads all registry sources and derives `DISABLED`, `WAITING`, `DUE`,
`RUNNING`, or `DELAYED` from configuration and scheduled history. The reference is the
latest scheduled `started_at` plus `sync_interval_seconds`; manual runs are ignored.
No history is due now. Missed ticks cause one execution only. Recent scheduled RUNNING
is skipped, while stale RUNNING remains visible and unchanged but does not block forever.
Disabling automatic sync never kills an existing run and does not disable manual sync.
Re-enabling an overdue source makes it due on the next tick.
Registry-row conversion and schedule evaluation are isolated per source. A malformed source or
evaluation anomaly produces only `SCHEDULE_EVALUATION_FAILED`, creates no scheduled history row,
and does not block other sources. `evaluation_failed` is reported separately in the scheduler
summary; execution, history, or evaluation failures make the process exit nonzero. Raw exception
details are never included in that summary.
`SYNC_MODE=inventory` is evaluation-only: it reads and prints decisions but does not
contact providers or create/finalize scheduled run records.

The schedule endpoint changes only `sync_enabled` and `sync_interval_seconds`. Desired
intervals are 60 through 86400 seconds. Expected previous values provide optimistic
concurrency; a mismatch returns `SCHEDULE_CONFLICT`. The API receives only the schedule
Unix socket, never the writer DSN.

Create a dedicated role using reviewed identifiers for the real database/schema:

```sql
CREATE ROLE netbox_sync_schedule_writer LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION;
REVOKE ALL ON DATABASE netbox_sync FROM netbox_sync_schedule_writer;
GRANT CONNECT ON DATABASE netbox_sync TO netbox_sync_schedule_writer;
REVOKE ALL ON SCHEMA netbox_sync FROM netbox_sync_schedule_writer;
GRANT USAGE ON SCHEMA netbox_sync TO netbox_sync_schedule_writer;
REVOKE ALL ON ALL TABLES IN SCHEMA netbox_sync FROM netbox_sync_schedule_writer;
GRANT SELECT (source_instance, sync_enabled, sync_interval_seconds)
  ON netbox_sync.sources TO netbox_sync_schedule_writer;
GRANT UPDATE (sync_enabled, sync_interval_seconds)
  ON netbox_sync.sources TO netbox_sync_schedule_writer;
```

Do not grant INSERT, DELETE, TRUNCATE, DDL, `enabled`/identity/credential updates,
`schema_meta` writes, or `sync_runs` writes. Supply its DSN only as
`NETBOX_SYNC_SCHEDULE_WRITER_DSN` to `netbox-sync-schedule-worker`.

Production rollout order: back up registry configuration; create/grant the narrow role;
install its secret environment; deploy the schedule worker socket and rebuild API/worker;
smoke read and optimistic update; evaluate a dry tick; install the reviewed 60-second
timer artifact; verify Proxmox 5-minute and ESXi 10-minute cadence; disable ESXi automatic
sync and verify Proxmox plus ESXi manual flow; re-enable ESXi and verify next-tick resume;
verify shared-lock contention, Runs, Diagnostics, and finally restart/reboot persistence.
Because the service is `Type=oneshot`, systemd does not run a second instance of the same
unit while it remains active; the shared flock also prevents overlap with manual apply.

Deferred: cron/timezones, clock-time schedules, maintenance windows, retry policies,
stale cleanup, live systemd control, notifications, RBAC, and source/credential editing.

### ESXi production-like multi-source validation (operator runbook)

Run this only against reviewed sources and disposable objects where a provider-side
change is requested. It is a checklist, not an automated production test:

1. Run ESXi discovery and verify the expected host/VM/NIC counts and the tested ESXi
   6.7 build 20497097 baseline.
2. Build an ESXi plan; verify managed objects are `NO_CHANGE` and the seven known
   name-only legacy objects remain `REVIEW_REQUIRED`.
3. Run one confirmed manual ESXi sync, then rebuild the plan and verify idempotency.
4. Observe one scheduled ESXi sync and one Proxmox sync at different configured
   intervals; verify separate source_instance, source_type, run_id, and diagnostics.
5. Disable and re-enable one source; confirm manual operations remain available and
   automatic execution resumes on its next due tick without backlog.
6. Use naturally occurring duplicate VM names or disposable VMs on test hypervisors;
   verify display names remain unchanged and v2 identities differ by source namespace.
7. Rename a disposable VM, apply its `UPDATE`, and verify the NetBox object ID and v2
   identity remain unchanged; a second plan must be `NO_CHANGE`.
8. Hide or remove only a disposable managed VM from a test source; verify
   `RETAIN_ONLY` and no NetBox delete, then restore it and verify the same identity.
9. Onboard a second ESXi or Proxmox source with its own address, username, secret
   reference, target Site/Cluster, interval, and TLS setting. Confirm neither source
   can match or update the other's objects.
10. Hold `/run/netbox-sync/apply.lock` and verify manual/scheduled contention fails
    safely, then verify Runs and Diagnostics stay source-scoped.
11. Restart/reboot the reviewed stack and repeat discovery, plan, history, diagnostics,
    schedule, credential-resolution, and shared-lock smoke checks.

Prefer `verify_ssl=true` after a trusted ESXi certificate chain is installed. Do not
silently change an existing source's TLS setting. Do not rename production VMs or
remove their visibility merely to exercise this checklist.

### Proxmox production-like validation (operator runbook)

Use reviewed sources and disposable test objects only. This checklist authorizes no
production VM/LXC mutation or deletion:

1. Run read-only discovery and verify the PVE 9.1.9 baseline, node, 23 QEMU guests,
   and LXC 101 `reverse-proxy` without exposing provider payloads or secrets.
2. Build a plan: managed host/QEMU/LXC/NIC objects should be `NO_CHANGE`; imported
   same-name objects must remain review/blocking candidates.
3. Run one confirmed manual sync, rebuild the plan, and verify zero effective writes.
4. Observe Proxmox and ESXi schedules at different intervals with independent source,
   history, scheduler, and diagnostics state.
5. Disable/re-enable automatic Proxmox sync; manual operations remain available and an
   overdue source creates at most one attempt on its next tick.
6. On disposable sources, verify same QEMU names/VMIDs remain source-isolated and a
   same-name QEMU/LXC pair remains kind-isolated.
7. Rename a disposable QEMU and, where available, LXC. Apply must update the same
   NetBox object/identity; the following plan must be `NO_CHANGE`.
8. Hide only a disposable managed guest or NIC. Verify `RETAIN_ONLY`, no delete, and
   reuse of the same identity after restoration.
9. Onboard a second Proxmox source with unique source_instance, address, username,
   token references, Site/Cluster, interval, and reviewed TLS setting. Confirm each
   resolves only its own secrets and cannot match the other's objects.
10. Verify missing VLAN/Prefix, foreign/duplicate MAC/IP, and foreign/manual primary
    cases fail closed or preserve only a proven same-VM primary.
11. Hold `/run/netbox-sync/apply.lock`; manual and scheduled apply must contend on the
    same inode without provider-specific locking or automatic retry.
12. Verify Runs and Diagnostics, then restart/reboot and repeat discovery, planning,
    schedule, history, credentials, and shared-lock checks.

A Proxmox node rename changes the current host identity and requires its own migration
plan. Final cross-provider live Multi-Source Validation remains a later stage.

### Multi-source live validation (operator runbook)

This checklist is read-only except for separately confirmed NetBox Sync operations. Never
rename, hide, create, or remove a production workload merely to exercise a test:

1. Confirm `pve-infra-test` and `esxi-infra-test` appear independently with intervals 300
   and 600 seconds, distinct target data, and no credential fields in API responses.
2. Run Discovery and Build Plan for each source. Proxmox should show expected managed
   `NO_CHANGE`/`RETAIN_ONLY`; ESXi may also show the previously reviewed legacy
   `REVIEW_REQUIRED` items. Do not adopt them implicitly.
3. Confirm a manual sync for one source at a time, then rebuild both plans. Verify the
   other source remains unchanged and each repeated plan is idempotent.
4. Observe fixed ticks until Proxmox runs at five-minute cadence and ESXi at ten-minute
   cadence. Verify distinct run UUIDs, source types, terminal states, durations, latest
   successes, scheduler states, and source-scoped diagnostic warnings.
5. Disable one source's automatic sync. It must create no scheduled attempts while the
   other continues; manual Discovery/Plan/Sync remains available. Re-enable it and verify
   at most one overdue attempt on the next tick.
6. Hold `/run/netbox-sync/apply.lock`. Scheduled/manual contention in either direction must
   fail closed with no partial writes. Reuse the already validated WEB-8 procedure.
7. Use only naturally duplicated names or disposable test VMs to verify that identical
   display names remain unchanged while identity/source history remains distinct.
8. If a disposable workload is available, test rename and temporary disappearance:
   same NetBox object ID, stable identity, `UPDATE` then `NO_CHANGE`, or `RETAIN_ONLY`
   with no delete followed by reuse on reappearance.
9. Restart the application services and finally reboot during an approved window. Verify
   registry rows, schedules, secrets, history, workers, timer cadence, and diagnostics
   persist and recover without re-registration.

For a supplied second or third test hypervisor, onboard it only through Web with a unique
source_instance, address, credentials, TLS setting, Site/Cluster, and interval. Confirm no
SSH/environment, wrapper, Compose, or mount edit is required; refresh Web and observe the
new source on the next scheduler tick. Validate its Discovery and Plan before enabling
automatic sync. Same-ID and credential tests must use disposable sources—never manipulate
production VMIDs, UUIDs, or secrets.

Readiness for the pre-v1 deployment audit requires all existing sources to pass the above,
no unresolved name/IP/MAC ownership candidate, stable shared-lock contention, independent
history/diagnostics, and reviewed total sequential tick duration. Source deletion, cloud
providers, vCenter, topology redesign, parallel apply, RBAC, notifications, clean deployment,
and UI redesign remain separate work.

## UI-0 / UI-1 frontend foundation

See [Frontend foundation](frontend.md) for routing, operational Overview, Sources filtering, and status evidence boundaries.

## UI-6 current operation/lifecycle API contract

This section supersedes earlier synchronous-only and create/rollback-only descriptions.
The API exposes protected `POST /api/v1/sources/{source}/operations/plan` and
`.../operations/discovery` (202, current operation, including duplicate starts), plus
`GET .../operations` (at most two latest slots). Closed DTOs reject foreign identity,
inconsistent kind/result/status and unexpected worker fields. Canonical planner results
are validated before persistence and projected without internal source IDs or secrets.
Existing synchronous plan/discovery compatibility endpoints use the same durable store;
the frontend uses short start/read requests. The discovery parent alone receives
`NETBOX_SYNC_OPERATION_WRITER_DSN`; provider children never receive it.

Prepare now requires the reviewed `operation_id` in the configured production path.
The single-use capability binds it to the source and existing digest; Apply checks the
current READY generation under the existing shared apply lock and still replans.
Apply request operation metadata is not an alternative authorization token. PLAN_STALE
revalidation invalidates only the exact reviewed generation through the discovery worker;
failure to update that projection does not permit Apply. No weaker parallel apply path.

`GET .../lifecycle` returns active revision or tombstone. Protected `POST .../remove`
requires `confirmed_source`, current `revision`, and strict `remove_credentials` boolean.
The API sends only fixed lifecycle actions over the peer-checked lifecycle worker socket; it cannot
request arbitrary paths or a general file deletion. Public errors are allowlisted.
The separate lifecycle worker holds the narrow lifecycle DB capability and shared lock.
The secret broker has `network_mode: none`, no DB connectivity and no NetBox/provider
egress. Only its local filesystem operations remain. No provider credentials are revoked.
No API migration-owner/writer DSN or source-secret filesystem mount is introduced.

This remains an operator UI behind the established access boundary, not authentication
or RBAC. Run history remains the evidence for actual synchronization and uncertain writes.
See [architecture](architecture.md), [deployment](deployment.md) and
[isolated historical bridge](historical-ui-test-bridge.md).

## First-run Bootstrap

The [first-run guide](first-run.md) describes `/setup`, the durable readiness gate,
separate NetBox tokens, bounded validation, manual prerequisites and restart recovery.
GET `/api/v1/bootstrap` returns secret-free state; POST `/configuration`, `/validate`
and `/finish` under that prefix reuse origin/CSRF checks and carry expected revisions.
Only the separate Bootstrap worker writes protected NetBox configuration.
