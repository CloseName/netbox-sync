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

## Stage 4a: entrypoint orchestration

Starts from main `21b7b1d3cdc34ae9c5ea02cac164cabd603d69a0` after PR #13.
Before extraction, 19 new tests passed against the existing implementation. They
cover sync-mode defaults/normalization, invalid-mode exit 2, legacy and registry
single-source dispatch, registry-all scheduler ordering, reader/writer DSN choice,
execution gating, hidden executor output, exact summary text and failure exit 1.

`entrypoint.py` owns mode selection, startup orchestration and summary output.
`netbox_sync:main` remains the installed console entrypoint and passes callbacks
resolved at invocation time. Existing package helper names remain available.
Provider dispatch and all execution/planning/apply functions remain in the package
for later increments, preserving their late-bound dependencies. The script guard,
TLS-warning handling, packaging and environment variable names are unchanged.

Extracted bodies and remaining execution functions match their original ASTs.
The final full pytest run on Windows/Python 3.14 passed 1719 tests with 485 skips
and one existing Starlette warning. Linux, database and opt-in skips are not
deployment acceptance. All 41 focused tests pass; error/fatal lint and whitespace
checks pass. Evidence is saved locally in `artifacts/entrypoint-evidence-20261019.zip`.
Selectel remains experimental; no
production or deployment changes. This is the first entrypoint increment, not a
rewrite of the 1000-line execution module. Next consider reporting and execution
responsibilities separately before network reconciliation.

## Stage 4b: shared synchronization execution

Starts from main `b621104cdffcecf5db3751d81e8a99e597635aab` after PR #14.
`sync_execution.py` owns the existing post-discovery execution pipeline shared by
Proxmox and ESXi. The package-level `execute_discovered_source` retains its original
signature and supplies existing collaborators per invocation. Provider connection,
discovery, dispatch, legacy helpers and the actual planners/appliers stay unchanged.

The extracted body is AST-identical, including duplicate-identity refusal, token
selection, durable NetBox configuration, TLS setup, plan preflight, guarded writes,
confirmation strings, failure stage tracking and the legacy fallback. All other
package function definitions and the script guard match the baseline.

Before extraction, 14 new routing tests passed on main. They cover all five partial
apply scopes with correct/incorrect confirmation, invalid-scope refusal before
credentials or connection, and inventory/plan read-token selection. After extraction,
76 focused tests pass, including existing real local REST checks for blocked plans,
write refusal without retries, retained plan evidence and ESXi dispatch. Existing
assertions are unchanged. Full pytest on Windows/Python 3.14: 1733 passed,
485 skipped, one existing Starlette warning. Linux, database and opt-in skips are
not deployment acceptance. Error/fatal lint and whitespace checks pass. Local logs
and comparison script are in `artifacts/sync-execution-evidence-20261019.zip`.

Selectel remains experimental; no production/deployment changes. This step does not
split the execution function internally or alter reconciliation rules. Provider
connection/discovery and legacy reporting remain possible subsequent small steps;
network planners/appliers should follow separately with their own safety evidence.

## Stage 4c: provider connection and discovery

Starts from main `a145797db245c59672793ddaead15fb7488f1e93` after PR #15.
`proxmox_executor.py` now owns the existing Proxmox credentials, API connection,
TLS setup, discovery and endpoint selection sequence, plus the unchanged token-name
parser. The package keeps the original executor signature and token helper alias;
collaborators are supplied per invocation to preserve existing injection points.
ESXi already has `esxi_executor.py`, so its adapter/session lifetime is unchanged.
Provider-specific discovery implementations and shared synchronization are untouched.

Twelve new tests passed on main before extraction. They cover normal and legacy
secret resolvers, exact connection parameters, ordering through reconciliation and
immediate failure propagation at credentials, connection, TLS, discovery and endpoint
selection. After extraction, 81 focused tests pass. The adapter body and token parser
are AST-identical; all other package functions and the script guard are unchanged.
Existing assertions are unchanged. Full pytest on Windows/Python 3.14: 1745 passed,
485 skipped, one existing Starlette warning. Linux, database and opt-in skips are
not deployment acceptance. Error/fatal lint and whitespace checks pass. Evidence
is saved locally in `artifacts/source-connection-evidence-20261019.zip`.

