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
