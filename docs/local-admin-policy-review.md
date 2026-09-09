# Local administrator / web policy review evidence

Base: main, 897de2a79a6781129f84cbbdcaef9b250795deb7, clean at start.
Existing commits retained. No push, deployment, VM or live-provider connection.
Implementation commits: `afe24aa38bbf4d119cc347c4031ab56ce457f6d0` (server/deployment)
and `2a5ac65fef88c8be1aca0a6f7d08f89fb0de7b7f` (Web UI).

**Implementation prepared for review; release acceptance is incomplete.** The
mandatory full pre-auth installer upgrade gate remains blocked by automatic tool
approval. The exact upgrade runbook is a review candidate, not a passed rehearsal.

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
isolation). Those changes have unit/PostgreSQL/process checks and a rebuilt image;
**a final production Compose rerun is pending alongside the upgrade gate**. Never
present the earlier container pass as a pass on the final committed image.

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
| test_tls_docker (3), auth Compose (2), probe compatibility entrypoint (2) | Auth/probe/Bootstrap runtime is relevant. Five unique runtime cases passed, then expanded auth two passed; final rerun pending after the last hardening. Probe entrypoint now delegates to that authenticated superset, rather than preserving anonymous old calls. |
| test_auth_upgrade_docker (1) | Required. Prepared, not executed: automatic approval blocked Docker socket inside operator harness. |
| test_backup_clean_debian (2), old backup Docker (1) | General old-release/optional-venv gates not rerun. Current auth archive path is covered by expanded Compose and PostgreSQL tests; old privileged systemd test is not claimed as current evidence. |
| test_container_names_docker (2), naming PostgreSQL (1) | Name migration logic is unchanged except registering the new service; not rerun. The additional service is covered in fresh Compose; old-to-new naming transition retains previous evidence only. |
| test_production_proxy_docker (1) | Dedicated tmpfs test not separately rerun. Exact production proxy tmpfs and delivery tested by three TLS scenarios; no test substitution of tmpfs. |
| live ESXi (1) | Intentionally absent: no live hypervisor or VM is authorized. Real controlled HTTPS/SOAP is not full live Discovery privilege validation. |

## Remaining gate and approval boundary

`tests/test_auth_upgrade_docker.py` prepares a unique disposable Debian operator
container and builds the immutable old Git archive 897de2a. It intends to run the
old backup CLI, confirm refusal without enrollment acknowledgment, run the new
installer, verify DB volume/credentials/READY/source/history/schedules, and exercise
root invitation + HTTP enrollment. It is **not executed**.

Automatic approval rejected first a privileged systemd + Docker-socket harness,
then the proposed unprivileged variant because the host Docker socket still grants
broad Docker control. No rejected command executed. The prepared final harness is
unprivileged, uses a unique root/runtime volume and project-scoped cleanup, but
requires separate explicit approval for its Docker socket. Application containers
never mount it. No indirect workaround was used.

After approval, run the upgrade gate and repeat final auth/TLS production smokes
against the final image, fix any actual defects, and update this record before
publication. Actual systemd/reboot remains outside the final unprivileged harness;
unit generation/ordering/shared-lock checks pass, but a real host timer/reboot
rehearsal is not claimed. No downgrade to a pre-auth anonymous API is a safe login
recovery path.

## Visual evidence

EN/RU, light/dark, 1440/390 gallery covers login, invitation form, session expiry,
confirmed auth-service unavailability, access denial, denied public destination
with explicit allow action, and saved policy/revocation. All screenshots use
synthetic data and empty password/invitation fields; no secrets are exposed.
Reproducible tests: frontend/e2e/auth.spec.ts and policy.spec.ts. Native zoom is
covered separately by ui-hardening.spec.ts. External delivered folder:
`netbox-sync-auth-review/index.html` (56 PNGs, no Git binaries).