Selectel remains experimental; no production/deployment changes. Next possible
increment: legacy inventory/reporting helpers, before deeper reconciliation changes.

## Stage 4d: legacy inventory and reports

Starts from main `900ef50b1012bf72f0ad200d8cead4bde7ba3cd5` after PR #16.
`legacy_inventory.py` owns `_load_nb_objects`, `_run_inventory` and the historical
`_run_plan` report. Package aliases preserve loader/inventory access, and a wrapper
keeps the plan signature and per-call CPU helper injection. The historical plan is
retained for compatibility; it is not substituted for the current planner.
No legacy write functions, source discovery, synchronization rules or CLI modes change.

Four new tests pass on the original implementation and after extraction. Checked-in
output fixtures capture empty/populated inventory; a mixed plan asserts exact
CREATE/UPDATE/SKIP/BLOCKED output and unchanged records. The loader test verifies
endpoint read order, index keys, duplicate overwrite behavior and record identity
using endpoints without write methods. After extraction, 41 focused tests pass.
All three extracted bodies and remaining package functions match their original ASTs.
Existing assertions are unchanged. Full pytest on Windows/Python 3.14: 1749 passed,
485 skipped, one existing Starlette warning. Linux, database and opt-in skips are
not deployment acceptance. Error/fatal lint and whitespace checks pass. Four report
tests also pass with the final JSON-encoded exact-output fixtures. Evidence is saved
locally in `artifacts/legacy-reports-evidence-20261019.zip`.

Selectel remains experimental; no production/deployment changes. Legacy mutation
helpers remain separate future work and must not be deleted merely because they
belong to an older path. Deeper network reconciliation remains a separate stage.

## Stage 4e: retained legacy NetBox writes

Starts from main `8a8ca0380af5829a69c1e9d6fb0ebd992081bcbb` after PR #17.
`legacy_netbox_writes.py` contains the ten existing tag, VM, interface, MAC/IP/VLAN,
disk and parsing/CPU helpers. Their package names remain imported aliases. Complete
function definitions (including signatures) match their original ASTs; all remaining
package functions and the script guard are unchanged. Modern guarded appliers,
confirmation logic, source dispatch and the shared execution pipeline are untouched.

Seven new tests pass before and after extraction. Local fake NetBox mutation traces
freeze create/update ordering and create payloads; explicit assertions cover VM
fields, primary IP and disk size. Other tests preserve failure propagation without
cache insertion and historical decimal disk units. Sixty focused tests pass after
extraction; existing assertions are unchanged. Full pytest on Windows/Python 3.14:
1756 passed, 485 skipped, one existing Starlette warning. Error/fatal lint and
whitespace checks pass. Local evidence is saved in
`artifacts/legacy-writes-evidence-20261019.zip`.
The tests use local fakes and do not establish real NetBox write acceptance.

Selectel remains experimental; no production/deployment changes. This extraction
retains historical write semantics, including their existing cache and parsing
behavior. Any corrections require separately reviewed behavior fixes. Next review
the now-small package facade before starting network planner/applier decomposition.

## Stage 5a: VM network inventory preparation

Starts from main `3abe63f4225fcf56d36fad086165ccb039d46920` after PR #18.
`vm_network_inventory.py` reads target VMs, interfaces, MACs and IPs in the original
order and returns their original records and six index/list collections. The
`apply_vm_networks` function retains site/cluster validation, conflict/ownership
checks, preflight, confirmation and all writes. No reads are broadened or cached.
Duplicate records remain ordered lists; IP keys retain VRF scope; invalid addresses
remain in the ID index but are excluded from address lookup as before.

Eight new behavior tests passed on main before extraction: read order, errors at
each read, duplicate MAC/IP refusal before writes, and malformed unrelated IPs.
After extraction, 67 focused tests pass. One additional helper-contract test verifies
record identity, orphan interfaces, duplicate preservation, VRF separation and
invalid-IP indexing (nine new tests total). Expanding the preparation call restores
the complete original apply AST; other functions and error classes are unchanged.

Full pytest on Windows/Python 3.14: 1765 passed, 485 skipped, one existing
Starlette warning. Linux, database and opt-in skips are not deployment acceptance.
Error/fatal lint and whitespace checks pass. Local evidence is saved in
`artifacts/vm-inventory-evidence-20261019.zip`. Selectel remains experimental;
no production/deployment changes. Next candidate: equivalent LXC preparation,
reviewing differences explicitly rather than automatically sharing VM rules.

