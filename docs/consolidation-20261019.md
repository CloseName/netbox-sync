# Repository consolidation — 19 October 2026

This is a development baseline, not a production release or complete acceptance.
Production was not contacted or changed. Broad refactoring has not started.

## Included local work

- Selectel support evidence, installation outcome and open backlog notes.
- The agreed future-product architecture and corresponding Map decision link.
- Experimental status in README, Selectel UI and selectel-status.md.
- A minimal shared planner correction: return source identity conflicts before
  querying Selectel host matches. Existing conflict tests now pass.
- Test corrections for numeric Selectel account paths, schema evolution, fixed
  hardware observation time, bounded parameter IDs, Linux-only worker execution,
  and counting registration POSTs separately from list GETs.

The early standalone Selectel reconnaissance package, its probe and tests remain
local and were archived before consolidation. They are not an alternative active
collector. Local production inventory remains local. No local work was deleted.

## Validation

Code revision: dfc4cb66f976adb7299f7781a592b895d6161545. Subsequent report-only
changes do not change the tested runtime.

- Windows / Python 3.14: 1687 passed, 485 skipped, no failures. Skips include
  Linux-specific, database and explicitly opt-in integration scenarios; this is
  not proof of Linux deployment or migration acceptance.
- Standalone collector: 102 passed.
- Frontend unit tests: 93 passed. Typecheck and production build passed. Vite
  reports a large output chunk; bundle splitting remains future work.
- Full Playwright attempt: 249 passed and 26 failed before it was stopped during
  repeated stale-scenario timeouts; remaining cases were not run. This was not a
  successful full browser run. The registration POST counter was fixed during
  that run; a separate final run passed that scenario and Selectel onboarding
  (2 passed). Do not add these counts into a claimed complete suite total.
- Earlier GitHub checks at 11a48eb: reconciliation passed, pfSense PHP matrix
  passed; native Selectel integration failed with PERMISSION_DENIED during Region
  creation. New runs for dfc4cb6 remained queued at consolidation time.

## Open verification work before broad refactoring

Keep the native Selectel permission/import and matching failures visible; do not
weaken access or replay guards. See [Selectel status](selectel-status.md).

Refresh browser scenarios against current UI contracts. Confirmed examples include
old overview counters, the former Sources navigation link, an ambiguous status
selector, old registration/catalog controls, and directory-user headings. Other
failures (including disabled plan controls and filtered source visibility) still
need investigation; they are not all proven harmless test-only errors. Preserve
meaningful behavior assertions rather than deleting failing scenarios.

Failed scenarios in the interrupted run (one was subsequently fixed and rechecked):

- e2e\add-source-wizard.spec.ts:177:1 вЂє lost final response checks the actor-bound journal without another registration (1.4s)
- e2e\add-source-wizard.spec.ts:332:1 вЂє malformed lifecycle review does not crash Sources (30.0s)
- e2e\expired-results.spec.ts:3:49 вЂє expired evidence with successful scheduled run operator (5.4s)
- e2e\expired-results.spec.ts:3:49 вЂє expired evidence with successful scheduled run admin (5.5s)
- e2e\foundation.spec.ts:55:1 вЂє direct routes, active navigation, Back/Forward and refresh (5.6s)
- e2e\foundation.spec.ts:132:1 вЂє overview healthy, unknown, stale and partial error preserve epistemic boundaries (5.4s)
- e2e\foundation.spec.ts:151:1 вЂє diagnostics unavailable preserves sources and never labels them healthy (720ms)
- e2e\foundation.spec.ts:180:3 вЂє layout at 1440 (6.2s)
- e2e\foundation.spec.ts:180:3 вЂє layout at 1280 (6.4s)
- e2e\foundation.spec.ts:180:3 вЂє layout at 1024 (6.2s)
- e2e\foundation.spec.ts:180:3 вЂє layout at 768 (6.3s)
- e2e\foundation.spec.ts:217:1 вЂє one source and successful overview (6.0s)
- e2e\foundation.spec.ts:268:1 вЂє loading and empty run history do not flash zero metrics (5.4s)
- e2e\foundation.spec.ts:295:1 вЂє history failure leaves independent overview sections available (5.4s)
- e2e\live-audit-20260921.spec.ts:3:67 вЂє directory users en light (5.4s)
- e2e\live-audit-20260921.spec.ts:3:67 вЂє directory users en dark (5.4s)
- e2e\live-audit-20260921.spec.ts:3:67 вЂє directory users ru light (5.4s)
- e2e\live-audit-20260921.spec.ts:3:67 вЂє directory users ru dark (5.4s)
- e2e\live-audit.spec.ts:62:1 вЂє address policy check sends no credentials and reports success separately from errors (30.1s)
- e2e\requirements-oct8.spec.ts:4:1 вЂє list scope, refresh feedback, modal close controls and teams settings (5.5s)
- e2e\source-placement.spec.ts:54:1 вЂє catalog empty, errors, ambiguity, pagination and keyboard preserve draft (30.0s)
- e2e\source-placement.spec.ts:87:72 вЂє expired ONBOARDING_TOKEN_INVALID preserves placement (6.5s)
- e2e\source-placement.spec.ts:87:72 вЂє expired PROBE_RECEIPT_INVALID preserves placement (6.5s)
- e2e\source-placement.spec.ts:99:1 вЂє unknown registration checks server without another POST (2.0s)
- e2e\source-placement.spec.ts:110:81 вЂє explicit catalog creation CREATED (30.0s)
- e2e\source-placement.spec.ts:110:81 вЂє explicit catalog creation REFUSED (30.0s)
