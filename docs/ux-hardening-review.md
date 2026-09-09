# UI follow-up review of c1e8b1d

Review date: 2026-09-09. Starting branch main; HEAD c1e8b1df8503bb617c621fcf412a134e1aabd1ca, clean before this review. Existing commits preserved; no backend, migrations, grants, Compose or host installation changes. No VM, push or deployment.

## Corrections

OperationFeedback distinguishes acknowledgement pending, RUNNING (“Operation in progress” / “Операция выполняется”), completion, and unknown outcome. Unknown is not labelled connection lost. A completed/uncertain state has no running spinner or growing elapsed counter. Existing Plan-ready, Discovery-result and Apply outcome displays remain authoritative; no synthetic completion is inferred.

Operation requests retain a closed failure category: timeout, transport (no response), HTTP 401/403, other HTTP error, invalid response, unknown failure. Timeout during body consumption is also recognized. HTTP response bodies and exception text are discarded. “No response received” is evidence, not a claim about DNS or a disconnected network. A valid Origin/CSRF request can still be denied; UI does not diagnose the reason for 403 beyond denied access.

Browser regressions make a confirmed running operation lose status visibility via 403, 503, malformed JSON or aborted transport, in EN and RU. The confirmed cause and unknown outcome appear together; remote sentinel does not appear. Restoring the read and reloading reveals the same completed operation, with exactly one start POST. Unit coverage adds timeouts before/after headers and foreign/malformed state. Durable server logic, revision/digest checks and shared lock are untouched.

Overview primary copy is shorter. “Next scheduled runs” / “Ближайшие запуски” names the entity. Count limits, recorded-not-live status, snapshot connectivity limitation and the five-estimate schedule boundary remain visible secondary explanations. Exact stale source/run joins and failed-refresh handling remain tested. Normal gallery uses three ordinary source names and a future forecast, separately from long-name and old-evidence stress scenarios.

## Verification

- Linux baseline reproduced: **834 passed, 91 skipped**. Every skip is classified in [the inventory](linux-skip-inventory.md), including all node IDs and reasons. Two existing FastAPI/httpx deprecation warnings.
- Relevant Linux/PostgreSQL + real Unix worker transport: **18 passed** (17 previously skipped nodes + one ordinary case). No public DB port, persistent DB volume, live credentials or unrelated resource use.
- Host Docker CLI production Compose models: **3 passed**, closing three baseline CLI skips.
- Frontend node tests: **59 passed**. TypeScript and Vite production build passed. Existing React Router “use client” bundler warnings remain, not runtime failures.
- Affected Playwright files: **120 passed**. New cases cover ordinary EN/RU light/dark 1440/390 Overview and four operation-error classes in each language. Existing tests exercise long names, 200% native Chromium zoom, keyboard focus, stale evidence, cross-source responses, modal confirmation and uncertain Apply.
- Docker Engine **29.7.2**, Compose **5.5.0**. Web Dockerfile rebuild passed. **4 Docker cases passed**: production Compose TLS/Unix API Bootstrap in standalone/corporate/external modes plus real production proxy tmpfs smoke. No tested security setting replaced by a mock tmpfs. Temporary port/volume fixtures isolate local smoke from canonical host ports.
- After final copy-only polish, the affected Overview/Operation browser subset passed again: **66 passed**. TypeScript/Vite and all 59 node tests also passed again. All **3 TLS cases passed again** on the final rebuilt Web image.
- git diff --check passed.

24 of the 91 baseline skipped nodes have separate current passes (17 PostgreSQL, 3 Compose render, 4 Docker). Of the other 67, two unchanged probe Docker cases have previous c1e8b1d evidence; 65 are explicitly independent unexecuted gates in this review, including live ESXi. There is no claim that all 91 passed, nor that UI fixtures replace those checks.

## Visual evidence

The reproducible gallery tests live in frontend/e2e/ui-hardening.spec.ts and durable-lifecycle.spec.ts. External evidence folder: netbox-sync-c1-review/index.html, delivered with the review (22 PNGs, not Git binaries). It separates:
- ordinary Overview: EN/RU, light/dark, 1440/390;
- long-name Overview: RU, light/dark, 1440/390;
- safe status-fetch errors: EN/RU, four categories;
- confirmed running and completed operation pages.

Screenshots are synthetic operator fixtures, not a live provider claim. Narrow history tables intentionally scroll within a labelled region; the whole page does not overflow. Do not interpret stress-fixture heights as ordinary content density.

## Scope and remaining decision

No authorization or online policy endpoint was implemented. The separate architecture proposal is for a decision, not a shipped login system. Web policy remains blocked until server identity and permissions are implemented and reviewed; Origin/CSRF and READY are not authorization.
