# Stage 2 validation — 2026-10-19

Runtime revision: `f67d5622b3618ea9986e837feb5cc7d490175310` (main after PR #4).
Stage 2 changes documentation only. No runtime, browser assertions, dependency
versions, deployment configuration or Selectel policy changes are included.

## Local checks

- Windows, Chromium, local Vite and intercepted API fixtures; no live servers.
- Frontend unit tests: 93 passed (`npm test`).
- Typecheck and production build: passed (`npm run build`). Existing Vite warning:
  output JavaScript chunk exceeds 500 kB; no bundle restructuring in this stage.
- Frontend serving and health API: 37 passed, one Starlette deprecation warning
  (`python -m pytest tests/test_frontend_routes.py tests/test_api_health.py -q`).
- The full Python suite was not repeated for documentation-only changes; stage 1
  results are linked from the [verification baseline](verification-baseline.md).

## Triage and next test-maintenance scope

These are findings at the first failing assertion, not proof that all later
assertions in the same scenario will pass after it is repaired.

| Area | Evidence and required follow-up |
| --- | --- |
| Foundation navigation | Sources is an expandable button; Proxmox/ESXi links carry active state. Update selector while preserving Back/Forward, refresh and direct-route assertions. |
| Overview | Old registered/healthy counters and `.overview-summary` were removed. Re-express assertions against current attention, recent-run and schedule sections; retain unknown/stale/error boundaries. |
| Status unavailable | Text occurs both in a filter option and in a source row. Scope assertion to the row instead of making a global ambiguous lookup. |
| Directory users | Old scenarios expect display names as headings. Inspect current row/edit controls, then retain role-change, filtering and failed-sync assertions. |
| Theme/component checks | `#component-api` is inside a collapsed `details` element. Open Component checks before asserting visibility; retain persistence and no-refetch assertions. |
| Narrow navigation and stale evidence | The narrow-navigation journey times out; three stale-evidence scenarios cannot find the expected table badges. Recheck current navigation and source-result rendering while retaining exact source/run matching and keyboard focus guarantees. These scenarios are not yet cleared. |
| Source filters | `requirements-oct8` supplies `site=obsolete`, `schedule=off`, `attention=yes` yet expects Source 001. `querySources` still applies these filters. Decide the intended URL contract explicitly; do not silently change filtering to satisfy this scenario. |
| Registration/catalog/lifecycle | Several scenarios target earlier controls and review headings. Reconcile with current onboarding API/UI, keeping credential clearing, focus, catalog outcomes and no-second-POST guarantees. |
| Expired results | Operator/admin Build plan is disabled. The fixture lacks current prerequisite responses; investigate actual enablement conditions before deciding fixture versus product defect. Viewer restrictions must remain. |
| Light-theme contrast | Control-border/surface-raised ratio is 2.874, below the test's 3.0 threshold. This is not a missing-selector failure. Confirm intended token usage and repair accessibility separately; do not lower the assertion. |

No failing tests are skipped or removed. Selectel matching/import acceptance
remains unresolved independently of mocked browser results. Before stage 3 API/UI
restructuring, maintain the affected scenarios and investigate behavior failures.

## Complete browser inventory

The following inventory is generated from the full Playwright JSON report, using
`npx playwright test --workers=3 --reporter=json` with retries disabled.

Completed: **316 passed, 51 failed, 0 skipped, 0 flaky**.
This is a completed red baseline, not browser acceptance.

- `add-source-wizard.spec.ts:332` — malformed lifecycle review does not crash Sources
- `expired-results.spec.ts:3` — expired evidence with successful scheduled run operator
- `expired-results.spec.ts:3` — expired evidence with successful scheduled run admin
- `foundation.spec.ts:55` — direct routes, active navigation, Back/Forward and refresh
- `foundation.spec.ts:132` — overview healthy, unknown, stale and partial error preserve epistemic boundaries
- `foundation.spec.ts:151` — diagnostics unavailable preserves sources and never labels them healthy
- `foundation.spec.ts:180` — layout at 1440
- `foundation.spec.ts:180` — layout at 1280
- `foundation.spec.ts:180` — layout at 1024
- `foundation.spec.ts:180` — layout at 768
- `foundation.spec.ts:217` — one source and successful overview
- `foundation.spec.ts:268` — loading and empty run history do not flash zero metrics
- `foundation.spec.ts:295` — history failure leaves independent overview sections available
- `live-audit-20260921.spec.ts:3` — directory users en light
- `live-audit-20260921.spec.ts:3` — directory users en dark
- `live-audit-20260921.spec.ts:3` — directory users ru light
- `live-audit-20260921.spec.ts:3` — directory users ru dark
- `live-audit.spec.ts:62` — address policy check sends no credentials and reports success separately from errors
- `requirements-oct8.spec.ts:4` — list scope, refresh feedback, modal close controls and teams settings
- `source-placement.spec.ts:54` — catalog empty, errors, ambiguity, pagination and keyboard preserve draft
- `source-placement.spec.ts:87` — expired ONBOARDING_TOKEN_INVALID preserves placement
- `source-placement.spec.ts:87` — expired PROBE_RECEIPT_INVALID preserves placement
- `source-placement.spec.ts:99` — unknown registration checks server without another POST
- `source-placement.spec.ts:110` — explicit catalog creation CREATED
- `source-placement.spec.ts:110` — explicit catalog creation REFUSED
- `source-placement.spec.ts:110` — explicit catalog creation UNCERTAIN
- `source-placement.spec.ts:110` — explicit catalog creation EXISTS_REVIEW_REQUIRED
- `source-placement.spec.ts:145` — catalog dialog en light 1440
- `source-placement.spec.ts:145` — catalog dialog en light 390
- `source-placement.spec.ts:145` — catalog dialog en dark 1440
- `source-placement.spec.ts:145` — catalog dialog en dark 390
- `source-placement.spec.ts:145` — catalog dialog ru light 1440
- `source-placement.spec.ts:145` — catalog dialog ru light 390
- `source-placement.spec.ts:145` — catalog dialog ru dark 1440
- `source-placement.spec.ts:145` — catalog dialog ru dark 390
- `ui-hardening.spec.ts:332` — themes follow system, persist explicit choice, and do not refetch resources
- `ui-hardening.spec.ts:381` — keyboard operator journey navigates attention, tabs, plan, dialog and result
- `ui-hardening.spec.ts:426` — narrow navigation supports Escape and route focus without trapping sidebar
- `ui-hardening.spec.ts:448` — existing Add Source journey clears credentials, focuses review and links registered source
- `ui-hardening.spec.ts:590` — semantic text and control contrast light
- `ui-hardening.spec.ts:661` — Overview and Sources use exact stale evidence: exact
- `ui-hardening.spec.ts:661` — Overview and Sources use exact stale evidence: foreign source
- `ui-hardening.spec.ts:661` — Overview and Sources use exact stale evidence: unavailable history
- `ui-hardening.spec.ts:712` — Overview editorial ordinary en light 1440
- `ui-hardening.spec.ts:712` — Overview editorial ordinary en light 390
- `ui-hardening.spec.ts:712` — Overview editorial ordinary en dark 1440
- `ui-hardening.spec.ts:712` — Overview editorial ordinary en dark 390
- `ui-hardening.spec.ts:712` — Overview editorial ordinary ru light 1440
- `ui-hardening.spec.ts:712` — Overview editorial ordinary ru light 390
- `ui-hardening.spec.ts:712` — Overview editorial ordinary ru dark 1440
- `ui-hardening.spec.ts:712` — Overview editorial ordinary ru dark 390

Local evidence: `artifacts/refactor-stage2-evidence-20261019.zip` in the task workspace
contains the full JSON report, compact failure summary, error contexts and check logs.
The archive is not committed; this report preserves the portable result inventory.
