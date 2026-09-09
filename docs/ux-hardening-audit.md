# UX hardening audit — baseline 36c727d

This is a repository and disposable-browser audit. No VM, real hypervisor or live
credentials are used. Confirmed defects below are distinguished from proposals.
The accepted production probe worker and source-access guidance are retained.

## Priorities before implementation

| Priority | Screen / user problem | Evidence and decision |
|---|---|---|
| P0 dependency | Add Source / public destination rejected; no authorized policy editor | API request_boundary enforces HTTPS/Origin/CSRF and READY but has no authenticated principal or administrative permission. These are not authorization. Do not silently open public egress or implement a client role. Keep inherited env restrictions. Server identity/permission enforcement is a prerequisite for the requested online policy-management workflow. |
| P1 defect | Access check after refresh shows Not checked while VALIDATED permits progress | BootstrapGate maps absent access_checks to not_run yet branches on status alone. Read persisted validation timestamp and explicit evidence; distinguish historical validation from current check and require a fresh complete result before Finish. Backend finish remains authoritative. |
| P1 defect | Language changes disappear on navigation/reload | BootstrapGate and AddSource have separate local state; the main panel is English-only. Introduce one persistent EN/RU preference without remounting forms or storing credentials. |
| P1 defect | Sending versus server execution is ambiguous | Bootstrap uses one generic running message for client submission and persisted VALIDATING/RUNNING. Separate these labels, report uncertainty, never auto-repeat writes, add quiet elapsed time and no synthetic percentage. |
| P1 defect | System health route is missing | SystemHealthPage exists but App does not route to it. Expose it under system navigation and distinguish application readiness from source/run evidence. |
| P2 proposal | Forms/branding differ between setup and panel | Share brand, controls and compact surface/spacing tokens; center bounded forms and preserve table width. Add vector mark, wordmark and favicon variants inspired by the operator concept. |
| P2 investigation | Old form reportedly displayed after update | Dockerfile.web copies a built hashed Vite bundle into /app/web; app serves index/assets with no-store. No service worker is present. This does not establish browser cache as the cause. Record build identity and verify built image/index/bundle, current release and proxy upstream independently; no VM conclusion is possible here. |

## Screen and state map

The following are source-code contracts to preserve and verify with browser scenarios;
not every state is live-backend telemetry.

| Screen | Evidence / action | Failure, recovery and limitations |
|---|---|---|
| Overview | Registered source count, diagnostics snapshot, bounded recent runs; add first source | Independent resource failures preserve other sections; sampled run counts are not global totals. |
| Sources | Search/filter/pagination, source availability, last run, schedule separately | Unknown diagnostic evidence must remain unknown; stale evidence is source/run matched. |
| Add Source | Provider credentials → connection attempt → ephemeral receipt → explicit registration with sync off | Attempt clears form secrets; no receipt survives API restart; registration response loss is uncertain, not automatic retry. |
| Source detail | Summary, configuration, tabs, retained last evidence | Missing source must distinguish unavailable registry from retained tombstone. |
| Discovery / Build plan | Durable source-scoped operation resources, restored by GET on return | Submission is not acceptance; RUNNING is backend evidence; loss of GET blocks mutation until status is recovered. No measurable object total exists. |
| Plan review / confirmation | Full diff, expected/actual, exact digest and separate confirmation | Old/recovered plan requires review; stale-plan fencing and shared apply lock stay server-side. |
| Apply | Explicit confirmation capability and runtime outcome | Partial and unknown outcome differ; no client cancellation or automatic resubmission. Run history is recovery evidence. |
| Schedule | Separate enabled state, interval, revision | Save conflict preserves edits; refresh is explicit; no schedule enable inferred from source registration. |
| Lifecycle | Typed source identity and optional exclusive local-secret cleanup | Durable removal/tombstone keeps identity reservation, runs and NetBox objects; no provider token revocation. |
| Runs / run detail | Bounded cursor history and per-run evidence | Unknown counts/times remain absent; stale sample absence is not completion. |
| Diagnostics | Application components and source-specific evidence | API response alone must not produce integration-wide health; retain snapshot timestamps. |
| System health | Read-only readiness of application/dependencies | Does not prove provider accessibility, data freshness or last sync success. |
| NetBox setup | Persisted configuration, access validation, exact 16-field plan, setup-token lifecycle | Fields may conflict/provision; preserve journal uncertainty; no repeated uncertain POST. Old validation must be clearly labelled. |

## Future roles — design only, no authorization claim

| Capability | Administrator | Operator | Viewer |
|---|---|---|---|
| Read allowed sources and redacted run history | Proposed | Proposed, scoped | Proposed, scoped |
| Add/edit allowed sources | Proposed | Proposed, scoped | No |
| Discovery / plan generation | Proposed | Requires explicit authorization decision | No |
| Apply, scheduling, removal | Requires explicit authorization decision | Not granted by default; decision required | No |
| NetBox/global settings, destination policy | Proposed administrative permission | No by default | No |
| Read stored secrets or raw sensitive logs | No UI capability proposed | No | No |

Each future permission must be enforced by the backend on data and actions. Menu
organization is only information architecture. Completing setup is not a login.
A separate review must define the principal source and permission contract before
online egress-policy writes; LDAPS/full RBAC is not silently introduced here.

## Sources and design rationale

