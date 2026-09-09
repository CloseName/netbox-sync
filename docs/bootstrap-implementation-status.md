# Bootstrap implementation evidence

Base: `1a4c056f4cc5698455eb50cdf26a997229cadefb` (UI-6). Local implementation and
validation only; no push, deployment, historical VM access or provider mutation.

## Implemented

- Protected atomic server-side Bootstrap state, revision and validation-attempt fencing,
  explicit credential replacement, bounded read-only validation and idempotent Finish.
- First-run gate on all frontend routes and source write API readiness checks;
  `/setup`, recovery/reload, token form clearing and normal navigation after readiness.
- Runtime reads select the appropriate NetBox token from READY state without restarting
  workers. Migration head remains `0005_source_tombstones`; no new database roles.
- Literal broker `network_mode: none`, no DB/env file; separate lifecycle worker retains
  exactly the existing lifecycle_writer privileges, gates, locks and tombstone semantics.
- Installer/examples/Compose and backup staging/quiescence recognize the new services.
- Fixed two bugs exposed by acceptance: broker retry after an already removed file;
  health query selecting an internal column outside existing API role grants. The latter
  was fixed by removing the unnecessary column, not by widening SELECT rights.

See [first-run guide](first-run.md) for state/secret/permission architecture and the
29-item clean-VM acceptance checklist. See existing UI-6 documentation for preserved
operation and removal semantics. A tombstone remains final; cleanup failure does not
authorize automatic resumed deletion or provider revocation.

## Executed checks (2026-09-08)

| Check | Result |
| --- | --- |
| Full backend suite in disposable Linux + PostgreSQL 16 | 778 passed, 4 skipped |
| Separate existing bundled Docker backup/dump/restore transport | 1 passed |
| Frontend unit suite | 48 passed |
| Full Playwright suite | 133 passed |
| TypeScript / Vite production build | Passed |
| Production, external-Postgres and development Compose config | Passed |
| Docker Engine / Compose | 29.7.2 / 5.5.0 |
| Dockerfile.web final build | Passed |
| git diff --check | Passed |

The full backend run includes actual constrained DB roles, migration/grant/idempotency
checks, durable operations/lifecycle, backup/restore, Bootstrap failure/concurrency tests,
real Unix peer checks, control-process restarts and a zero-source process startup.
The startup test provisions roles/migrations, starts broker/bootstrap/lifecycle/discovery/
apply/schedule and API (UID 10001), reads FRESH and empty Sources, confirms degraded
system readiness, and completes a scheduler tick without NetBox/provider credentials.
The full Linux run's opt-in tests are not all enabled; the Docker backup transport was
run separately. Browser tests use controlled API fixtures; no live NetBox permission
or provider acceptance is claimed. Non-failing dependency deprecation warnings remain.

The final Web image manifest was
`sha256:d06ef7b1a13edf7a77be9f9698aeb58a966b3f6ff88c28c6310e4578adf1cd1d`.
In its production Uvicorn/static path, `/`, `/setup`, `/sources`, `/sources/test-source`,
`/sources/add`, `/runs`, `/runs/test-run-id`, `/diagnostics` all returned the built SPA
with HTTP 200. `/unknown-frontend-route`, `/api/unknown-smoke-route`,
`/api/v1/unknown-smoke-route` and `/assets/missing-smoke.js` returned 404.
The referenced built JS and CSS returned 200 with 354568 and 28389 bytes respectively.
No Vite server participated in this Docker smoke.

A separate disposable broker container was inspected running with NetworkMode `none`,
no DSN, `cap_drop: ALL`, no cap_add, read-only image, temporary local secret/socket
filesystems and supplementary group 10001. A UID-10001 socket request reached the
broker's fixed protocol. Separate Linux transport regression proved that this UID
cannot invoke owned-file cleanup, while the lifecycle root peer can, including retry.
A proposed development CHOWN addition was rejected by automatic approval review and
was not applied; the existing group configuration passed without capability expansion.

## Manual/deferred boundaries

The clean Debian/systemd/reboot rehearsal and UI-6 real Proxmox/ESXi acceptance remain
pending on the upcoming explicitly authorized disposable VM. Repository tests do not
replace that acceptance. The original manual prerequisite boundary is being extended by the fixed-contract preparation flow; see [prerequisite contract](prerequisite-contract.md). Its new Docker/Linux evidence is recorded separately in [onboarding verification](onboarding-verification.md); the historical results above do not validate that extension.
Read-only GET/OPTIONS evidence cannot prove every object-level PATCH permission or the
absence of delete rights; operator permission review remains required. LDAPS/RBAC,
automatic certificate issuance and IPv6-only NetBox validation are outside this stage.
The subsequent [DNS/TLS hardening stage](tls.md) adds operator-supplied HTTPS and
explicit NetBox CA trust; use its [clean-install runbook](clean-install-tls-runbook.md).
No production or historical installation was modified.