## Stage 5b: LXC network inventory preparation

Starts from main `7286ab101031d58dfe24581aa5a6707b87e64fd6` after PR #19.
`lxc_network_inventory.py` owns only LXC reads and four list/index collections.
Unlike VM preparation, LXC reads all VMs across clusters and checks the matched
container's cluster later. It retains its own IP canonicalizer (including string
conversion) and does not introduce VM-specific interface/IP ID indexes. Both keep
ordered duplicate lists and VRF-scoped IP keys. No shared abstraction changes these
provider-specific semantics. Target validation, conflicts and writes stay in the applier.

Nine new behavior tests passed before extraction, covering read order and failures,
duplicate MAC/IP refusal, malformed addresses and matched identity outside the target
cluster. One additional helper-contract test covers global VM retention, original
records, orphan interfaces and scoped duplicate indexes (ten new tests total).
After extraction, 55 focused tests pass, including VM contracts, network scopes,
conflicts, first-sync and scheduled execution. Inlining the loader restores the
original complete apply AST; other functions/error classes are unchanged.

Full pytest on Windows/Python 3.14: 1775 passed, 485 skipped, one existing
Starlette warning. Linux, database and opt-in skips are not deployment acceptance.
Error/fatal lint and whitespace checks pass. Local evidence is saved in
`artifacts/lxc-inventory-evidence-20261019.zip`. Selectel remains experimental;
no production/deployment changes. Next consider read-only context/preflight preparation
inside one applier, preserving all-before-write checks as a separate small increment.

## Stage 5c: VM network preflight

Starts from main `05ea9ec27a6b47fe7208b0ebe5502297ae2ea2f6` after PR #20.
`vm_network_preflight.py` prepares checked contexts for the entire VM batch before
reporting or writing. It preserves identity/name validation, MAC/IP ownership and
duplicate checks, VRF scopes and primary IPv4 decisions. Existing error classes and
helper imports remain available from the applier. LXC semantics are unchanged.

Twelve new tests passed before extraction: conflicts on the second VM prevent any
writes or report output, with and without confirmation. They cover duplicate
source MAC/IP, foreign MAC/IP ownership, foreign primary IPv4 and missing identity.
After extraction, 88 focused tests pass. AST comparison confirms that inlining the
new preparation function restores the original apply function exactly, and all
moved helpers/error classes are unchanged. Error/fatal lint passes.

Full pytest on Windows/Python 3.14: 1787 passed, 485 skipped, one existing
Starlette warning. Linux, database and opt-in skips are not deployment acceptance.
Local evidence: `artifacts/vm-preflight-evidence-20261019.zip`.
Selectel remains experimental; no production or deployment changes.

## Stage 5d: LXC network preflight

Starts from main `9969909837233f3e8d48a96125a6a3748d623440` after PR #21.
`lxc_network_preflight.py` prepares checked contexts for the complete LXC batch
before reporting or writing. Existing errors and helper imports remain available
from the applier. Report, confirmation and write code are unchanged.

The LXC-specific checks remain separate from VM: identity lookup spans all clusters,
then rejects a container outside the selected cluster; changing a primary MAC is
refused. Existing primary IPv4 is not a preflight refusal: the unchanged writer can
replace it with the unique discovered candidate. No VM manual-primary policy is
introduced into LXC. IP normalization, VRF scopes, duplicate detection and check
order are preserved.

Fifteen new tests passed before extraction: fourteen combinations of later-container
conflicts and confirmation modes prove no writes or report output on failure; one
checks that existing primary IPv4 does not cause LXC preflight refusal. After
extraction, 72 focused tests pass, including VM contracts and shared network tests.
AST comparison confirms that inlining preparation restores the complete original
apply function; moved helpers and error classes are unchanged. Error/fatal lint passes.

Full pytest on Windows/Python 3.14: 1802 passed, 485 skipped, one existing
Starlette warning. Linux, database and opt-in skips are not deployment acceptance.
Local evidence:
`artifacts/lxc-preflight-evidence-20261019.zip`. Selectel remains experimental;
no production access or deployment changes.

