# Source sync review — historical checkpoints

Current local acceptance: [source-sync-acceptance.md](source-sync-acceptance.md). The entries below are historical intermediate evidence; their pending/blocked labels are superseded by that final record.

Base: `9140682652cf8dd3e65d4ed0fb2485a91ae9f7cf`. No push, deployment, live VM or hypervisor access has occurred.

## Confirmed defect and current correction

The Proxmox empty-target regression failed before the correction in `VMNetworkApplyError`: the global preflight checked VM networking before the new VM existed, including in the planning facade. The preflight now simulates the complete dependency chain on an isolated nested PlanningNetBox. Only a successful complete preflight permits the real executor phase. This explains a reproduced code defect; it is not proof that it was the only cause of the operator's live failure.

ESXi now includes new stable-identity hosts and VMs in the supported metadata/VM-network creation path while retaining explicit legacy-adoption boundaries. Host VMkernel/vSwitch networking remains unsupported/report-only. Controlled real-pynetbox HTTP tests cover Proxmox host + VM + LXC and ESXi host + VM, plan without writes, explicit apply and a repeated plan without duplicate creation. They are not live NetBox/hypervisor or production-worker end-to-end proof.

Safe diagnostics use closed error codes and allowlisted repository frame locations. Exception text, local variables and stderr are not forwarded. Operation UUIDs correlate durable failures. The HTTP timeout contract remains 504. Further error-family coverage remains part of final hardening.

## Current Linux evidence (2026-09-10)

Docker Engine 29.7.2, Linux; Compose 5.5.0.

- Full backend with a unique internal test network and PostgreSQL in tmpfs: **956 passed, 26 skipped**, two dependency deprecation warnings.
- Subsequent name/CSRF/auth route regressions: **14 passed**.
- Separate dedicated PostgreSQL deployment/grants suite: **5 passed**. Lifecycle UPDATE(name) is allowed; web_reader and registration_writer UPDATE(name) remain denied.
- Production Compose auth/probe tests (bundled/external PostgreSQL) plus actual external proxy tmpfs smoke: **3 passed**. This image preceded the final rename/UI changes; the final release image must be rebuilt and tested again.
- Frontend unit suite: **66 passed**; TypeScript and Vite build passed. Vite warns about the main bundle exceeding 500 kB.
- Placement browser suite (including catalog creation/refusal/uncertainty): **21 passed**, including EN/RU, themes, narrow display, catalog failures, session/receipt expiry and uncertain registration without repeated POST.
- Source name/removal browser suite: **5 passed**, including exact case, stable ID, conflict and active-operation blocking.
- The loading browser test verifies changing computed transform with no-preference and no animation under reduced motion.

All temporary runtime resources were scoped by unique test labels and cleaned by those labels. Product containers receive no Docker socket. No global host Python packages were installed. Host API test execution lacks argon2; those tests were executed successfully in the prepared Linux runner instead.

## The 26 skips in the full Linux run

| File/group | Count | Reason / separate evidence |
|---|---:|---|
| test_auth_compose_docker.py | 2 | Docker opt-in; both passed separately |
| test_probe_compose_docker.py | 2 | Delegates to the same auth/probe scenario; covered by the two runs above |
| test_production_proxy_docker.py | 1 | Docker opt-in; passed separately |
| test_deployment_postgres.py and its imported fixture test | 6 | Separate DB name/user required; deployment module's five cases passed separately; imported registry case covered by main PostgreSQL suite |
| test_deployment_foundation.py, test_external_ingress.py | 3 | Docker CLI absent inside networkless runner; host Compose model checks remain to be run for final diff |
| test_auth_upgrade_docker.py | 1 | Separate operator-container opt-in; final upgrade rehearsal still required |
| test_backup_clean_debian.py | 2 | Explicit clean Debian/privileged fixture opt-ins; not enabled in general runner |
| test_backup_restore_docker.py | 1 | Separate Docker fixture opt-in; final update/backup coverage pending |
| test_backup_restore_postgres.py | 1 | Dedicated backup DB DSN not configured |
| test_container_names_docker.py | 2 | Independent naming migration Docker opt-in; naming code unchanged |
| test_naming_migration_postgres.py | 1 | Dedicated naming migration DSN; naming code unchanged |
| test_tls_docker.py | 3 | Separate Docker TLS opt-in; final standalone/external smoke pending |
| test_esxi_live.py | 1 | Live connection deliberately unavailable and prohibited |

The earlier general run without a PostgreSQL DSN had 99 skips; adding the isolated DB removed 73. It also exposed the HTTP timeout regression and exact-envelope assertions, now corrected. One install preparation test failed while browser artifacts were being recreated in the shared checkout; its independent rerun and subsequent complete PostgreSQL run passed. Do not treat concurrently changing checkout artifacts as an immutable release input.

## Name/removal contract