- [NetBox product documentation](https://netboxlabs.com/docs/netbox/): source-of-truth concepts and explicit infrastructure entities.
- [NetBox actual font/theme variables](https://github.com/netbox-community/netbox/blob/main/netbox/project-static/styles/_variables.scss): Inter sans-serif and compact table/button spacing. Adopt principles, not its exact logo or a large library.
- [Inter license](https://github.com/rsms/inter/blob/master/LICENSE.txt): SIL OFL 1.1 permits bundled local font use with copyright/license preservation; no external CDN.
- [PatternFly progress](https://www.patternfly.org/components/progress/): use labelled feedback appropriate to available progress evidence; do not fabricate a determinate percentage.
- [W3C WAI status messages](https://www.w3.org/WAI/WCAG21/Understanding/status-messages.html): status changes are programmatically available without repeatedly moving focus; elapsed-time ticks must not be live-announced.

## Implemented outcome and acceptance evidence

Code commits:
- `97cfca44cc71912b3937857abf74ce3736b90e2d`: safe DNS/address errors across
  API/Unix probe transport; exact allow entries cannot bypass protected service names.
- `417148c0fd2482d8c49ced353ce807c363c13105`: shared EN/RU, language/theme
  persistence, local Inter and brand assets, restored System health route, honest
  operation feedback, historical Bootstrap validation handling and regressions.

| Gate | Observed result |
|---|---|
| Before-change browser baseline | 21 existing UI-hardening scenarios passed at 36c727d; before gallery retained outside checkout |
| Windows backend | 737 passed, 187 skipped; POSIX and opt-in integration gates remain explicit |
| Linux backend, isolated `--network none` runner, checkout read-only | 833 passed, 91 skipped; includes Unix peer credentials, subprocess timeout, Bootstrap/lifecycle and security unit/transport coverage |
| Additional production SPA route regression | 20 passed including newly added `/system` |
| Frontend unit | 56 passed, including translation-key/closed-label coverage and preservation of literal managed values |
| Browser suite | 160 passed in the final full run; two subsequently added DNS/format message scenarios also passed independently |
| TypeScript / Vite | passed; production image rebuilt with local fonts/brand and content identity |
| Real production API → probe-worker → HTTPS/SOAP | 2 passed, bundled and external PostgreSQL; old inline-API network failure reproduced, actual worker path succeeds |
| Production Compose TLS / Bootstrap / SPA | 3 passed: standalone, corporate certificate layout, external shared ingress; actual Compose tmpfs/capabilities/network boundaries retained |
| Whitespace / mirrors | git diff --check passed; sources/ mirrors untouched |

Docker Engine 29.7.2, Compose 5.5.0. Smoke resources were unique local disposable
projects, cleaned by their fixture finalizers. No VM, deployment, push, real provider
or production NetBox interaction took place. The opt-in Docker probe/three TLS cases
were run separately from the Linux suite; do not read its 91 skips as failed tests.
Other skips require explicit PostgreSQL DSNs or unrelated privileged-host/naming/
backup Docker gates; those were not silently enabled. DB/role/naming behavior is not
changed by this task. Two existing FastAPI/httpx deprecation warnings remain.

The first full browser run exposed nine obsolete assertions for the old ambiguous
“Planning in progress / Discovering / Submitting-applying” labels. Their replacements
assert backend-confirmed execution or pending acknowledgement as appropriate. All nine
passed, then the complete suite passed. This is not substituting UI fixtures for runtime
proof: the five Docker gates exercise production transport and Bootstrap separately.

Visual evidence delivered with this review contains 166 retained before/after captures:
full English pages, Russian pages in light/dark at 1440 and 390 pixels, source details,
plans/confirmation, unknown/partial outcomes, empty/failed refresh, removal/tombstone,
slow probe with secret field masked, and full-contract Bootstrap missing/partial/conflict/
success/unconfirmed-token-revocation states. Inspect before/after using the same theme
and width; long-name stress fixtures intentionally produce taller rows. Screenshots are
outside Git; `frontend/e2e` contains their reproducible scenarios. Focus, browser 200%
zoom, reduced motion, source-switch response isolation and preference persistence were
also exercised. This is not a WCAG conformance certification or a live hypervisor claim.

## Remaining explicit limits

- **Online public-destination management is blocked by missing server authorization.**
  No unauthenticated policy reader/writer, automatic public egress, client role or
  env migration was shipped. Existing restrictions are preserved. Authorized online
  management needs a separately reviewed principal/permission contract and policy store.
- Original backend technical evidence (reason text, keys, enum codes, managed field
  values) retains its original representation/language. Surrounding controls and
  closed status/error messages are EN/RU; this is not machine translation of provider data.
- No global discovery/apply total, authoritative completion ETA, source heartbeat,
  cancellation or continuously verified connectivity was invented. Historical elapsed
  time is not proof the worker remains alive; unknown operation status requires recovery.
- The old-UI live report cannot be attributed to browser cache without comparing actual
  release/image/upstream/build metadata. A content fingerprint now makes that comparison
  reviewable. No live systemd/reboot or production upgrade was performed.

For an existing deployment, use the inspected and component-tested [upgrade sequence](source-probe-deployment.md#existing-netbox-sync-test-upgrade-after-review-and-publication):
metadata inventory → supported verified backup → exact reviewed release → same root,
project, public URL and ingress mode → installer → verify current/image/UI fingerprint,
unchanged DB volume/credentials/READY and timer state. Failure is a stop condition,
not permission to regenerate credentials or blindly repeat an immutable release ID.

## Follow-up architectural review of c1e8b1d

See [UI corrections and verification](ux-hardening-review.md) and the [exact 91-skip inventory](linux-skip-inventory.md). These supersede the generic skip explanation above without changing its historical test totals.
