# Browser contract maintenance — 2026-10-19

Starts from main `0f74ac1c89905dcadbf5880f27e98f7cd05d3281`, after merging PR #5.
Runtime source, styles, dependency versions and deployment configuration are
unchanged. Selectel remains experimental. All requests use local browser fixtures.

## Preserved checks with current journeys

- Provider navigation retains active-state, direct-route, Back/Forward and reload
  coverage. Narrow navigation still checks Escape and keyboard focus.
- Overview checks current attention, run and schedule sections in place of removed
  summary counters. Unknown/loading and failed refresh are still explicit; the
  loading fixture releases all concurrent source reads, including sidebar reads.
- Directory role changes use Change role and explicit Save role, then verify the
  persisted role. Filtering and failed directory synchronization still preserve
  the last successful data in English/Russian and both themes.
- Connection checks and diagnostic component details are opened before use.
- Malformed lifecycle review is exercised in existing-source configuration, where
  that feature now lives, and must not crash the screen.
- Catalog lookup checks still cover empty results, denied access, network failure,
  ambiguity, pagination, keyboard selection and zoom. The site control now uses
  its current Placement site label.
- Explicit catalog creation is tested through Edit placement for an existing
  source, not the automatic onboarding wizard. CREATED, REFUSED, UNCERTAIN and
  EXISTS_REVIEW_REQUIRED outcomes retain token clearing and single-write checks.
  Creating/selecting a catalog object must not automatically save source placement.
- Lost registration responses count only POSTs; read-only status and navigation
  requests do not count as duplicate registrations. Expired credentials preserve
  the non-secret draft and site selection.
- Stale-run fixtures no longer mark the local source stale while claiming that
  only a foreign source has stale evidence. Exact-source matching and unavailable
  history boundaries remain asserted in both Overview and Sources.

No test is removed, skipped or converted to an expected failure. Product findings
are documented [separately](browser-product-findings-20261019.md), with reproduction
and the relevant runtime boundary; assertions are not weakened to conceal them.

## Validation

- Registration and placement focused run: 62 passed, no failures or skips.
- Frontend unit tests: 93 passed.
- `npm run build`: typecheck and production build passed; existing large-chunk
  warning remains.
- Full-suite results are recorded below. Counts from focused runs are not added
  to full-suite totals.

One exploratory run timed out waiting for a heading in the Russian light-theme
gallery. It subsequently passed in both the complete run and a single-worker
focused run without changing that scenario or enabling retries. The initial JSON
is retained in the evidence archive; this is not enough evidence to claim a
diagnosed or fixed intermittent rendering issue.

Final complete Chromium run: **366 passed, 1 failed, 0 skipped, 0 flaky**.
Command: `npx playwright test --workers=3 --reporter=json`; retries disabled.

Remaining failure: `ui-hardening.spec.ts:591` — semantic text and control contrast light.

This is not a fully green browser acceptance. Keep the remaining product defect
visible and resolve it in a separate visual change before claiming full acceptance.
The prior 51-failure baseline remains in the stage 2 report.

Local evidence is archived in `artifacts/browser-maintenance-evidence-20261019.zip`
in the task workspace (raw reports, failure summary, error contexts, unit/build logs).