PATCH `/api/v1/sources/{stable-id}/name` requires server permission `source.configure`, same-origin write protection and an exact lifecycle revision. The lifecycle worker updates only the name column under the existing shared apply/source locks. Existing source fingerprints bind the name and cause old plans to fail revalidation. The API gains no DB write capability.

Removal uses the stable source route and the exact current display name, case-sensitive, validated after the revision check under the existing locks. A rename invalidates an earlier removal confirmation. Tombstones, historical runs, NetBox objects and exclusive/shared credential cleanup semantics remain unchanged.

## Outstanding acceptance work

This is not a supported upgrade candidate yet. Do not publish or install this checkout.

- Finish catalog creation model/dependency coverage and visual review. The mechanism, HTTPS tests and production API/worker restart reconciliation now pass; see the evidence below.
- Complete the placement/per-host mapping editor with current discovery evidence and stale-plan invalidation.
- Complete configurable HTTPS port across receipt, preview, plan and runtime. Automatic permission review rejected this edit twice; the separate user confirmation is pending. No port implementation has been applied.
- Complete final copy/layout review. Standalone cluster suggestions now show the discovered name used and remain editable.
- Prove full plan/apply and update preservation through production Compose workers, including partial/unknown outcomes and all final security checks.
- Rebuild final image, finish browser screenshots, final test/skip audit, update the upgrade runbook and make focused commits only with explicit remaining limitations.

Existing commits and all prepared changes have been preserved. The current work remains uncommitted pending completion of these gates.


## Catalog creation verification (2026-09-10, prepared checkout)

- Linux catalog journal/HTTPS, real-pynetbox first-sync, catalog validation and auth routes: **39 passed**, two dependency deprecation warnings.
- Browser placement: **21 passed**, including four explicit catalog outcomes. The initial accessible Slug label failure was corrected; the entire placement file then passed.
- Dockerfile.web rebuilt successfully: local `netbox-sync-auth:review`, image ID `sha256:ba7b2634331059b7bcf2e76d81a7dd7107db19602cc2ae2fbf15c7e305420bcf`. TypeScript/Vite passed inside the build; the 517.43 kB main bundle warning remains.
- Actual production Compose auth/probe scenario with bundled and external PostgreSQL: **2 passed in 167.72 s**. Added API → bootstrap worker → HTTPS catalog writes using a separate temporary token, read-token write refusal, idempotent intent, lost response and reconciliation after bootstrap-worker restart. This does not replace the outstanding full plan/apply production-worker gate.
- Concurrency retains existing nonblocking locks. Confirmed pre-POST lock refusal is `CATALOG_BUSY` (409); transport uncertainty is not reclassified as a definite refusal. Parallel identical intents produce at most one POST; later requests resolve to the durable journal.
- A failed durable journal write prevents child launch. Unsafe journal permissions fail closed. Temporary write/read tokens are absent from journal and public output assertions.

No push/deployment/live connections. The broader task is still incomplete; no final upgrade recommendation or completed-task commit is implied by these intermediate results.


## Latest checkpoint after Docker became available

- Full Linux backend with isolated PostgreSQL: **985 passed, 26 skipped**, two dependency deprecation warnings, 78.46 s. The skip classification above still applies. The prior run's sole failure was the exact Discovery envelope assertion after adding bounded `hosts`; the assertion was updated and secret-bearing/oversized host projections were additionally rejected in regression tests.
- Full Playwright: **226 passed**, 4.0 min. This includes all 29 placement/catalog cases, EN/RU, light/dark, narrow viewport and 200% CSS zoom.
- Frontend unit: **66 passed**; TypeScript/Vite passed, main bundle 517.48 kB warning retained.
- Six catalog models and their dependencies are exercised through controlled HTTPS: catalog suite **22 passed**. Existing NetBox rows are never silently selected after a lost response.
- ESXi client now retains only the classified DNS/TLS/timeout code through its safe wrapper: client/diagnostic subset **53 passed**.
- Fixed two additional browser defects: a delayed suggestion could overwrite a newly created explicit selection; and viewport-unit modal limits could put controls out of reach at 200% CSS zoom. Delayed-response and zoom regressions now pass.
- `git diff --check` passed; branch `main`, HEAD remains `9140682652cf8dd3e65d4ed0fb2485a91ae9f7cf`. No new commits, push, deployment or live connections. `sources/` unchanged.

The production image/Compose evidence above precedes the latest ESXi diagnostic, Discovery host projection and modal-race corrections. Rebuild and repeat affected production gates after integrating the remaining work; do not present the earlier image as proof of the final checkout.

### Explicit approval blockers

Automatic approval review rejected the configurable HTTPS-port changes twice; no such implementation was applied. The separate confirmation question remains pending.

