# Incremental refactoring

Baseline: main at 258d0e29fbaac881e2eb303c520399e1b6647d16.
Selectel remains experimental; see [status](selectel-status.md).
These stages preserve runtime behavior and do not authorize deployment.

## Sequence

1. **Shared record readers:** extract identical ID and choice-value readers used
   by planners and appliers. Keep existing module aliases and conversion behavior.
2. **Documentation and verification baseline:** index current contracts separately
   from historical reports; triage the browser failures recorded in
   [consolidation](consolidation-20261019.md). Establish checks for future PRs
   before changing API or UI structure. Do not delete assertions to make tests pass.
3. **API boundaries:** separate route groups and error handling while preserving
   routes, payloads, status codes, authorization, confirmation and dependency injection.
4. **Application entrypoint:** extract CLI/bootstrap responsibilities without
   changing entrypoints, environment handling, exit codes or execution order.
5. **Network reconciliation:** split large VM/LXC planning and apply functions
   one responsibility at a time. Preserve ownership, preflight-before-write,
   partial failure handling, replay rules and provider-specific policy.
6. **Deployment and remaining cleanup:** classify maintained scripts, compatibility
   tools and historical material. Remove only items proven unused by imports,
   packaging, deployment and supported upgrade/recovery procedures.

Each stage is a separate reviewable PR. Changing features or fixing unrelated
defects requires a separate change, so behavior changes are visible to reviewers.
Do not combine the remaining stages into one repository-wide rewrite.

## Stage 3a: read-only API routes

