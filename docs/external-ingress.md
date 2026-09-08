# External/shared ingress deployment mode

NetBox Sync supports two explicit deployment models. Standalone remains the default.
Use the [clean-install runbook](clean-install-tls-runbook.md) for either model.

| Contract | Standalone | External ingress |
|---|---|---|
| Installer | `--ingress-mode standalone` (fresh default) | `--ingress-mode external` |
| Public listener owner | NetBox Sync nginx, host 80/443 | Operator-managed shared ingress |
| Sync upstream | Private API Unix socket | Protected host Unix socket into Sync nginx |
| Sync published ports | 80/443 only | None |
| Sync nginx network | Dedicated Web bridge | Literal `network_mode: none` |
| Public server certificate | Canonical Sync TLS files | Outer ingress owns it; no duplicate required |
| NetBox additional CA | Optional canonical bundle | Same optional canonical bundle |

## Interface and compatibility

Fresh installs without a mode remain standalone. Existing installs lacking the new
setting are standalone. The installer writes `NETBOX_SYNC_INGRESS_MODE` and the
installer-owned `NETBOX_SYNC_INGRESS_DIR` into protected `config/compose.env`.
An omitted option on an upgrade preserves the saved mode. Invalid or duplicate mode
settings fail closed. An explicit different mode is a deliberate transition through
the existing timer/shared-lock/activation process; coordinate the outer ingress
separately, including releasing 80/443 before switching back to standalone. No
certificate, CA, source or token is deleted during a mode transition.

