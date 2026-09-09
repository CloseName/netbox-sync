# Local administrator / web policy review evidence

Base: main, 897de2a79a6781129f84cbbdcaef9b250795deb7, clean at start.
Existing commits retained. No push, deployment, VM or live-provider connection.
Implementation commits: `afe24aa38bbf4d119cc347c4031ab56ce457f6d0` (server/deployment)
and `2a5ac65fef88c8be1aca0a6f7d08f89fb0de7b7f` (Web UI).

**Mandatory local upgrade and final runtime gates passed on 2026-09-09.**
Prepared implementation is ready for architectural review. Publication and the
operator-executed VM upgrade remain separate steps; neither was performed.
Final regression commit: `45b0678a62485189cbd05293e87c3dd10744bb45`.

## Delivered contract

See [identity, worker, permission map and policy](local-admin-policy.md) and
[the /netbox-sync-test upgrade/enrollment sequence](local-admin-upgrade-runbook.md).
The implemented public-source workflow does not require per-source file edits:
root chooses the managed ceiling once, then the administrator explicitly allows
the exact destination in Add Source and repeats probe/register. Revision and actor
fences are server-owned. No future role/LDAPS implementation was added.

## Completed checks

- Linux full baseline: **848 passed, 98 skipped**, two existing FastAPI/httpx
  deprecation warnings. Read-only checkout in a networkless test container, no
  Docker socket. The skip list is classified below; they are not hidden failures.
- Expanded disposable PostgreSQL/process run: **97 passed, 1 skipped**. Includes
  auth enrollment/CAS races, failed-login persistence, schema 0005 → 0006 with a
  retained source, narrow auth/API/run/schedule/registration grants, all generic
  registry/history/operation/lifecycle integrations, real Unix worker process
  transport, first-run zero-source with actual auth-worker/session, and logical
  backup/restore identity/policy/audit invalidation. Naming migration used a
  different opt-in DB and was not run in this selection. One later pure-policy
  test for a full idempotency window is covered by the final Linux run.
- Frontend node **59 passed**. TypeScript/Vite build passed. Existing React Router
  bundler warnings remain. Full Playwright **194 passed**; after improving actual
  401/403/503 interception and the policy breadcrumb, focused auth/policy gallery
  **16 passed**, repeated successfully after final login styling. Final focused
  auth/API/root-host tests: **14 passed**. `git diff --check` passed.
- Production Compose rendered on host: **3 passed**, proving standalone ports
  80/443, external no published proxy/API/DB ports and networkless broker.
- Docker Engine **29.7.2**, Compose **5.5.0**. Final Dockerfile.web build passed.
  Production transport run **5 passed**: two authenticated bundled/external
  PostgreSQL probe scenarios and standalone/corporate/external TLS + real Bootstrap
  16-field preparation. Actual API → auth/policy → probe → controlled HTTPS/SOAP
  passed, with revision conflict, stale receipt refusal, registration, outage and
  restart. The synthetic public subnet belongs to the disposable fixture; it is
  not an Internet/live hypervisor claim. Provider TLS, DNS failure, timeout,
  wrong password and immutable broker/network/port boundaries are asserted.
- Expanded auth Compose run **2 passed** afterward. Bundled mode additionally
  exercised the standard Debian host CLI create/verify/inspect and fresh restore,
  source/NetBox credentials, READY, source row, current/volume preservation,
  restoration of the pre-backup running-service set, retained identity/rules and
  invalidated restored sessions/invitations. The target retained its own deployment
  identity; no hand-built database-only backup substituted for the product CLI.

The 5 + 2 invocations are not seven distinct test cases. They predate the final
small hardening changes (bounded policy response/idempotency window, graceful auth
termination, host readiness acknowledgment/check and final fixture lock-directory
isolation). Those changes had unit/PostgreSQL/process checks and a rebuilt image. The final
rerun below now validates that image; the earlier passes remain historical evidence.

## Reproduced/fixed validation issues

- Old anonymous endpoint fixtures failed once auth was enforced. Business-screen
  unit/browser fixtures now inject an explicit test identity; production has no
  disable-auth flag. Auth tests and Compose tests use the real service contract.