## Stage 5e: VM network precheck report

Starts from main `8add53216ceab6db287f3a9661df97f6fc02e8d4` after PR #22.
`vm_network_report.py` prints validated VM network contexts and all ten summary
counters. The existing confirmation gate, mutation loop and final apply summary
remain in the applier. LXC code and its distinct primary MAC/IP policies are unchanged.

Sixteen tests passed before extraction against eight fixed output snapshots captured
from the original implementation. Independent expected counters cover create, update,
skip, primary set/match/preserve, absent MAC/IP, IPv6-only, mixed VM batches and empty
input. Every scenario runs both confirmed and unconfirmed; unconfirmed runs assert
zero mutations and the exact confirmation message. Snapshots are read-only during tests.
After extraction, 87 focused tests pass. AST comparison confirms all applier functions
are identical after inlining the reporter. Error/fatal lint passes.

Full pytest on Windows/Python 3.14: 1818 passed, 485 skipped, one existing
Starlette warning. Linux, database and opt-in skips are not deployment acceptance.
Local evidence:
`artifacts/vm-report-evidence-20261019.zip`. Selectel remains experimental;
no production access or deployment changes.

## Stage 5f: LXC network precheck report

Starts from main `9888275084a9a3cf73780016dd18c4bd1c8297a2` after PR #23.
`lxc_network_report.py` prints validated LXC contexts and eight summary counters.
Confirmation, writes and the final apply summary remain unchanged in the applier.
Unlike VM reporting, LXC reports primary IPv4 candidates without SET/MATCH/PRESERVE
classification. Existing primary IPv4 does not change this report policy.

Sixteen tests passed before extraction against eight fixed output snapshots from
the original implementation, with independently specified counter values. Cases
cover create/update/skip, existing primary IPv4, absent MAC/IP, IPv6-only, mixed
containers and empty input, both confirmed and unconfirmed. Unconfirmed runs assert
zero mutations and exact confirmation messages. Tests never regenerate snapshots.
After extraction, 82 focused tests pass, including VM report/preflight contracts.
AST comparison restores every original applier function after inlining the report.
Error/fatal lint passes. Full pytest on Windows/Python 3.14: 1834 passed,
485 skipped, one existing Starlette warning. Linux/database/opt-in skips are not
deployment acceptance.
Local evidence: `artifacts/lxc-report-evidence-20261019.zip`.
Selectel remains experimental; no production access or deployment changes.

## Stage 5g: VM network writes

Starts from main `567bac36287544e60dbc94c669942a10dd55ed50` after PR #24.
`vm_network_writes.py` owns the unchanged ordered mutation loop and apply output,
including final counters. The applier still resolves the target, loads inventory,
validates the whole batch, prints precheck and enforces confirmation before calling
the writer. The writer accepts already checked contexts; it is not a new public
confirmation bypass. LXC code and provider-specific policies are unchanged.

Thirteen new tests passed before extraction. Ten injected failure positions across
two VMs assert exception identity, stop-on-first-failure, the exact completed-write
prefix and absence of a success summary. Three fixed snapshots capture full mutation
payloads and apply output for creation, reuse of unassigned MAC/IP, and preservation
of manual primary IPv4, with VRF 42. Each successful scenario asserts mutation-free
replay. Snapshots are read-only during tests. Existing tests continue to cover MAC
replacement, ownership conflicts and no writes without confirmation.

After extraction, 116 focused tests pass. AST comparison restores every original
applier function after inlining the writer. Error/fatal lint passes.
Full pytest on Windows/Python 3.14: 1847 passed, 485 skipped, one existing
Starlette warning. Linux/database/opt-in skips are not deployment acceptance.
Local evidence:
`artifacts/vm-writes-evidence-20261019.zip`. Selectel remains experimental;
no production access or deployment changes.

## Stage 5h: LXC network writes

Starts from main `a4fa8bcf79461ac8151a228f491209c9e0eff1dc` after PR #25.
`lxc_network_writes.py` owns the original mutation loop, operation output and final
counters. Target resolution, inventory, whole-batch preflight, precheck report and
confirmation remain in the applier. VM code is unchanged. LXC still refuses primary
MAC replacement during preflight, and its writer replaces existing primary IPv4
with the unique discovered candidate instead of applying VM manual-primary policy.

