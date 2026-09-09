# Source connection probe: production boundary and upgrade

## Cause and selected boundary

Bundled production API is attached only to `netbox-sync-db` (`internal: true`).
The previous Test Connection child process ran inside that API container, so it
inherited a network without external reachability. Host DNS success does not prove
container DNS/routing. Frontend mocks and direct Python probe tests did not exercise
this production network path.

The fix keeps the API network unchanged. A new **netbox-sync-probe-worker** receives
one ephemeral request over `/run/netbox-sync-probe/worker.sock`. The named socket
volume is read-only in API and writable only in the worker. The worker alone joins
a dedicated `netbox-sync-probe-egress` bridge, with ordinary Docker DNS/routing.
No ports are published. PostgreSQL remains on its internal network and broker
remains literally `network_mode: none`. No API/DB ports, role grants, migrations,
provider writes, shared apply lock or lifecycle semantics change.

The trusted caller is the API UID 10001, enforced by Unix `SO_PEERCRED` and socket
root:10001 mode 0660. The worker has no DB configuration/credentials, stored provider
credentials, NetBox tokens, source/config mounts, Docker socket, systemd control or
shared lock mount. Parent root has only CHOWN/SETUID/SETGID/KILL beyond cap_drop ALL, to
own its socket and launch the child as UID/GID 10001 with supplementary groups empty.
KILL is required for the root parent to kill/reap its different-UID child on the total deadline; the worker has its own PID namespace, with no host PID access.
Root filesystem remains read-only, no-new-privileges and bounded tmpfs remain set.

Only existing fixed probe operations are available: Proxmox HTTPS/8006 version GET;
ESXi HTTPS/443 version GET, SOAP login, RetrieveContent and logout. Credentials move
through the Unix request and child stdin, never argv/env/log files. Child environment
is sanitized, stderr discarded, SDK logging disabled, and only closed error codes
return. Serial worker processing bounds concurrent children; queued/unavailable
transport fails closed and never falls back into API. Whole child deadline is 15s,
I/O deadline 5s, Unix client 18s. Pending registration secrets retain the existing
API in-memory TTL contract; the worker adds no durable credential state.

The API supplies its validated operator egress policy; this is an authenticated
internal caller contract, not protection against arbitrary code execution inside
API. Child validates destinations and pins DNS exactly as before, retaining TLS
hostname verification. Private IPv4 destinations are allowed by existing default
policy; public destinations require explicit authorization. Loopback, link-local,
metadata/reserved/multicast and denied ranges remain forbidden. The dedicated bridge
is not an L3 destination firewall: deployments requiring subnet-level egress controls
must enforce those controls at the host network. No arbitrary URL/path/port API was
added. Docker DNS must be able to resolve the operator's source names.

Standalone and external ingress use this same worker; public authority/origin checks
are unchanged. `compose.external-postgres.yml` retains its existing API network
contract for reaching an operator database. Optional **NetBox** CA trust continues on
the existing NetBox worker mounts and is not repurposed as provider CA configuration.
The existing provider verify_ssl setting and OS trust store behavior are unchanged.

Installer starts the additional canonical `<project>-probe-worker` service. No new
host env values are required: production Compose sets NETBOX_SYNC_PROBE_SOCKET.
Direct non-Compose/dev callers without that setting retain the bounded local child
path. No broad API egress is added. Backup's list of write services is unchanged:
quiescing API stops admission, and any remaining probe only reads provider state and
holds ephemeral memory. It cannot alter the backup or persistent product state.

## Checked regression path

`tests/test_probe_compose_docker.py` uses an isolated Debian host harness and actual
production/external-ingress Compose files, with unique project resources. Only the
operator test harness receives Docker control; application containers do not.
A controlled HTTPS/SOAP endpoint is on the probe egress network, outside the DB
network. A test-only CA certificate is mounted read-only in the probe trust store;
verification remains enabled. No production network, tmpfs, capability or port
parameter is replaced. Test server keys stay private in disposable test storage.

The bundled scenario explicitly disables worker delegation to reproduce the old
real API child failure, then restores production Compose and proves SOAP success.
Both bundled and external PostgreSQL exercise the real API, completed onboarding,
safe auth/timeout/TLS/destination/connection/DNS/format codes and unchanged protected configuration/credentials.
The bundled scenario also prepares/activates a second immutable release through
installer components, reapplies roles/migrations/grants, checks unchanged DB container
and volume, preserves completed onboarding and tests the probe after activation.
This is component upgrade evidence, not a Debian systemd/reboot or live hypervisor test.

## Existing /netbox-sync-test upgrade after review and publication

Use the maintenance process in [onboarding verification](onboarding-verification.md)
and the [backup workflow](backup-restore.md). Before any installer operation:

```sh
ROOT=/netbox-sync-test
readlink -f "$ROOT/current"
git -C "$ROOT/repo" status --short
git -C "$ROOT/repo" rev-parse HEAD
systemctl is-active netbox-sync.timer
systemctl is-enabled netbox-sync.timer
docker ps -a --filter label=com.docker.compose.project=netbox-sync --format '{{.ID}} {{.Names}} {{.Status}}'
```