- Persistent Chromium zoom context bypassed the new test fixture. It now installs
  the same explicit authenticated fixture; native 200% zoom passed in the full run.
- External Compose merged auth networks. Explicit `!override` now selects the
  external-DB network; the real external PostgreSQL transport passed afterward.
- Three old role tests assumed trust authentication and created passwordless roles.
  They now generate test-only passwords and also pass on SCRAM PostgreSQL.
- Old zero-source smoke read Bootstrap anonymously. It now proves health is public,
  Bootstrap is 401 without a session, and FRESH/empty sources are available after
  a real worker-issued session. Machine scheduler still exits successfully without
  any NetBox/provider credentials.
- Policy fixtures initially omitted required Bootstrap fields and used a too-short
  opaque receipt. Correct full contracts pass; validators were not weakened.
- At the idempotency retention bound, revocation remains possible. Old evicted
  requests fail revision fencing instead of executing twice. Oversized policy
  writes are refused before an unreadable state is committed.

## Skip classification for this diff

The previous [91-node inventory](linux-skip-inventory.md) remains the historical
base. Current 98 = that 91 + auth Compose 2 + auth PostgreSQL 3 + auth upgrade 1 +
auth-specific grant 1. These are conditional selections, not 98 unresolved defects.

| Group | Current relationship and evidence |
|---|---|
| Generic PostgreSQL, source/read/history/schedule/operation/lifecycle tests | Relevant due migration and mandatory auth seam; run in the 97-pass selection with dedicated DSNs. Three passwordless-role fixture failures corrected and rerun. |
| Deployment PostgreSQL, auth PostgreSQL, first-run process, backup PostgreSQL | Relevant; run with dedicated disposable databases, including actual negative grants and session revocation after restore. |
| Compose render CLI skips | Relevant; all three rendered on host and passed. |
| test_tls_docker (3), auth Compose (2), probe compatibility entrypoint (2) | Auth/probe/Bootstrap runtime is relevant. Five unique runtime cases passed, then expanded auth two passed; final rerun of all five cases passed after the last hardening, including runtime session expiry/revocation. Probe entrypoint now delegates to that authenticated superset, rather than preserving anonymous old calls. |
| test_auth_upgrade_docker (1) | Required; now passed twice, with the final expanded case checking old backup verify/inspect and inherited non-default allow/deny rules. |
| test_backup_clean_debian (2), old backup Docker (1) | General old-release/optional-venv gates not rerun. Current auth archive path is covered by expanded Compose and PostgreSQL tests; old privileged systemd test is not claimed as current evidence. |
| test_container_names_docker (2), naming PostgreSQL (1) | Name migration logic is unchanged except registering the new service; not rerun. The additional service is covered in fresh Compose; old-to-new naming transition retains previous evidence only. |
| test_production_proxy_docker (1) | Dedicated tmpfs test not separately rerun. Exact production proxy tmpfs and delivery tested by three TLS scenarios; no test substitution of tmpfs. |
| live ESXi (1) | Intentionally absent: no live hypervisor or VM is authorized. Real controlled HTTPS/SOAP is not full live Discovery privilege validation. |

## Final authorized acceptance run - 2026-09-09

The user explicitly approved a temporary **unprivileged** operator container with
Docker socket access for isolated local resources. Prior automatic rejections of
privileged/systemd and unapproved socket variants remain historical; those rejected
commands did not execute. The approved tests ran without `--privileged` or host
systemd control. No product Compose service acquired a Docker socket mount.

- **Upgrade: 1 passed, 59.45 s** in the final expanded run (initial run: 1 passed,
  121.74 s). Real old Git archive `897de2a79a6781129f84cbbdcaef9b250795deb7`
  was built and installed in Debian 12. The installed old host CLI performed
  create/verify/inspect before activation. The installer refused missing enrollment
  acknowledgment without changing current/config/secrets, then upgraded with the
  acknowledgment. Migration 0005 -> 0006, identical source/history rows, schedule
  settings, protected credentials, READY, PostgreSQL container and volume mounts
  were asserted. Non-default allowed CIDRs/hosts and denied CIDRs were copied from
  the old API baseline to auth.env. Root-only file invitation, anonymous 401,
  HTTP enrollment and explicit managed-policy transition passed.