Starts from main `5503d84bf94e745238ea08731d6a6d9ca50fe867` after PR #7.
The preceding contrast change passed all 367 Chromium scenarios without skips;
see the [contrast resolution](browser-product-findings-20261019.md#contrast-resolution-follow-up).

`netbox_sync/api/read_routes.py` now registers nine existing GET handlers:
`/health`, `/system/health`, `/diagnostics`, `/version`, `/runs`, `/runs/{run_id}`,
`/pfsense`, `/sources`, and `/sources/{source_instance}`, all under `/api/v1`.
The factory supplies its already-created services and settings to this module.
Registration still uses the same router, at the same position, with the same
names, DTOs, query defaults and request-state assignments. Version lookup remains
late-bound and evaluated on each request.

An AST comparison confirmed all nine decorated functions are identical to their
original definitions, and the rest of the factory and shared boundaries are
unchanged. Complete OpenAPI schemas and ordered route metadata matched before
and after in both default and frontend/bootstrap configurations. The comparison
does not replace HTTP tests: 123 focused health, sources, history, diagnostics,
authorization, directory and frontend-route tests passed.

No existing assertion was changed. Shared middleware, authentication, errors,
onboarding, write operations and Selectel remain in their existing locations.
The frontend is unchanged; its mocked browser suite is not evidence for backend
equivalence and is not rerun for this extraction. API tests exercise the real
factory with injected services. No production service or deployment is involved.

Validation on Windows/Python 3.14: full `pytest tests -q --tb=short` completed with
1687 passed, 485 skipped and the existing Starlette deprecation warning. The skips
include Linux, database and opt-in integrations; they do not establish deployment
acceptance. Pylint for the extracted module scored 10.00/10, preserving the
factory's signature-related exemptions and the lazy catalog import. `git diff
--check` passed. Raw schema snapshots, comparison scripts and test logs are saved
locally in `artifacts/api-read-routes-evidence-20261019.zip` in the task workspace.

Next API increments should remain separate: lifecycle/schedule routes, guarded
operations, onboarding/catalog, then shared error/request boundaries. Preserve
initialization and route order, dependency injection, authorization and confirmation
checks at each step; do not bundle these into one rewrite.

## Stage 3b: lifecycle and schedule routes

Starts from main `9f8c99d6d43f7de8e153ccaf670b3a20ff8b103b` after PR #8.
`api/lifecycle_routes.py` registers the five existing lifecycle, placement, name
and removal handlers; `api/schedule_routes.py` registers the two schedule handlers.
Both installers use the existing router and factory-owned clients/services.
Catalog validation remains resolved per request because its factory binding is
initialized after route registration. Retirement, legacy admission and recovery
routers retain their original inclusion points.

All seven decorated handler ASTs match the originals. The remaining factory
(excluding the installers and relocated DTO import) and shared boundaries are
unchanged. Complete OpenAPI schemas and ordered route metadata match in default
and frontend/bootstrap configurations. Existing tests and assertions are unchanged.
Selectel remains experimental; no production or deployment changes are included.

The frontend is unchanged. Its last browser baseline remains 367 passing Chromium
scenarios; mocked browser checks are not a substitute for backend HTTP tests.
Validation on Windows/Python 3.14: full pytest completed with 1687 passed,
485 skipped and the existing Starlette warning. Linux, database and opt-in
integration skips do not establish deployment acceptance. Pylint for both new
modules scored 10.00/10; diff whitespace checks passed. Local evidence is saved in
`artifacts/api-lifecycle-routes-evidence-20261019.zip` in the task workspace.

Next increment: guarded operation routes, followed by onboarding/catalog and
shared error/request boundaries, each as a separate reviewable change.

## Stage 3c: operation and confirmation routes

Starts from main `a96ad0d39c3f1cd8a3c89ca5b5c37c8db204a99b` after PR #9.
`api/operation_routes.py` registers the seven existing operation-list, plan-start,
discovery-start, synchronous discovery, sync-plan, confirmation and apply routes.
The two related helpers move with them. Services and clients are still created
by the application factory and passed explicitly to the installer.

The fresh apply permission check, actor binding, stale-plan invalidation, source
identity checks and request-state run ID assignment remain unchanged. All nine
handler/helper ASTs match their originals; the remaining factory and shared
boundaries are unchanged. Complete OpenAPI schemas and ordered route metadata
match in default and frontend/bootstrap configurations. No test assertions changed.

Selectel remains experimental. No production or deployment changes are included.
The frontend is unchanged; its previous 367-pass Chromium baseline is not rerun
for this backend extraction. Full pytest on Windows/Python 3.14 completed with
1687 passed, 485 skipped and the existing Starlette warning. Linux, database and
opt-in integration skips do not establish deployment acceptance. Pylint scored
10.00/10 and diff whitespace checks passed. Local evidence is saved in
`artifacts/api-operation-routes-evidence-20261019.zip` in the task workspace.

Next increment: onboarding/catalog routes, then shared error/request boundaries.

## Stage 3d: onboarding and catalog routes

Starts from main `d85639a13ee12cd0a89ad2884fd8c570aa06eb74` after PR #10.
`api/catalog_routes.py` registers three catalog handlers. `api/onboarding_routes.py`
registers eight onboarding handlers and owns their unchanged registration helpers,
job initialization and continuation lifespan. The factory still creates services,
clients and settings; the installer runs at the original registration position.
Catalog exception translation stays in the factory for the boundary refactor.

Expanding both installer bodies reproduces the entire original factory AST,
including receipt checks, actor binding, namespace checks, registration guards,
job setup and thread shutdown. Complete OpenAPI schemas and ordered route metadata
match in default and frontend/bootstrap configurations. Existing tests are unchanged.
Selectel remains experimental; no production or deployment changes are included.

### Existing findings, outside this refactor

Pylint reports the same nine undefined `HostRegistrationConflict` references in
both the original factory and extracted onboarding module. The only original
import is local to `_install_boundaries`, so these rejection paths can raise
`NameError` instead of their intended domain exception. Fix this separately with
regression coverage for namespace/closed-source and registration-intent conflicts;
this extraction deliberately does not change those responses.

The `saved` indexing diagnostic (E1136) also exists in the original connection-test
handler; it requires a separate type-flow review. These findings are not suppressed,
and this stage does not claim a clean Pylint result.

Full pytest on Windows/Python 3.14: 1687 passed, 485 skipped, one existing
Starlette warning. Linux, database and opt-in skips are not deployment acceptance.
Error/fatal lint diagnostics exactly match the baseline (10 findings); whitespace
checks pass. Evidence is saved locally in
`artifacts/api-onboarding-routes-evidence-20261019.zip` in the task workspace.
Browser tests are unchanged and were
not rerun for this backend extraction. Next stage: shared error/request boundaries.

## Registration refusal fix after stage 3d

PR #11 was merged as `e54f5b789eae2eff601d3a29cf326c20472f8476`.
The missing `HostRegistrationConflict` import is now present in the onboarding
module. The existing exception boundary returns HTTP 409 with the domain code
instead of an internal HTTP 500. No admission rule or exception mapping changed.

Thirteen HTTP regressions cover direct and durable registration: closed sources,
mismatched source identity, non-boolean closure status, unavailable/outdated Guard,
foreign namespaces, and changed durable intent. They use real API middleware and
auth policy with fake external services, and assert no reservation, credential
consumption, job staging or registration writes occur after refusal. All thirteen
failed before the import and pass after it. The production code change is one import.
The separate E1136 type-flow finding remains outside this fix.

Full pytest on Windows/Python 3.14: 1700 passed, 485 skipped, one existing Starlette
warning. Linux, database and opt-in integration skips are not deployment acceptance.
Undefined-variable lint and whitespace checks pass. Before/after and full-suite
logs are saved locally in `artifacts/registration-refusal-evidence-20261019.zip`.
Selectel remains experimental;
no production or deployment changes. Continue boundary refactoring separately.

## Stage 3e: shared request and error boundaries

Starts from main `37e3fbde842ece3b384facc239651f7aec7cc3c5` after PR #12.
`api/request_boundaries.py` now owns the existing `_error` response helper,
`_install_boundaries` and catalog exception registration. The factory imports the
private helpers for compatibility and installs each boundary at its original point.
The shared logger retains its name and object identity; logger setup stays in the
factory. Source-provider and frontend route registration remain unchanged.

The response helper, middleware and exception handler ASTs are unchanged. The
remaining factory matches after expanding the catalog installer and accounting for
its relocated exception import. Complete OpenAPI schemas, ordered routes, exception
handler registries and middleware order/dispatch names match in default and
frontend/bootstrap configurations. Existing tests and assertions are unchanged.

Full pytest on Windows/Python 3.14: 1700 passed, 485 skipped, one existing
Starlette warning. Linux, database and opt-in skips are not deployment acceptance.
Pylint error/fatal checks report no findings in the new module; whitespace checks
pass. Evidence is saved locally in `artifacts/api-boundaries-evidence-20261019.zip`.
Selectel remains experimental; no
production or deployment changes. Frontend/browser tests were not rerun for this
backend extraction. Further decomposition should follow a fresh review rather than
changing error mappings or admission rules as part of structural cleanup.

## Stage 2 scope

PR #4 was merged as `f67d5622b3618ea9986e837feb5cc7d490175310`.
The [documentation map](README.md) separates entry points, contracts, historical
evidence and proposals without moving or deleting existing files. The
[verification baseline](verification-baseline.md) defines checks and limitations;
the [stage 2 report](refactoring-stage2-validation.md) inventories browser failures.
Runtime behavior, test assertions and deployment remain unchanged in this stage.
Before restructuring API/UI code, repair the affected browser scenarios in a
separate test-maintenance change and investigate unresolved behavior failures.

## Stage 1 scope

Nine identical function definitions are replaced with two shared readers in
`netbox_sync/netbox_record_values.py`: seven `_object_id` definitions and two
`_choice_value` definitions. The original private names remain imported aliases.

Compatibility is intentional: integer subclasses (including bool) pass through
the ID reader, dictionary values are not coerced, and choice objects without a
`value` attribute pass through unchanged. Similar helpers in ESXi, host-primary-IP
and network-scope modules have distinct contracts and are not consolidated here.

An AST comparison verifies that the extracted bodies match the originals and
that the remaining executable code in all seven callers is unchanged.
Validation results for this stage are recorded in its PR. No API/frontend,
Selectel policy, migrations, deployment or production changes are part of stage 1.