Thirteen new tests passed before extraction. Ten injected failure positions across
two containers assert exception identity, stop-on-first-failure, exact completed-write
order and no success summary. Three fixed snapshots preserve complete mutation
payloads and output for creation, unassigned MAC/IP reuse and existing primary IPv4
replacement with VRF 42. The old IP record remains present; successful cases replay
without mutations. Snapshots are read-only during tests.
After extraction, 108 focused tests pass, including VM write/report/preflight and
network safety contracts. AST comparison restores every original applier function
after inlining the writer. Error/fatal lint passes.
Full pytest on Windows/Python 3.14: 1860 passed, 485 skipped, one existing
Starlette warning. Linux/database/opt-in skips are not deployment acceptance.
Local evidence:
`artifacts/lxc-writes-evidence-20261019.zip`. Selectel remains experimental;
no production access or deployment changes.

## Stage 5i: VM network planner inventory

Starts from main `37c1ddd49aa404a4ff323808d11c3699a1687237` after PR #26.
`vm_network_plan_inventory.py` owns the six ordered reads and seven collections
used by the legacy VM network planner. Planning decisions, counters and output
stay unchanged. This is separate from write inventory: planner IP keys are address
only (not VRF scoped), VLAN keys use integer VID, and prefix keys use literal strings.
Duplicates retain order and original record references; invalid IPs remain in the
ID index, and invalid VLAN conversion still raises. No shared loader changes policy.

Eleven behavioral tests passed before extraction: each read failure, exact read
order/filter, duplicate records, malformed IP/VLAN data, fixed output snapshots and
zero mutations. One additional helper test verifies original references, address-only
IP grouping across VRFs, invalid-IP ID retention and VLAN/prefix duplicates.
After extraction, 58 focused tests pass. AST comparison restores every original
planner function after inlining preparation. Error/fatal lint passes.
Full pytest on Windows/Python 3.14: 1872 passed, 485 skipped, one existing
Starlette warning. Linux/database/opt-in skips are not deployment acceptance.
Local evidence:
`artifacts/vm-plan-inventory-evidence-20261019.zip`. Selectel remains experimental;
no production access or deployment changes.

## Stage 5j: per-interface MAC planning

Starts from main `f9ce76084f0e7d013c9915f0770d7446772ea1e7` after PR #27.
`vm_network_plan_mac.py` owns the original per-interface MAC decision/output and
three counter increments. The planner supplies its canonicalization/assignment
readers. MAC conflicts still report and continue into IP planning, unlike write
preflight refusal; no write policy is reused or changed.

Eight tests passed before extraction through the full planner: absent MAC,
normalization/create, unassigned reuse, ownership match, foreign assignment, wrong
object type, incomplete assignment and duplicate records. Exact MAC lines and
counter values, subsequent IP planning and zero mutations are asserted.
After extraction, 70 focused tests pass. AST comparison restores every original
planner function after inlining the helper. Error/fatal lint passes.
Full pytest on Windows/Python 3.14: 1880 passed, 485 skipped, one existing
Starlette warning. Linux/database/opt-in skips are not deployment acceptance.
Local evidence:
`artifacts/vm-plan-mac-evidence-20261019.zip`. Selectel remains experimental;
no production access or deployment changes.

## Stage 5k: per-interface IP and prefix planning

Starts from main `d89f015af0c2ab5b9aae56124834c28afdc224bc` after PR #28.
`vm_network_plan_ip.py` owns the original IP loop, prefix selection/reporting,
IP counters and IPv4 candidate accumulation. The caller supplies the same helper
functions and mutable collections. Primary IPv4 decision remains in the planner.
Conflicts continue to later addresses; conflicting IPv4 addresses still contribute
to primary candidates. Address-only indexing across VRFs and site/global prefix
preference remain distinct from write policy. VM/LXC write code is unchanged.

Twelve tests passed before extraction, comparing fixed full-output snapshots and
independent counters: create/free/owned/foreign IP, duplicates across VRFs, ignored
addresses, IPv6, site/global/foreign/ambiguous prefixes and conflicting primary
candidate. Tests assert continued IP analysis and no mutations; snapshots are
read-only during tests. After extraction, 82 focused tests pass. AST comparison
restores all original planner functions after inlining the helper. Error/fatal lint passes.
Full pytest on Windows/Python 3.14: 1892 passed, 485 skipped, one existing
Starlette warning. Linux/database/opt-in skips are not deployment acceptance.
Local evidence:
`artifacts/vm-plan-ip-evidence-20261019.zip`. Selectel remains experimental;
no production access or deployment changes.

