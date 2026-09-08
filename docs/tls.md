# DNS, HTTPS and explicit NetBox CA trust

Standalone production uses `compose.production.yml` and the existing `deploy/install.py`.
External/shared ingress is also supported; see [its exact Unix-socket contract](external-ingress.md).
Follow [the pinned clean-install runbook](clean-install-tls-runbook.md). NetBox
remains a separately installed external dependency; this project does not deploy it.

## Boundary and threat model

The conventional official `nginx:stable-alpine` image terminates TLS. There is no
ACME dependency. The operator issues and renews certificates. nginx runs as numeric
UID/GID 10001, with all capabilities dropped, no-new-privileges, a read-only root
filesystem and temporary files under `/tmp`. It publishes host 80/443, mapped to
unprivileged container 8080/8443. The only upstream is the API's Unix socket.

```text
trusted operator network -> TCP 443 nginx -> private Unix socket -> API
                         TCP 80: fixed canonical HTTPS 308 redirect
API -> internal PostgreSQL network (no published database port)
bootstrap/discovery/apply/scheduler -> authorized NetBox/provider HTTPS
lifecycle/schedule -> DB only; secret broker -> network_mode: none
```

The HTTP socket volume is mounted into API (read/write), nginx (read-only), and a
networkless one-shot initializer. It is not mounted into other workers. API listens
only on `/run/netbox-sync-http/api.sock`, not TCP, and runs as UID 10001. Initialization
uses root with CHOWN only; it sets directory mode before transferring ownership.
The API keeps its existing narrow reader/registration DSNs. No database grants or
migrations change. The lifecycle writer, broker filesystem authority, source scopes,
retained history/objects, tombstones and shared apply lock remain unchanged.

Uvicorn proxy middleware is disabled. In public mode the API requires a Unix peer
(`scope.client is None`), exact canonical Host and `X-Forwarded-Proto: https`.
nginx overwrites Host/scheme and strips client Forwarded, X-Forwarded-Host and
X-Forwarded-For. A direct TCP request with forged headers is rejected, even if an
operator accidentally starts the app on TCP. Local Unix GET `/api/v1/health` with
Host localhost is the narrow liveness exception. Socket access implies trust;
host root and a compromised nginx are inside this boundary.

Writes still require the exact HTTPS Origin and CSRF marker. There are no wildcard
host defaults. nginx rejects other Host values with 421; HTTP redirects use the
configured authority rather than the caller's Host. Request bodies are limited to
16 KiB, upstream connect/send/read timeouts are 3/30/360 seconds. nginx never retries
an upstream mutation. The UI uses same-origin relative URLs and polling, not WebSockets.

TLS is not operator authentication. The product still has no LDAPS/RBAC/login.
Restrict 80/443 to the trusted operator network using the deployment infrastructure;
do not expose the unauthenticated control interface to the public Internet. Docker
published-port firewall policy must be reviewed at the host/upstream boundary.

## Public URL and DNS

Fresh installation requires `--public-url https://lowercase.fqdn`, with no port,
path, credentials, query, fragment, wildcard or literal IP. No hostname is a default.
The installer generates `NETBOX_SYNC_PUBLIC_URL` and the exact write authority in
`config/api.env`; `NETBOX_SYNC_PUBLIC_HOST` and canonical mount paths go into
`config/compose.env`. Do not manually edit or shell-source generated env files.
The nginx template is release code, rendered into `/tmp/nginx.conf` at startup.

Example Sync DNS: `netbox-sync-test.indeed-id.hq` points to the Sync VM. Example
NetBox DNS: `netbox-test.indeed-id.hq` points to the separately managed NetBox HTTPS
endpoint. Both operator clients and relevant containers must resolve the names.
Publish AAAA only if that complete path is supported; bootstrap currently requires
an approved IPv4 destination. These names are examples, not defaults.

Standalone Compose owns host ports 80/443. For two applications on one host, use
[external ingress mode](external-ingress.md): the operator-owned shared ingress
owns those ports and routes Sync to its protected Unix upstream. NetBox remains
independently installed and configured; no NetBox ingress configuration is shipped.

## Operator material

| Host path under `/opt/netbox-sync/secrets` | Owner | Mode | Consumer |
|---|---|---|---|
| `tls/` | root:10001 | 0750 | nginx only |
| `tls/fullchain.pem` | root:10001 | 0640 | nginx, read-only |
| `tls/privkey.pem` | root:10001 | 0640 | nginx, read-only |
| `ca/` | root:root | 0755 | outbound NetBox clients |
| `ca/netbox-ca.pem` (optional) | root:root | 0644 | outbound NetBox clients, read-only |

The parent `secrets/` remains root:root 0700. Rootful Docker bind-mounts the leaf
directories; UID 10001 never traverses the host secret parent. Reserve this numeric
identity on the host and do not grant it to unrelated local accounts. Rootless/userns
remapped Docker is not the tested deployment model.

`--init-tls-layout` creates only canonical directories; it generates no certificates,
passwords, configuration or containers. Certificates must contain the public FQDN
in SAN and a complete leaf-first intermediate chain. The private key must be an
unencrypted PEM suitable for unattended startup. Installer preflight checks regular
single-link files, numeric ownership, exact modes, size, key matching, current expiry
and hostname before database preparation. Symlinks are rejected. `--check-tls` is a
read-only file/certificate check. External chain trust is checked separately by the
runbook; host preflight does not certify the operator's issuer or DNS reachability.