Stop if checkout is dirty, root/current/config ownership is ambiguous, canonical
container names conflict, or any existing DB password file is missing. Record DB
volume identity from its mount metadata (never dump full inspect/env). Produce,
verify and inspect a supported backup before activation. If current is still
6639c38, use the reviewed stdlib backup tool **against old current** as described
in backup-restore.md; do not activate a release merely to obtain the backup fix.

After securely obtaining the reviewed published commit in the existing checkout,
set RELEASE to its full approved hash and confirm the clean checkout matches:

```sh
: "${RELEASE:?Set the exact reviewed published commit}"
test "$(git -C "$ROOT/repo" rev-parse HEAD)" = "$RELEASE"
sudo python3 "$ROOT/repo/deploy/install.py" --root "$ROOT" --ingress-mode external --check
sudo python3 "$ROOT/repo/deploy/install.py" --root "$ROOT" --ingress-mode external --check-tls
sudo python3 "$ROOT/repo/deploy/install.py" --root "$ROOT" --source "$ROOT/repo" \
  --release-id "$RELEASE" --public-url https://netbox-sync-test.indeed-id.hq --ingress-mode external
```

Use the same root/project/config/volume and public URL. Do not regenerate credentials,
change ingress mode, run down -v, perform naming migration or reset onboarding.
Do not use prepare-only/no-start/no-systemd for the complete systemd-managed upgrade.
The installer stops the timer, holds the shared apply lock, prepares the release,
publishes configuration/current and starts all runtime services; success enables
the timer. Failure is a stop condition: current/config rollback does not prove all
containers/timer resumed. Inspect metadata before a reviewed recovery; do not blindly
retry an immutable release ID.

After success verify current, timer, unchanged DB volume, completed Web onboarding,
and ten canonical running containers for bundled PostgreSQL (nine runtime + DB).
Confirm broker network none, no API/DB ports, worker on the dedicated bridge, then
use Test Connection in the form. Shared ingress continues at
`$ROOT/ingress/upstream.sock`; outer TLS/certificates stay operator-owned. This runbook
has not been executed on the live VM. Real source DNS/TLS/ACL/discovery acceptance
remains the operator's next gate.

## Verification record (2026-09-09)

- Docker Engine 29.7.2, Compose 5.5.0, Linux containers on Docker Desktop.
- Actual production probe smoke: **2 passed**, bundled + external PostgreSQL,
  external ingress; bundled additionally exercises installer component upgrade.
- Before delegation: actual API-local child fails from the DB-only network.
  After delegation: API → worker → verified HTTPS/SOAP succeeds.
- Additional deadline regression initially returned SOURCE_CONNECTION_FAILED under
  capabilities without KILL. With KILL only on the probe worker, timeout reports
  SOURCE_TIMEOUT, the UID-10001 child exits by SIGKILL and is reaped.
- Existing production TLS smoke: **3 passed** (standalone, corporate, external),
  SPA/API proxy, exact authority, invalid TLS rejection and custom NetBox CA behavior.
- Linux backend/Unix/security suites: **168 passed**, 3 Compose-CLI skips in the
  networkless runner. Those Compose checks pass on the host: **47 passed**, 4 POSIX
  skips there, all covered by the Linux run. No required case remains skipped.
- Frontend transport/unit: **54 passed**. Browser guidance + foundation + hardening:
  **45 passed**, including original Add Source journey, EN/RU, light/dark, narrow
  390px guidance and zoom, retained inputs, clipboard commands and redacted errors.
- TypeScript, Vite production build and git diff --check pass.
- Screenshots are generated in frontend/test-results/access-*.png with empty secret
  inputs; they are local review artifacts, excluded from Git.

Reproduce with purpose-built test images (never point these at live resources):

```sh
docker build -f Dockerfile.web -t netbox-sync-probe:review .
docker build -f tests/Dockerfile.backup-host -t netbox-sync-probe-host:review .
NETBOX_SYNC_PROBE_DOCKER_TEST=1 python -m pytest tests/test_probe_compose_docker.py -q -s
```

The scripts create uniquely labelled resources and remove only those resources.
They do not touch the VM, use live credentials, validate a live hypervisor or perform
real systemd/reboot acceptance. The controlled SOAP endpoint models connection
operations; complete Discovery privilege acceptance remains a separate operator gate.

## Destination policy and local administrator

The accepted follow-up implements server identity and the separate auth/policy
worker. See [the current contract](local-admin-policy.md), including the route
permissions, one-time host ceiling transition, exact web exceptions and stale
receipt fences. The process/transport guarantees above still apply. Origin/CSRF
and Bootstrap READY alone cannot authorize a probe or policy change. See
[review evidence](local-admin-policy-review.md) for the pending upgrade gate.

## Diagnosing a reported old frontend without guessing cache

After an approved update, compare the public page's `netbox-sync-ui-build` metadata
with the same metadata in the running API image `/app/web/index.html` and the
System health details. Inspect only current symlink/release ID, image ID, Compose
project/service labels and public asset status codes. Do not print env files or
container configuration dumps containing secrets. A mismatch identifies a delivery
or release/upstream selection issue; an identical fingerprint directs investigation
to the actual UI state. Browser cache alone is not established by an old screenshot.
The production smoke checks recognized routes, built JS/CSS/font/brand assets,
no-store HTML, API/static 404s and TLS/authority enforcement.
