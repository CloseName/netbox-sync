# Refactoring verification baseline

Stage 2 starts at main `f67d5622b3618ea9986e837feb5cc7d490175310`,
after PR #4. This document distinguishes local checks from deployment acceptance.
Selectel remains [experimental](selectel-status.md). No production acceptance or
deployment is implied by a passing local check.

## Checks for subsequent PRs

Run commands from the repository root unless indicated otherwise:

| Change | Required local evidence |
| --- | --- |
| Documentation only | Resolve new relative links; `git diff --check`; verify claims against the named implementation |
| Python shared helpers, API, bootstrap or reconciliation | Focused tests for affected contracts, then `python -m pytest tests -q`; report platform and skips |
| Frontend or browser fixtures | In `frontend`: `npm ci`, `npm test`, `npm run build`, `npx playwright install chromium`, `npm run test:e2e` |
| Routes or frontend serving | Also run `python -m pytest tests/test_frontend_routes.py tests/test_api_health.py` |
| Database, workers or deployment | Relevant isolated Linux/PostgreSQL/container checks; Windows skips do not establish acceptance |

Existing GitHub workflows are scoped to particular feature branches and do not
automatically establish a green gate for every refactoring PR. Record exact
commands and results in each PR. Do not interpret an absent check as a passing one.

Browser tests start local Vite and intercept API calls with fixtures. They verify
client behavior against those fixtures, not real provider connectivity, server
authorization, migrations, NetBox writes, or Selectel matching. Keep credentials
and live endpoints out of this suite.

## Failure handling

Preserve the behavioral purpose of a failing assertion. If a control moved, update
its accessible selector and still exercise the same action and result. If a fixture
is obsolete, model the current API contract rather than bypassing prerequisites.
Do not remove scenarios, add blanket skips, relax authorization, or retry writes
solely to make a suite green.

Separate confirmed obsolete selectors from unresolved failures. A disabled action
can be a correct guard, incomplete fixture, or application defect; inspect its
prerequisites before classifying it. Keep behavior fixes in separate changes.
Before API/UI restructuring, resolve failures in the affected scenarios and rerun
them. A red baseline is a tracked limitation, not permission to introduce new failures.

## Previous evidence

PR #4 preserved executable behavior while extracting identical record readers.
Its Windows/Python 3.14 run passed 1687 tests with 485 skips. That is historical
evidence for stage 1; it is not a fresh Linux or deployment result.
The [consolidation report](consolidation-20261019.md) contains the earlier interrupted
browser attempt. Do not combine counts from interrupted and focused runs.

Stage 2 local results and the complete browser failure inventory are recorded in
[the stage 2 report](refactoring-stage2-validation.md).