Only nginx receives `/run/netbox-sync-tls` read-only. Neither private-key bytes nor
certificate bytes are placed in env files, DB, browser state or application logs.
Git, Docker context and release packaging exclude the secret tree and canonical
private-key filenames. Keep all operator material outside the checkout. Backups intentionally include
these protected files: treat the entire backup as secret and encrypt it off-host.

## NetBox CA trust

Only bootstrap, discovery, apply and the transient scheduler mount the canonical
CA directory at `/run/netbox-sync-ca`, read-only. Broker, lifecycle, API, schedule
control, proxy and PostgreSQL do not receive it. Development/legacy NetBox clients
use the same explicit contract. The exact filename `netbox-ca.pem` is the only input;
other mounted certificates are not discovered or trusted automatically.

Each NetBox Requests/pynetbox session sets `trust_env=False`. Without that file,
Requests' packaged CA bundle and hostname verification remain enabled. Installing
CA trust only on the Debian host does not configure containers. With a valid bundle,
the client creates a private temporary combined bundle containing Requests' standard
roots plus the operator CA and assigns its path to `session.verify`. The temporary
bundle lives for that client only. Invalid contents, modes, owners, links or private
keys fail closed; bootstrap reports `TLS_FAILED`. There is no insecure fallback,
proxy environment inheritance, `verify=False` or hostname-verification exception.
Provider trust settings are independent and unchanged.

## Health, renewal and upgrade

API health uses its Unix socket. nginx health is its private localhost:8081 listener;
nginx cannot start it successfully if loading the TLS listener/key fails. The installer
requires both checks and all long-running services before enabling the timer. These
checks prove process readiness, not external DNS/firewall/CA trust or NetBox readiness.
External curl/openssl checks remain mandatory. An unconfigured NetBox gives FRESH
Bootstrap and degraded product readiness while HTTPS/UI liveness stays available.

For renewal, install both new files with the same owner/modes from protected operator
staging. Do not print keys. nginx continues using the loaded pair until reload. Run:

```sh
sudo python3 /opt/netbox-sync/current/deploy/install.py --check-tls
sudo python3 /opt/netbox-sync/current/deploy/compose.py exec -T netbox-sync-proxy \
  nginx -c /tmp/nginx.conf -t
sudo python3 /opt/netbox-sync/current/deploy/compose.py exec -T netbox-sync-proxy \
  nginx -c /tmp/nginx.conf -s reload
```

Stop on either validation failure; do not reload a failed pair. Repeat external chain,
hostname and HTTPS checks after reload. Renew before expiry. CA replacement uses the
same protected exact file and is consumed by newly created client sessions; already
running operations keep their original trust bundle. Validate again through onboarding
when applicable; do not restart or interrupt active synchronization to force rotation.

Existing HTTPS installs preserve public URL/certificates/CA on installer reruns. A
conflicting explicit URL is rejected; changing the canonical hostname requires a
separately reviewed transition. Upgrading an older HTTP release requires explicit
`--public-url` and operator certificates before preparation. The old loopback write
allowlist is replaced by the chosen authority. Existing secrets and other operator
settings remain. Timer/shared-lock/activation rollback semantics remain in force.
There is no DB migration for TLS: head remains `0005_source_tombstones`.

Backup v1 now recognizes the exact TLS/CA permission exceptions, preserving numeric
metadata. Restore rejects a different public URL and validates TLS before DB restore.
An older bundle without TLS can use the prepared target's operator TLS/CA material.
Host-local mount paths are rewritten to the target root. Source secret rules are not
relaxed; unknown files below TLS/CA are rejected by backup validation.

## External NetBox prerequisites

NetBox must expose the exact HTTPS base URL through its separately managed proxy,
with matching SAN, valid complete chain and trusted issuer. No redirect is accepted
by the bootstrap probe. Configure NetBox's own allowed-host/CSRF/public-origin settings
for its FQDN according to that deployment; Sync does not configure NetBox or access it
from the browser cross-origin. NetBox's private key is never copied into Sync.

Provide distinct read and apply tokens through Web onboarding. The read principal
must be read-only; the apply principal needs reviewed create/update permissions for
managed objects, without token reuse. The probe uses GET and OPTIONS on devices,
interfaces, clusters, VMs, VM interfaces and IP addresses, and reads custom fields.
It requires POST evidence only for the apply token. This does not prove every object
level PATCH permission or absence of delete grants: review those independently.

`netbox_sync/bootstrap_probe.py:FIELDS` is the exact machine-checked prerequisite
contract, also shown by onboarding. It requires JSON `sync_identities` and
`sync_original_names` on devices/interfaces/VMs/VM interfaces; device hardware fields
(`hypervisor_version`, `cpu_model`, `cpu_vendor`, `cpu_sockets`, `cpu_cores`,
`cpu_threads`, `memory_mb`, `physical_disks`); VM fields (`guest_kind`,
`guest_architecture`, `guest_os_type`, `swap_mb`); and VM-interface `source_bridge`
and `source_vlan_id`, with types/models defined there. Create them manually in NetBox;
Sync creates neither prerequisites nor VLANs/Prefixes automatically. Source-specific
Site/role/platform/device/cluster mappings are configured during later source setup.
The repository does not define a certified NetBox server version range. Do not infer
one from the pynetbox dependency; validate the actual endpoint/API contract.

Implementation references: [nginx proxy module](https://nginx.org/en/docs/http/ngx_http_proxy_module.html),
[nginx TLS module](https://nginx.org/en/docs/http/ngx_http_ssl_module.html),
[Uvicorn settings](https://www.uvicorn.org/settings/).