## Stage 5l: primary IPv4 planning

Starts from main `a05394e3d98050e53108c1a1b843c703f3057d05` after PR #29.
`vm_network_plan_primary.py` owns candidate deduplication/sorting and the original
KEEP/SET/unchanged output and counter. The existing primary reader is supplied by
the planner. Decisions still compare canonical address including mask, without
write-side ownership or manual-primary preservation policy. Conflicting discovered
IPs can still be primary candidates. VM/LXC writes remain unchanged.

Eleven tests passed before extraction: no addresses, IPv6-only, set, keep despite
ownership conflict, replace, missing/empty current record, duplicate candidates,
sorted ambiguity, mask change and malformed current address. Tests assert exact
primary output/counter, original ValueError/no summary on malformed current data,
unchanged VM records and zero mutations. After extraction, 93 focused tests pass.
AST comparison restores all original planner functions after inlining the helper.
Error/fatal lint passes. Full pytest on Windows/Python 3.14: 1903 passed,
485 skipped, one existing Starlette warning. Linux/database/opt-in skips are not
deployment acceptance.
Local evidence: `artifacts/vm-plan-primary-evidence-20261019.zip`.
Selectel remains experimental; no production access or deployment changes.

## Stage 5m: per-interface VLAN and bridge planning

Starts from main `0c8b409a72c53939dc5188587f016bb05faf91ed` after PR #30.
`vm_network_plan_vlan.py` owns bridge output and VLAN choice/reporting for one
interface. The unchanged shared scope selector is passed by the planner; prefix
selection and VM/LXC writes are unchanged. Missing/ambiguous VLAN remains a warning,
with no creation and no interruption of subsequent MAC/IP planning.

Eighteen tests passed before extraction: absent/missing/global/site VLAN, preference
for a site VLAN over duplicate global candidates, foreign-only scope, ambiguous
site/global candidates, VID zero, and present/absent bridge. Tests assert exact
output/order, warning counts, continued MAC/IP planning and zero mutations.
After extraction, 84 focused tests pass. AST comparison restores all original planner
functions after inlining the helper. Error/fatal lint passes.
Full pytest on Windows/Python 3.14: 1921 passed, 485 skipped, one existing
Starlette warning. Linux/database/opt-in skips are not deployment acceptance.
Local evidence:
`artifacts/vm-plan-vlan-evidence-20261019.zip`. Selectel remains experimental;
no production access or deployment changes.

## Stage 5n: interface validation and matching

Starts from main `9a82bbebcf83537a79de165d3793ab2420468ef9` after PR #31.
`vm_network_plan_interfaces.py` separates VM-wide name validation from per-interface
identity matching. Validation returns whether the VM may continue; matching returns
an explicit continuation flag plus the existing interface, distinguishing creation
(None) from conflict. Original exceptions, output/counters and skip boundaries stay
unchanged. VM/NIC ordering and all downstream planning remain in the caller.

Five new full-planner tests passed before extraction: create, match, manual name
collision, duplicate identity and duplicate desired name. They assert counters,
no downstream work on blocked VM, continued processing of the next VM and no writes.
After extraction, 86 focused tests pass, including existing naming and network tests.
AST comparison restores all original planner functions after inlining helpers and
mapping their refusal returns back to the original continue statements.
Error/fatal lint passes. Full pytest on Windows/Python 3.14: 1926 passed,
485 skipped, one existing Starlette warning. Linux/database/opt-in skips are not
deployment acceptance.
Local evidence: `artifacts/vm-plan-interfaces-evidence-20261019.zip`.
Selectel remains experimental; no production access or deployment changes.

## Stage 5o: final VM network plan report

Starts from main `aadc21518c5518e0c82d1c10fc0b3bd5d63fd4b4` after PR #32.
`vm_network_plan_report.py` prints the unchanged final heading and thirteen counters
in their original order. Counter initialization/increments and all decisions remain
in their existing locations; the report is called at the original completion point.