Automatic approval review also rejected connecting the placement editor across API/lifecycle protocol and persistent DB grants. That command did not execute. `placement_control.py` is a prepared, unconnected prototype, not an enabled or accepted feature. The bounded Discovery host projection is tested, but neither placement routes nor placement privileges were added. The pending question requests narrowly scoped lifecycle-worker placement updates and PLAN invalidation, with no API DB writer, credentials, NetBox egress or lock changes.

These approvals do not substitute for the remaining full production-worker plan/apply and upgrade-preservation tests. The overall task is **not complete** and the checkout is **not ready for publication or installation**. Retain the prepared changes; no reset/clean or partial release activation.

Screenshots from the complete browser run were copied to the unique local directory `C:/Users/2BA0~1/AppData/Local/Temp/netbox-sync-review-gallery-0407bf5f397f474c81391b2e23579144` (28 placement/catalog PNGs). Dialog screenshots contain empty token inputs. This is local evidence, not a portable release artifact.


## Resumed checkout checkpoint — 2026-09-15

Work resumed in `E:/Codex/Project/netbox-sync` by explicit user authorization. HEAD remains `9140682652cf8dd3e65d4ed0fb2485a91ae9f7cf`; the old `infra-netbox-sync` checkout was left untouched. The historical approval-pending notes above are superseded: port and placement integration are now authorized and implemented in the prepared tree. They still require the remaining acceptance work below.

Prepared changes:
- Explicit strict integer HTTPS port (1–65535), provider defaults for old sources, receipt binding, persisted `settings.api_port`, probe/preview/Proxmox and ESXi runtime clients, and EN/RU wizard input.
- Placement read/save through lifecycle Unix RPC with server `source.configure`, existing catalog validation, lifecycle revision and Discovery fencing, shared apply/source locks, retained absent-host mappings, and invalidation of READY plans. API gets no DB writer; lifecycle receives only the required additional column updates.
- Configuration-tab placement editor uses the shared selectors, hides identity/name/schedule editing, requires explicit review, and does not automatically repeat an uncertain save.

Newly executed evidence:
- Docker production image build succeeded (`netbox-sync-auth:review`, image manifest list `sha256:3f421631c612f4ac2edf9927b14298e1d781722046f617823d343b80514d975b`). TypeScript/Vite passed; 521.88 kB bundle warning remains.
- Actual production Compose bundled/external auth/probe plus proxy smoke: **3 passed**, 240.34 s. This exercises the existing controlled SOAP/catalog scenarios and component upgrade/backup/restore; it is not the full provider inventory plan/apply gate.
- Old pre-auth `897de2a` to prepared image upgrade: **1 passed**, 125.27 s. Real installer, pre-upgrade backup/verify/inspect, retained source/history/credentials/READY/policy and PostgreSQL volume, explicit enrollment. No systemd/reboot proof.
- New placement plus existing lifecycle PostgreSQL tests: **18 passed**. Separate deployment/grants suite: **5 passed**.
- Initial port/onboarding/first-sync/client/config subset: **95 passed**. Receipt/API subset: **58 passed**.
- Full Linux backend: **995 passed, 3 failed, 26 skipped**. All three failures were diagnostic test doubles missing the new `api_port` contract, preventing injected DNS/TLS/timeout exceptions from being reached. Fixture corrected; diagnostic/ESXi/port subset then **64 passed**. Do not report an all-green full-suite rerun: none has yet been performed after this fixture-only correction.
- Frontend unit **66 passed**, TypeScript/Vite passed.
- Browser source-detail/source-placement **57 passed, 1 failed**; the new mapping test opened Overview instead of Configuration. Route corrected and targeted rerun **1 passed**. Existing 57 include EN/RU, themes, narrow viewport, session/receipt expiry and catalog outcomes.
- `git diff --check` passed before this documentation checkpoint.

The 26-skip inventory above still describes the general runner. Upgrade and the three Compose cases are now separately executed; the five deployment cases are also separately executed. Live ESXi remains prohibited; dedicated standalone TLS/naming/backup-specific opt-ins and final full worker coverage must not be implied by these results.

A production-image build attempt was rejected before execution because the automatic approval service returned HTTP 403 Forbidden. After the user's explicit retry request, the same reviewed command succeeded. This is not a current authorization blocker.

Still required before completion/commits/publication recommendation:
- Full ESXi and Proxmox provider inventory → production worker plan → confirmed apply → repeated plan, including partial/uncertain outcomes. Existing real-pynetbox HTTP first-sync tests are narrower evidence.
- Real non-default provider HTTPS-port scenario through production transport and saved runtime configuration; current evidence is implementation plus unit/receipt tests.
- Placement API/worker runtime acceptance, permission denial/concurrency/uncertainty and final visual/error-copy hardening, including bounded response validation.
- Final full verification, current screenshots, upgrade runbook and focused commits. No new commits or push/deployment/live connections in this checkpoint.

The locally reproduced Proxmox dependency-preflight defect remains distinct from the operator's original live failure; the latter is not proven resolved.