- **Final production Compose: 5 passed, 273.44 s.** Bundled and external PostgreSQL
  plus standalone/corporate/external ingress, using actual production Compose files
  and the rebuilt product image. Bundled mode includes full host backup/verify/
  inspect/fresh restore. Both DB modes assert real HTTP login, idle and absolute
  session expiration (controlled fixture DB timestamps, unchanged product limits),
  root revocation, fresh login, logout, outage 503 and policy/session persistence
  across worker restart. Policy changes do not recreate containers or edit config/
  secrets. All three TLS modes exercise the complete 16-field Bootstrap workflow,
  concurrent fencing, conflict/provisioning stop, lost-response reconciliation,
  restart, confirmed/unconfirmed temporary-token revocation and secret non-retention.
- **Focused Linux: 101 passed, 1 skipped**, two existing deprecation warnings.
  Auth policy/API/root CLI, installer and backup suites. The sole skip is Docker
  CLI rendering inside the deliberately socketless test image; the same test was
  executed on the host afterward: **1 passed**. No unresolved skip in this selection.
- Docker Engine **29.7.2 Linux**, host Compose **5.5.0**. Product image:
  `sha256:ba4e2a70855b5e316773baa46369b1fd8d9f98f634ab654295948fddea59d2fb`.
  This continuation changed only test harnesses/evidence, not product code or UI.
  Prior frontend/TypeScript/Vite/Playwright evidence therefore remains applicable.
  `git diff --check` passed.

Each operator host, helper and volume now has an exact project ownership label;
Compose resources retain their own unique project labels. Cleanup selects these
labels, not arbitrary container/volume names. External fixture DB storage is
explicitly labeled. TLS cleanup verifies ownership, and DB readiness waits for the
final TCP listener rather than PostgreSQL's temporary initialization socket.
Final metadata inventory found no remaining containers, volumes or networks for
these smoke projects and no temporary old-release image tags. Existing unrelated
rehearsal resources were left intact. Reusable review/test images are retained.

Repeat only with the same explicit operator-socket authorization and prepared
local review/test images (Docker-capable Debian harnesses; no production values):

```sh
NETBOX_SYNC_AUTH_UPGRADE_TEST=1 python -m pytest -q tests/test_auth_upgrade_docker.py
NETBOX_SYNC_AUTH_DOCKER_TEST=1 NETBOX_SYNC_TLS_DOCKER_TEST=1 \
  NETBOX_SYNC_TLS_TEST_IMAGE=netbox-sync-auth:review \
  NETBOX_SYNC_TLS_RUNNER_IMAGE=netbox-sync-auth-tests:review \
  python -m pytest -q tests/test_auth_compose_docker.py tests/test_tls_docker.py
```

**Limits:** the real installer ran with `--no-systemd` in the unprivileged harness.
Unit generation/ordering/shared-lock tests passed, but a real host timer/reboot
rehearsal is not claimed. The live runbook uses the normal systemd path and requires
operator checks. External PostgreSQL transport is covered; the immutable old -> new
installer rehearsal specifically covers bundled PostgreSQL/external ingress.
No live hypervisor or VM was contacted. Do not downgrade to a pre-auth anonymous API
as a login recovery method. No mandatory local acceptance gate remains open.

## Visual evidence

EN/RU, light/dark, 1440/390 gallery covers login, invitation form, session expiry,
confirmed auth-service unavailability, access denial, denied public destination
with explicit allow action, and saved policy/revocation. All screenshots use
synthetic data and empty password/invitation fields; no secrets are exposed.
Reproducible tests: frontend/e2e/auth.spec.ts and policy.spec.ts. Native zoom is
covered separately by ui-hardening.spec.ts. External delivered folder:
`netbox-sync-auth-review/index.html` (56 PNGs, no Git binaries).