Five tests passed before extraction: empty, create, match, blocked and mixed VM
batches. They assert the exact final output including whitespace, all counter values,
only one summary, no trailing output and zero mutations. After extraction, 71 focused
planner tests pass. AST comparison restores all original planner functions after
inlining the reporter. Error/fatal lint passes.
Full pytest on Windows/Python 3.14: 1931 passed, 485 skipped, one existing
Starlette warning. Linux/database/opt-in skips are not deployment acceptance.
Local evidence:
`artifacts/vm-plan-summary-evidence-20261019.zip`. Selectel remains experimental;
no production access or deployment changes.

## Stage 6a: host apply target preparation

Starts from main `512c9a8a76f24a0483507dc10764eb91014c6b09` after PR #33.
`host_apply_targets.py` resolves site, role, platform, per-host device types and
cluster into an immutable container of original records. Mapping validation and
lookups keep their original order and lazy import. The applier supplies its existing
required-object and cluster resolvers, preserving aliases and injected behavior.
Host preflight, report, confirmation and writes remain in the applier. VM/LXC policy
and host_networking behavior are unchanged.

Eleven tests passed before extraction: ordered legacy/explicit-ID selection (with
stale name/slug values), missing prerequisites, foreign scope/type and duplicate
clusters. Failures precede host checks, output and mutations. After extraction,
76 focused tests pass and 33 environment-dependent tests skip. AST comparison
restores all original host applier functions after inlining preparation.
Error/fatal lint passes. Full pytest on Windows/Python 3.14: 1942 passed,
485 skipped, one existing Starlette warning. Linux/database/opt-in skips are not
deployment acceptance.
Local evidence: `artifacts/host-targets-evidence-20261019.zip`.
Selectel remains experimental; no production access or deployment changes.

## Stage 6b: host preflight context

Starts from main `69ed2ec5edc6f9427bc4210ec805efe5314859d4` after PR #34.
`host_apply_preflight.py` owns the unchanged per-host preflight body: device resolution,
network checks, management binding, IP ownership and desired metadata. The existing
`_preflight_host` signature stays as a wrapper supplying original helpers/error class.
This preserves existing imports and monkeypatch boundaries without circular imports.
The all-host loop remains before report/confirmation/writes in `apply_hosts`.
The host_networking=False path still resolves identity/metadata but skips network checks.

Eleven new tests passed before extraction: five second-host conflicts with/without
confirmation (name adoption, duplicate interfaces, missing management address, foreign
IP, duplicate IP) stop the entire batch before output/mutations. One test fixes the
network-disabled behavior. After extraction, 77 focused tests pass and one skips.
AST comparison restores all original host applier functions/classes after inlining
the preflight body. Error/fatal lint passes. Full pytest on Windows/Python 3.14: 1953 passed,
485 skipped, one existing Starlette warning. Linux/database/opt-in skips are not
deployment acceptance.
Local evidence: `artifacts/host-preflight-evidence-20261019.zip`.
VM/LXC policies are unchanged. Selectel remains experimental; no production access
or deployment changes.

## Stage 6c: host precheck report

Starts from main `00c41dd645b47d612ebd547676caad35ee8cc027` after PR #35.
`host_precheck_report.py` prints the original report for all checked host contexts.
It preserves device actions/reasons, changed-field order/count, interface/address
counts, management binding and PRECHECK PASSED. The original host-type lookup is
retained. Confirmation messages, the gate and writes remain in the applier.

Six tests passed before extraction against fixed exact-output snapshots: empty,
create, match, changed metadata, mixed hosts and networking disabled. They include
the exact no-confirmation suffix and assert zero mutations. Snapshots are read-only.
After extraction, 73 focused tests pass and one skips. AST comparison restores all
original applier functions/classes after inlining the report. Error/fatal lint passes.
Full pytest on Windows/Python 3.14: 1959 passed, 485 skipped, one existing
Starlette warning. Linux/database/opt-in skips are not deployment acceptance.
Local evidence:
`artifacts/host-report-evidence-20261019.zip`. Selectel remains experimental;
no production access or deployment changes.

## Stage 6d: host writes