External mode requires Docker Compose >=2.24.4. Its checked-in override uses
`!reset` to remove ports/networks and `!override` to replace mounts, including removal
of the standalone TLS mount. These semantics prevent accidental additive merging;
see [Docker's merge contract](https://docs.docker.com/reference/compose-file/merge/).
The installer checks support before preparing the database.

Use the mode-aware operator command for all canonical Compose operations:

```sh
sudo python3 /opt/netbox-sync/current/deploy/compose.py ps
sudo python3 /opt/netbox-sync/current/deploy/compose.py config --quiet
```

It reads only the saved mode to select `compose.production.yml` and, for external
mode, `compose.external-ingress.yml`; it does not shell-source config or print env
contents. Installer, backup/restore and the scheduled wrapper use the same selector.
The scheduler still has exactly one host `flock`; containers gain no host control.
Do not run a bare production Compose file for an external deployment: that explicitly
selects the standalone model. Extra reviewed database overrides remain composable.

Restore preserves the prepared target's ingress mode and local socket directory,
not the source host's ingress topology. Public URL mismatch still fails. External
restore validates optional NetBox CA without requiring a public server key; standalone
restore retains certificate validation. For an external bundle with neither server
certificate nor key, standalone restore uses the prepared target pair. Partial
incoming TLS material fails closed. The socket is transient and is excluded from
backup; the installer/restore prepares its persistent parent directory.

## Exact local boundary and trust

Canonical host upstream is HTTP over:

`/opt/netbox-sync/ingress/upstream.sock`

The directory is numeric **10001:10001, mode 0750**; the installer creates it. It is
outside releases, secrets, backup payload and `/run`, so its owner/mode survive reboot.
nginx recreates its listener socket when starting/restarting. Do not chmod the parent
to 0777, expose this socket directory to unrelated containers or share group 10001
with untrusted local users. Host root and the selected ingress worker identity are
trusted. An unrelated UID cannot traverse the directory/connect to the socket.

Only the Sync nginx service mounts that host directory read/write, at
`/run/netbox-sync-ingress`; API has no host ingress mount. The internal API volume
and Uvicorn Unix-only listener are unchanged. The Sync nginx has no network, host
ports, certificates, DB/provider secrets, Docker socket or systemd access. Its
localhost health listener is reachable only inside its network namespace.

For a host ingress, authorize its worker identity to traverse/connect using numeric
group 10001 outside this repository. For an operator-managed container ingress,
bind-mount only `/opt/netbox-sync/ingress` read-only and grant its worker that group.
Do not mount the API volume, source secrets or Docker socket into the outer ingress.
The outer ingress must support HTTP upstreams over Unix sockets; this mode does not
publish a loopback TCP alternative. It is a same-host boundary, not a remote backend.

The outer ingress must terminate valid HTTPS for the exact configured public FQDN,
redirect public HTTP to HTTPS, reject unexpected authorities and overwrite Host and
`X-Forwarded-Proto` with the canonical host and `https`. It must not copy arbitrary
client-supplied forwarded headers. Sync nginx rejects other Host values (421) and
missing/non-HTTPS forwarded scheme (403), then overwrites these upstream headers
and strips other Forwarded/X-Forwarded fields. API requires its Unix peer and retains
exact HTTPS Origin/CSRF checks. The browser uses the public HTTPS URL, never the socket.

This is filesystem-based ingress authentication. A compromised root/authorized ingress
worker is inside the trust boundary and can construct accepted proxy requests; headers
alone cannot authenticate that peer. An arbitrary remote client cannot reach the
socket; an untrusted local user cannot connect by forging headers. As in standalone,
TLS is not product login/RBAC. Limit public listener access to trusted operators.

## Certificates and health ownership

Standalone continues to require `/opt/netbox-sync/secrets/tls/fullchain.pem` and
`privkey.pem` with the existing 0750/0640 root:10001 contract. External mode neither
loads nor mounts them. Empty TLS directories may exist for canonical layout/backup
compatibility; no duplicate certificate or key is required. Outer certificate paths,
renewal, trust/CSRF settings for NetBox, and the shared ingress configuration belong
to the separate operator deployment. This repository generates none of them.

`--check-tls --ingress-mode external --public-url https://your.fqdn` checks public URL
syntax and optional NetBox CA only. It does not claim the outer certificate is ready.
API and inner nginx health checks prove local readiness; external DNS, chain, hostname,
redirect and SPA/API checks in the runbook are still mandatory acceptance gates.
Use the same NetBox CA bundle at `secrets/ca/netbox-ca.pem`, mounted only into existing
outbound clients. No inbound-ingress change weakens outbound verification or grants.

## Concrete disposable-VM topology

```text
shared host ingress :80/:443 (operator-owned certificates and configuration)
├── netbox-test.indeed-id.hq
│   └── separately deployed NetBox upstream (outside this repository)
└── netbox-sync-test.indeed-id.hq
    └── unix:/opt/netbox-sync/ingress/upstream.sock
        └── NetBox Sync nginx, network_mode: none
            └── private API Unix socket -> API -> private PostgreSQL
```

Both DNS names can resolve to the same acceptance VM. The host ingress routes by
hostname and owns both public certificates. NetBox Sync's public URL remains
`https://netbox-sync-test.indeed-id.hq`; its NetBox base URL is configured through
onboarding as `https://netbox-test.indeed-id.hq`. NetBox remains a separate product:
this repository includes no NetBox service or deployable general-purpose ingress.

## Local upstream verification (trusted operator, after installation)

```sh
sudo stat -c '%u:%g %a %n' /opt/netbox-sync/ingress
sudo test -S /opt/netbox-sync/ingress/upstream.sock
sudo curl --unix-socket /opt/netbox-sync/ingress/upstream.sock \
  --noproxy '*' --fail --silent --show-error --max-time 10 \
  -H 'Host: netbox-sync-test.indeed-id.hq' -H 'X-Forwarded-Proto: https' \
  http://localhost/api/v1/health
sudo python3 /opt/netbox-sync/current/deploy/compose.py ps
```

Expected directory 10001:10001 750, socket present, health success and no Sync published
ports. This local HTTP-over-Unix test is not public HTTPS acceptance and never carries
a token. Wrong/missing Host or scheme must fail; repeat external curl/openssl checks
against the public FQDN after the outer ingress has been separately configured.

## Acceptance evidence

Validated locally with Docker Engine 29.7.2 / Compose v5.5.0, without accessing the
acceptance VM or modifying NetBox. Production Web image manifest:
`sha256:e6d9dc40045c3086c543c78def81ba31bd53e8df1cae98a5c867b633c17f6a31`.

- Full Linux backend suite with disposable PostgreSQL: **811 passed, 8 skipped**.
  Skips were three Compose-CLI checks and three Docker smoke cases (all passed
  separately on the host), live ESXi credentials absent, and legacy naming migration
  cluster absent. No live provider or naming-transition acceptance is claimed.
- Host ingress/Compose unit gates plus Docker smoke: **12 passed, 1 skipped**;
  the Linux-only certificate restore case skipped there passed in the Linux suite.
- Docker smoke covers **three cases**: standalone HTTPS, external/shared HTTPS and
  bundled backup transport. Both ingress cases verify SPA routes, built assets,
  API/static/unknown-route 404, correct Origin, rejected wrong Origin/Host, private-CA
  Bootstrap -> READY and no backend TCP publication. External smoke additionally
  checks no TLS mount/no network/no ports on inner nginx, denial of an unrelated UID,
  wrong forwarded scheme rejection and socket recovery after restart. The outer
  ingress is an ephemeral test fixture only.
- Frontend **48 unit / 134 Playwright passed**; TypeScript and Vite build passed.
- Combined external-ingress + external-PostgreSQL Compose renders successfully.
- Runbook shell blocks parse with `bash -n`; their installation commands were not
  executed. Documentation links and `git diff --check` passed.

Actual shared-ingress configuration, operator certificates, DNS, real NetBox and
Debian/systemd/reboot rehearsal remain operator acceptance steps. No container gains
Docker/systemd control, API DB grants are unchanged and broker stays networkless.
