# LDAPS/RBAC — local validation evidence

Base main: `5acd4c12d62c62072049b22f98e22d19a980a5af`, initially clean.
Implementation and local gates completed. No push, deployment, live AD/hypervisor
or VM connection was performed. Microsoft AD acceptance remains open.

## Implemented boundary

- Auth-worker owns fixed Viewer/Operator/Admin authorization and directory sessions.
  Every API route requires an explicit permission; Origin and onboarding are not roles.
- Only auth-worker receives the LDAP egress bridge and read-only bind-file mount.
  A dedicated root-peer broker socket accepts create-only immutable secret writes.
  Broker stays literal network_mode none; API/DB and sync workers receive neither
  LDAP network nor bind files. No product Docker socket or published API/DB ports.
- Verified CA/hostname LDAPS; escaped filters, no referrals, bounded subprocess and
  operation deadlines, direct-group mapping and stable directory identity.
- Reads revalidate within 30 seconds; writes always revalidate. Prepare/apply checks
  permissions again and binds confirmation to actor. Already admitted operations
  finish independently. Local emergency login remains during directory outage.
- Installer generates protected auth directory; backup binds active LDAP reference
  to archived files; restore retains configuration/CA while invalidating sessions
  and check proofs. Existing grants and shared apply lock are unchanged.

## Executed checks

| Gate | Result |
| --- | --- |
| Full Linux backend with disposable PostgreSQL | 1063 passed, 27 skips classified below |
| Extra real LDAPS/protocol and authorization, including secret-socket rejection | 26 passed |
| Dedicated PostgreSQL grants | 5 passed |
| Dedicated logical DB backup/restore | 1 passed |
| Bundled production LDAP + actual host CLI backup/create/verify/inspect/fresh restore | 1 passed |
| Exact 5acd4c12 Debian upgrade, then second upgrade with configured LDAP | 1 passed |
| Production workers + real browser + scheduled ESXi/Proxmox, bundled/external DB | 2 passed |
| Actual production TLS Compose standalone/corporate/external + deployment/ingress | 50 passed, 4 Windows skips covered in Linux |
| Frontend unit | 67 passed |
| Complete Playwright suite, EN/RU/light/dark/narrow/zoom | 238 passed |
| TypeScript, Vite, image build, Compose model, git diff --check | passed |

Runtime worker gates exercise API connection/preview/discovery, nonempty plan,
prepare/apply, created objects and unchanged repeat plan, both providers on HTTPS
8443. Proxmox includes VM/LXC. Actual scheduler follows manual apply and proves
no-op plus correlated required-read refusal and recovery on a later explicit tick.
Mapping CAS, stale-plan invalidation and populated upgrade also pass.

Real LDAPS Settings/test/save and login run through production API/auth-worker and
broker, not mocked HTTP. Tests cover role controls, group removal/account disable,
CA/hostname failure, concurrent save, secret modes/read-only mount, runtime restart,
and emergency access during directory outage. Backup restores actual LDAP login
with retained CA/bind file; old sessions fail. Upgrade retains old local identity,
session, source/schedule/history, READY, credentials, policy and same DB container/
volume. Second upgrade retains LDAP settings and immutable files.

## Defects and test corrections found during validation

- Direct production `/settings` returned 404 despite React/Vite working. Added
  the backend SPA route and production route regression; real browser now passes.
- Browser logout originally revoked the harness's shared local session. Browser
  now receives its own real login, leaving subsequent checks independent.
- One upgrade attempt failed during preparation with a generic installer error.
  Concurrent generated evidence was an uncontrolled source input. Harness now
  freezes release input and repeat passes; the original exception was not captured,
  so source mutation remains a hypothesis, not a proven product defect.
- Updated a revalidation test double to accept the new actor argument; final full
  backend rerun passes. No permission or stale-plan checks were relaxed.

## Reproduction and artifacts

Use `tests/Dockerfile.ldap` for isolated real OpenLDAP protocol tests. Production
image: `netbox-sync-auth:review`. Runtime opt-ins: NETBOX_SYNC_AUTH_DOCKER_TEST=1,
NETBOX_SYNC_LDAP_COMPOSE_TEST=1; add NETBOX_SYNC_WORKER_FULL_SYNC_TEST=1 and
NETBOX_SYNC_BROWSER_FULL_SYNC_TEST=1 for full workers. Upgrade opt-in:
NETBOX_SYNC_LDAP_UPGRADE_TEST=1. TLS: NETBOX_SYNC_TLS_DOCKER_TEST=1.
Run auth Compose harness instances sequentially (controlled fixed fixture subnet).
Each uses unique ownership labels; cleanup is limited to those resources. Temporary
operator harness alone uses Docker socket, without privileged. Product does not.

Screenshots generated in frontend/test-results: production-ldap-settings.png,
production-ldap-{viewer,operator,admin}.png and ldap-saved/roles EN/RU themes/widths.
Production settings and narrow RU/dark screenshots were visually inspected; password
fields are empty, no secret values are captured. Test images are retained locally;
no labeled test containers remained after completed cleanup.

## Classification of full-suite skips

| Group | Skips | Coverage/status |
| --- | ---: | --- |
| auth Compose | 2 | Both PostgreSQL modes passed separately with full worker/browser gate. |
| pre-auth upgrade | 1 | Unchanged old migration stage; exact current 5acd upgrade passed separately. |
| clean Debian host | 2 | Nonprivileged real CLI covered in Compose gate; privileged systemd host not run. |
| backup Docker | 1 | Actual CLI create/verify/inspect/fresh restore covered in LDAP Compose gate. |
| backup PostgreSQL | 1 | Separate dedicated DB passed. |
| container names | 2 | Unchanged naming code; upgrade proves existing DB identity/volume retention. |
| deployment foundation Docker CLI | 1 | Host Compose validation passed. |
| deployment PostgreSQL | 6 | Dedicated cluster passed all 5 test functions (helper generated 6 skip records). |
| live ESXi | 1 | Not authorized; isolated HTTPS/SOAP fixture used. |
| external ingress Docker CLI | 2 | Host Compose/TLS regression passed. |
| LDAP upgrade | 1 | Separate exact-base runtime passed. |
| naming migration PostgreSQL | 1 | Unchanged historical naming migration, not repeated. |
| probe Compose | 2 | Covered by extended actual auth Compose HTTPS/SOAP journey. |
| production proxy | 1 | Same real Compose proxy exercised by all 3 TLS modes. |
| TLS Docker | 3 | Standalone/corporate/external passed separately. |

The host 50-test run skipped four POSIX-specific metadata/symlink tests on Windows;
they passed in the full Linux run. No UI mock is counted as a production worker test.

## Remaining acceptance limits

- Real Microsoft AD: actual schema/ACLs, objectGUID, account lock/expiry/disable,
  direct groups and CA chain must be accepted with operator-supplied accounts.
  OpenLDAP emulates required AD attributes; it is not AD interoperability proof.
- Direct groups only; nested/primary groups are not expanded. Account-state
  attributes not returned by directory ACLs cannot all be independently observed.
- LDAP bridge is not a destination firewall; use operator network rules if required.
- Debian upgrade harness is nonprivileged and uses --no-systemd. Actual host
  systemd/reboot and clean-deployment rehearsal remain separate operator acceptance.
- Immutable unreferenced bind files are retained, not automatically garbage-collected.
- Vite reports the existing >500 kB bundle warning; Python dependencies emit
  deprecation warnings. Neither caused test failures.

See [architecture](ldaps-rbac.md), [upgrade runbook](ldaps-upgrade-runbook.md),
and [backup contract](backup-restore.md). No claim of production AD acceptance.