Starts from main `a375cb4929ee70badf163d77c71c612adec01819` after PR #36.
`host_apply_writes.py` owns the original device/interface/IP writes, late IP conflict
checks, primary assignment and operation/summary output. The applier supplies its
existing helpers and error class. All-host preflight, report and confirmation gate
remain in the caller. The network-disabled path and VM/LXC behavior are unchanged.

Nine tests passed before extraction: four write failure boundaries, three exact
payload/output snapshots (create, free-IP reuse, network-disabled) with mutation-free
replay, and duplicate/foreign IP appearing after preflight. Test discovery timestamps
are fixed before execution for deterministic payloads. Late conflicts preserve the
completed device/interface writes and stop without a success summary. Snapshots are
read-only during tests. After extraction, 82 focused tests pass and one skips.
AST comparison restores all original applier functions/classes after inlining writes.
Error/fatal lint passes. Full pytest on Windows/Python 3.14: 1968 passed,
485 skipped, one existing Starlette warning. Linux/database/opt-in skips are not
deployment acceptance.
Local evidence: `artifacts/host-writes-evidence-20261019.zip`.
Selectel remains experimental; no production access or deployment changes.

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

## VM apply: target preparation and inventory

Extracted `prepare_vm_apply_inventory` from `apply_virtual_machines`, starting
from main `4fbafab264fea97aef043019f0a589ce1db8ed6a` (PR #37).
The helper retains prerequisite lookup order, cluster name/explicit-ID selection,
site and cluster-type validation, and independent eager all-VM/cluster-VM reads.
Existing prerequisite and cluster-resolution helpers remain injected from the
original module. Discovery, preflight, native-disk handling, reports, confirmation
and writes remain in the caller; LXC behavior is unchanged.

Eleven characterization tests passed before extraction and cover read order,
independent selections, explicit cluster mapping, prerequisite failures, scope/type
mismatches, duplicate clusters and read failures before discovery or writes.
The focused suite passed 61 tests after extraction. AST comparison after inlining
the helper confirms unchanged original function and class bodies.
Selectel remains experimental; this change does not deploy to production.

Full suite: 1979 passed, 485 skipped, one existing Starlette deprecation warning.

## LXC apply: target preparation and inventory

Extracted `prepare_lxc_apply_inventory` from `apply_lxc_containers`, starting
from main `963a2f22d5bfe17d2693502348ef7eb26d4e5504` (PR #38).
The helper retains site lookup, cluster name/explicit-ID selection and site scope
validation without adding VM-style cluster-type checks. It reads the global VM
inventory once and derives target membership using the original `cluster.id`
attribute comparison, preserving record references and order. Existing error
class and cluster-filter callback remain available in the original module.
Discovery, identity checks, reports, confirmation and writes remain in the caller.

Sixteen characterization tests passed before extraction, covering read order,
explicit selection, object/dictionary/missing cluster relationships, target
failures and read errors before discovery or writes. The focused suite passed
47 tests after extraction. Original function/class ASTs match after inlining the
helper; error/fatal lint checks passed. VM behavior is unchanged, Selectel remains
experimental, and no production deployment is included.

Full suite: 1995 passed, 485 skipped, one existing Starlette deprecation warning.

## Workload application stages

After PR #39, VM and LXC application each have separate preparation, preflight,
precheck report and write modules. The public appliers retain confirmation and
orchestration. Existing helper callbacks preserve patch points and error classes.
VM sorting, duplicate-name checks, aggregated blocked reports and native-disk
suppression remain distinct from LXC input-order processing and immediate refusal.
Seventeen new baseline tests cover exact output/payloads, replay, confirmation,
partial write failures and native disks; 64 focused tests pass. AST round-trip
comparison verifies unchanged executable bodies after inlining all six helpers.

## Completion scope for the remaining structural pass

1. Finish VM/LXC application stages (above).
2. Separate remaining read-only planning and disappearance responsibilities.
3. Review provider discovery boundaries, extracting mixed conversion responsibilities
   where useful without merging provider-specific rules.
4. Audit maintained entrypoints, scripts, compatibility paths and documentation;
   record retention decisions and final verification. Do not remove code solely
   because static search finds no direct caller.

Already separated preflight/write modules may remain long when they implement one
ordered safety policy. Registration functions containing nested API routes are not
split merely to meet a line-count target. This pass preserves behavior and excludes
Selectel feature completion, unrelated bug fixes and production deployment.
