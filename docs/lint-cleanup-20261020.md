# Lint cleanup — 2026-10-20

## Stage 1: formatting

Format `netbox_sync` with Black 25.1.0, a 120-character target and Python 3.10
syntax compatibility. The formatter is pinned in development requirements and
configured in pyproject.toml. All 225 changed modules have exactly the same AST
before and after formatting, including string constants; no operator behavior,
exception flow or public signature was changed.

This removes packed statements and most avoidable long lines. Runtime/platform
inference, imports and remaining maintainability findings are separate stages.
Do not reduce the existing Pylint 9.0 threshold or suppress real runtime errors
merely to improve the score. Selectel remains experimental; no deployment occurs.

## Stage 2: runtime contracts and analyzer environment

Declare transaction-owned mixin fields and dynamically installed PlanningNetBox
names without initializing new runtime values. Initialize the optional discovery
review before provider dispatch; bind each health-check UID to its callback.

Keep Pylint Error/Fatal findings fatal independently of the style score. The
platform allowlist names only actual POSIX members used by Linux workers and
external NetBox/Django imports installed by the guard image. An executable lint
probe verifies that a misspelled POSIX name and a missing application import still
fail. Explicitly document individual Pylint 3.3.4 inference limitations after
isinstance guards and on validated Pydantic/database values; no global no-member
or import-error disable is used.

Full analysis at this stage has **zero Error/Fatal findings**, score **8.87/10**.
The unchanged 9.0 threshold is not met yet; remaining style cleanup is next.

## Stage 3: safe style cleanup and the restored gate

Replace 118 builtin `dict()`/keyword-only constructions with literals. Do not
rewrite positional or unpacked constructors, whose validation can differ. Split
long literal strings with exact constant-value preservation, including SQL and
public messages. Add module-purpose docstrings. Remove unused internal imports;
keep documented/previously preserved import aliases, with a regression test for
alias identity. Keep evaluation of unused prerequisite lookups under explicit
underscore names instead of deleting those checks.

Normalized AST comparisons of all 83 changed modules allow only dict-literal
syntax, unused local names, reviewed imports and documentation differences.
Focused output/payload and compatibility tests pass. Black check is now part of
Forgejo CI alongside the existing Pylint and test commands.

The original command `pylint --fail-under=9.0 --max-line-length=120 netbox_sync`
now passes with **9.02/10**, **zero Error/Fatal findings**, without lowering the
threshold. This is a passing project gate, not a claim of zero recommendations.
The full report still contains 186 warnings, 553 refactoring recommendations and
1149 conventions. Their principal remaining groups are function/class docstrings,
complexity/argument counts, intentional lazy imports, exact-type checks and
cross-module private access. Do not replace `type(x) is int` with `isinstance`
where rejecting booleans/subclasses is part of validation. Do not merge differing
VM/LXC safety policies merely to satisfy a duplicate-code recommendation.

Broad exception boundaries close worker/authentication/transport failures;
changing their coverage requires separate behavioral review. Historical public
aliases remain available. The lint report is an ongoing maintenance input; the
existing aggregate gate intentionally permits these recommendations while making
runtime errors fatal. No global complexity/docstring/typecheck disable was added.

Final full suite: 2036 passed, 485 skipped, one existing Starlette warning.

## Stage 4: virtual disk planning

Separate one VM's disk validation and payload preparation from batch orchestration
and confirmed writes. Both functions now document their contracts. Preserve the
original inventory snapshot, lookup and validation order, identity fallback,
decimal MB rounding, unrelated custom fields and retention of missing disks.
This is a VM-only path; it does not introduce a shared VM/LXC disk policy.

Fifteen characterization cases were added and passed before extraction. They
cover late failures with no partial writes, preview validation, conflict error
precedence, zero/boundary capacities and custom field preservation. Together with
the existing disk tests, all 26 focused cases pass before and after extraction.
The module no longer has missing-function-docstring, too-many-locals or
too-many-branches findings. The compatibility parameter and unpacked dict
construction remain unchanged.

Full suite: 2051 passed, 485 skipped, one existing Starlette warning. Black check
passes; full Pylint is 9.02/10 with zero Error/Fatal findings.

## Stage 5: VM/LXC application contracts

Document the entry points, prerequisite errors, inventory readers, preflight,
reports and writes in ten modules. Describe actual VM/LXC differences: endpoint
filtering versus attribute-based cluster membership, sorted VM processing versus
LXC discovery order, native VM disk protection, delayed blocked VM reports versus
immediate LXC preflight failures, and differing skip output.

The write helpers require confirmation/preflight from their callers and do not
roll back a successfully applied prefix after a later transport failure. These
contracts are explicit rather than implied by helper names.

AST comparison allowing only docstrings and removal of two redundant exception
class `pass` statements verifies that runtime logic is unchanged. All 17 existing
workload output, payload, replay and failure-prefix
tests pass; Black passes. The full suite result in stage 4 is the unchanged-code
baseline, not a second full run for this documentation-only change.

Full Pylint passes at 9.02/10 with zero Error/Fatal findings; no global suppressions
or threshold changes are introduced.

## Stage 6: VM network preflight

Separate NIC metadata, MAC ownership, scoped IP validation, primary IPv4 policy
and one-VM context preparation. The public batch entry point retains host/VM
order and rejects duplicate discovered MACs before duplicate discovered IPs,
after all per-VM checks. Keep stable-interface MAC rotation, structured
ManagedMACConflict details and preservation of a manual primary owned by the VM.
Do not substitute LXC's stricter primary-MAC policy.

Eleven new characterization cases pass on the original implementation and after
extraction, including competing failures and structured MAC error attributes.
All 73 focused preflight/report/write/bootstrap tests pass. AST comparison
confirms original private helpers and extracted MAC/IP control flow are unchanged.
The module has no branch, statement, local-variable or nesting complexity findings.

Full suite: 2062 passed, 485 skipped, one existing Starlette warning. Full Pylint
passes at 9.03/10 with zero Error/Fatal; Black and whitespace checks pass.

## Stage 7: LXC network preflight

Separate LXC NIC metadata, MAC ownership/primary-MAC refusal, scoped IP validation
and one-container context preparation. Retain global identity lookup followed by
cluster validation, sorted duplicate-name messages, discovery order and MAC-before-IP
batch duplicate errors. Unlike VM preflight, LXC still refuses primary-MAC rotation
and does not validate the existing primary IPv4 during preparation.

Thirteen new characterization cases pass before and after extraction, covering
competing cluster, MAC ownership, primary-MAC and IP failures in preview and confirmed
runs. All 67 focused inventory/preflight/report/write tests pass. AST comparison
confirms unchanged existing helpers and extracted NIC/MAC/IP control flow. Both
network preflight modules now have no branch, statement, local-variable or nesting
complexity findings, without suppressing those checks.

Full suite: 2075 passed, 485 skipped, one existing Starlette warning. Full Pylint
passes at 9.03/10 with zero Error/Fatal; Black and whitespace checks pass.

## Stage 8: guest placement

Separate VM/LXC identity resolution and placement ownership/cluster validation
from batch preparation and confirmed writes. Document unmanaged-host skipping,
VM-before-LXC order, the already-assigned fast path and partial write failures.
Preserve the existing architecture-attribute dispatch and source-instance ownership
check rather than inventing a common guest identity policy.

Eighteen characterization cases pass before and after extraction. They cover
preview, confirmed payload/order, replay, ambiguous or missing identities,
ownership-before-cluster failures, whole-batch validation, and write failure
propagation without rollback. The placement module no longer has complexity or
missing-function-docstring findings; compatibility arguments and lazy imports remain.

Full suite: 2093 passed, 485 skipped, one existing Starlette warning. Full Pylint
passes at 9.03/10 with zero Error/Fatal; Black and whitespace checks pass.

## Stage 9: source team metadata validation

Extract name/create/rename validation and source assignment into helpers operating
only on the pending copy. Keep authorization, metadata version, exact integer
revision checks, encoded-size limit, commit and audit in their original order.
Document detached responses, casefold uniqueness, creation-only team limits and
revision advancement on an unassignment that changes no assignment.

Ten new characterization cases and all nine existing team cases pass before and
after extraction. Expanding the helper AST back into the entry point exactly
matches the original function after removing its docstring. The module has no
complexity or missing-function-docstring findings. Keep the exact-type check:
accepting booleans as revisions would change the protocol.

Full suite: 2103 passed, 485 skipped, one existing Starlette warning. Full Pylint
passes at 9.04/10 with zero Error/Fatal; Black and whitespace checks pass.

## Stage 10: Proxmox guest-agent network parsing

Separate the guest-agent read/parse boundary from configured QEMU NIC creation.
Keep the original partial-result behavior: completed interface entries survive a
caught error, the current partial entry is discarded, and later entries are not
processed. Preserve duplicate-MAC replacement, address filtering and permissive
prefix formatting. Do not introduce stricter address validation during refactoring.

Document QEMU/LXC NIC and disk contracts, including static LXC IPv6 and the
different disk selection rules. Eleven new characterization cases pass before
and after extraction; all 47 focused component/discovery tests pass. Expanding
the helper AST reproduces the original four provider functions, excluding docs.
Branch/local-variable and missing-function-docstring findings are removed; the
existing dependency-injection signature and its argument-count recommendation
remain unchanged.

Full suite: 2114 passed, 485 skipped, one existing Starlette warning. Full Pylint
passes at 9.04/10 with zero Error/Fatal; Black and whitespace checks pass.

## Stage 11: network scope observations

Separate inventory evidence indexing, MAC conflict annotations, IP conflict
annotations and guest iteration. Keep scope selection, VRF verification and
deep-copy behavior in the entry point. Document exact-type selectors, inventory
read order, malformed evidence errors and differing ambiguous-NIC handling:
IP observations reset while existing MAC observations remain for executor refusal.

Fifteen new VM/LXC characterization cases pass before and after extraction.
All 42 scope/observation tests, including local HTTP integration scenarios, pass.
AST comparison confirms unchanged rule/value helpers and extracted evidence,
MAC and IP blocks. Retain mask/VRF conflicts, ID ordering and read-only behavior;
no provider apply policies or global lint suppressions are changed.

Full suite: 2129 passed, 485 skipped, one existing Starlette warning. Full Pylint
passes at 9.04/10 with zero Error/Fatal; Black and whitespace checks pass.
No complexity or missing-docstring findings remain in network_scopes.


## Stage 12: lifecycle capability dispatch

Split exact-envelope handlers by capability, keeping the source/evidence gates
and closed exception boundary in the dispatcher. Preserve retirement availability
precedence, archive/resume flags and credential callback identity. Recovery reads
remain separate from transitions. No complexity findings remain in this module.

70 new characterization cases pass before and after extraction. Full suite:
2199 passed, 485 skipped, one existing Starlette warning. Pylint: 9.05/10 with
zero Error/Fatal; Black and whitespace checks pass. The complete remaining work
is tracked in [completion status](lint-completion-status.md), not declared finished.


## Stage 13: catalog query dispatch

Separate bounded catalog capabilities within the existing pinned-DNS/TLS session.
Extract complete evidence pagination and configured identity target resolution.
Retain count checks, local offsets, closed responses and never follow remote next
URLs. Nine new malformed-page cases pass before and after extraction; 70 focused
catalog/recovery/placement tests pass. No complexity or missing-doc findings remain
in netbox_catalog. Full suite: 2208 passed, 485 skipped, one existing Starlette
warning. Pylint 9.05/10, zero Error/Fatal; Black and whitespace pass.

## Stage 14: authorization dispatch

Separate enrollment, login, authenticated capabilities, policy updates and receipt
operations. Preserve session/refusal precedence, throttle accounting, LDAP routing,
rollback and the intentional ability to cancel an expired receipt. Fourteen new
characterization cases pass before and after extraction; focused tests: 86 passed,
one platform skip. Full suite: 2222 passed, 485 skipped, one existing Starlette
warning. Pylint 9.06/10, zero Error/Fatal. Public positional constructor arguments
remain compatible; its argument-count recommendations are intentionally retained.

## Stage 15: directory settings preparation and persistence

Extract endpoint-bound secret reuse and tested-settings persistence from directory
administration. Preserve early disable/revoke paths, exact-int revisions, test proof
expiry and identity-change invalidation. Six new cases pass on the original code
and after extraction; focused suite: 92 passed, one platform skip. No complexity or
missing-doc findings remain in directory_auth. Full Pylint: 9.07/10, zero Error/Fatal.
Full-suite retry: 2228 passed, 485 skipped, one existing Starlette warning. The first
run hit a Windows temporary-directory rename PermissionError in a backup test;
that case and then the entire suite passed unchanged on retry. Black passes.

## Stage 16: isolated setup operations

Extract setup-token identification, fixed custom-field POST and exact-token revoke.
Keep post_sent in the outer session boundary, including session-exit failures.
Sixteen new cases cover token mismatches, lookup failures, POST response classes
and pre-send/post-send errors; 42 focused tests pass on main and after extraction
(14 platform skips). Full suite: 2244 passed, 485 skipped, one existing warning.
Pylint: 9.07/10, zero Error/Fatal. No complexity or missing-doc findings remain in
bootstrap_setup_probe. Black and whitespace checks pass.

## Stage 17: discovery and API contract documentation

Add 38 descriptions across discovery records and public DTOs, including provider
identity differences, secret exclusion, confirmation semantics and coherent results.
Move two existing misplaced descriptions ahead of fields. Executable AST is
unchanged; all 52 API model schemas match after removing description metadata.
Existing focused suite: 132 passed before and after. Full lint: 9.09/10, zero
Error/Fatal; missing-doc findings reduced to 98 classes and 384 functions. Black
and whitespace checks pass. Full suite was green immediately before this
pure documentation change (2244 passed, 485 skipped).

## Stage 18: host primary-IP checks and writes

Separate source-owned management target resolution from writes using a private
validated target record. Preserve per-host order, manual primary retention, exact
assignment/prefix checks, ambiguity refusals and idempotence. Three new ambiguity
cases pass before and after extraction; focused suite: 47 passed. Full suite:
2247 passed, 485 skipped, one existing warning. Pylint: 9.09/10, zero Error/Fatal;
changed module: 10/10. Black and whitespace checks pass.

## Stage 19: control API contracts and lifecycle client documentation

Describe bootstrap/authentication inputs and projections, recovery/retirement
confirmations, administrator identity checks and bounded lifecycle RPC methods.
56 descriptions added, including constructors. Executable AST and 25 model schemas
are unchanged apart from documentation metadata. Focused suite before and after:
95 passed, 27 platform skips, one existing warning. Full Pylint: 9.12/10, zero
Error/Fatal. Remaining missing docs: 68 classes and 360 functions. Black and
whitespace pass. Last full executable-code suite: 2247 passed, 485 skipped.

## Stage 20: placement resolution stages

Separate request validation, site selection, host-type resolution and cluster
matching. Keep catalog lookup/projection/creation callbacks distinct, retain
query order and refuse automatic preparation without a selected site. Eight new
cases pass before extraction; all 50 focused tests pass after. Full suite: 2255
passed, 485 skipped, one existing warning. Pylint: 9.12/10, zero Error/Fatal;
no complexity or missing-doc findings remain in placement_resolution. Black and
whitespace pass. Exact integer checks still reject boolean IDs/counts.

## Stage 21: bounded diagnostic projections and classification

Separate phase, HTTP and frame filtering, preserving exact integer checks and
truncation before filtering. Extract connection classification while keeping
explicit codes, HTTP statuses and named provider errors in their original order.
Twenty-two new cases pass on main; focused suite: 55 passed. Full final suite:
2277 passed, 485 skipped, one existing warning. Pylint 9.12/10, zero Error/Fatal;
no complexity or missing-doc findings remain in worker_failure. Black and whitespace
pass. Unknown stage values are not consulted before a known provider fault matches.

## Stage 22: guard transport and scheduled diagnostic documentation

Add 28 descriptions covering guard protocol validation, request uncertainty,
receipt formats, bounded diagnostic fields and scheduled context lifetime.
Executable AST unchanged. Focused tests: 90 passed before and after. Full Pylint:
9.13/10, zero Error/Fatal. Missing docs remaining: 63 classes and 337 functions.
Black and whitespace pass. Last full executable-code suite: 2277 passed, 485 skipped.

## Stage 23: NetBox bootstrap probe stages

Extract per-endpoint token/permission checks, guard capability checks and prerequisite
inventory checks. Keep active read/apply attribution, access evidence ordering,
closed exceptions and token reads at the same points. Six new cases pass before
extraction; focused suite: 66 passed, 31 skipped. Full suite: 2283 passed, 485 skipped,
one existing warning. Pylint 9.14/10, zero Error/Fatal; no complexity or missing-doc
findings remain in bootstrap_probe. Black and whitespace pass.

## Stage 24: prerequisite journal execution stages

Separate ephemeral token validation, revision/plan fencing and the journaled
execution loop. Retain marker-before-POST ordering, stop statuses, reconciliation,
revocation and final cleanup. Six new scenarios pass before extraction, each also
registered for the protected Linux fixture. Focused suite: 72 passed, 37 skipped.
Full suite: 2289 passed, 491 skipped, one existing warning. Pylint 9.15/10, zero
Error/Fatal; no complexity or missing-doc findings remain in bootstrap_setup.
Black and whitespace pass. The six added skips are Linux fixture variants, not
accepted deployment evidence.

## Stage 25: bootstrap command dispatch

Separate provider, catalog and state/preparation capabilities. Preserve exact
envelopes, lock scope, catalog read slots and registration intent ownership.
All 29 new cases pass on main and after extraction. Full suite: 2318 passed,
491 skipped, one existing warning. Pylint 9.15/10, zero Error/Fatal; no control-flow
complexity or missing-doc findings remain in bootstrap_worker. Keep its single
public callable entry point; a second public method would unnecessarily widen its
interface merely to satisfy a class-size metric. Black and whitespace pass.

## Stage 26: bootstrap state file checks and contracts

Split file type/link/size checks from POSIX owner/mode checks without changing
short-circuit refusal order or descriptor cleanup. Seven new fake-descriptor cases
pass before extraction. Add 11 descriptions of state persistence and transitions;
the documentation itself preserves executable AST. Full suite: 2325 passed,
491 skipped, one existing warning. Pylint 9.16/10, zero Error/Fatal; no complexity
or missing-doc findings remain in bootstrap_state. Black and whitespace pass.

## Stage 27: local control transport

Separate peer request handling and serial maintenance startup from the socket
server. Preserve authentication before parsing, closed error codes, fork behavior,
send-failure handling, directory lock lifetime and maintenance failure logging.
Eleven fake-socket/process cases pass on main and after extraction. Full suite:
2336 passed, 491 skipped, one existing warning. Pylint 9.16/10, zero Error/Fatal;
control-flow and missing-doc findings resolved in local_control. Retain the public
serve argument list for caller compatibility. Black and whitespace pass.

## Stage 28: hardware identity and host mapping documentation

Add 14 descriptions covering normalized system identifiers, observation freshness,
provider coverage, conflict classification and reviewed-versus-legacy mappings.
Executable AST unchanged. The same focused suite passes before and after:
90 passed, 52 skipped, one existing warning. Pylint 9.17/10, zero Error/Fatal;
Black and whitespace pass. Previous full runtime baseline remains 2336 passed.

## Stage 29: host device conflict checks

Separate management-IP lookup and unowned-device refusal from stable identity
resolution. Preserve duplicate-identity precedence, IP-before-name refusal and
site validation. Ten new cases pass before extraction; 42 focused tests pass
afterward. Full suite: 2346 passed, 491 skipped, one existing warning. Pylint
9.17/10, zero Error/Fatal; control-flow/doc findings resolved in netbox_apply.
Its legacy device-change helper signature remains compatible. Black and whitespace
pass. VM/LXC selection rules and Selectel ownership remain unchanged.

## Stage 30: runtime contract documentation

Add 73 descriptions across 28 modules: authorization persistence, secret access,
TLS trust, scheduling, identifiers, metadata and VM/LXC planning/apply entry points.
Descriptions explain existing boundaries and VM/LXC differences. Executable AST
unchanged for every file. Full suite before and after: 2346 passed, 491 skipped,
one existing warning. Pylint 9.19/10, zero Error/Fatal. Black checks all 227 Python
files; whitespace passes. No algorithm, public signature or payload change.

## Stage 31: VM/LXC network precheck report stages

Extract per-interface printing and the VM primary-IP decision from the report
entry points. Keep separate VM/LXC counters and output, including manual-primary
preservation versus LXC primary-candidate counts. Two new generator/repeated-call
cases and all 32 golden output cases pass before and after extraction. Full suite:
2348 passed, 491 skipped, one existing warning. Pylint 9.19/10, zero Error/Fatal;
no findings remain in either report module. Black and whitespace pass.

## Stage 32: application and API contract documentation

Add 68 descriptions across 20 API/application modules, covering reviewed catalog
selections, registration/recovery bindings, planning overlays and scheduling.
Executable AST unchanged. All 13 affected Pydantic schemas are identical after
excluding description metadata. Full suite before and after: 2348 passed,
491 skipped, one existing warning. Pylint 9.23/10, zero Error/Fatal. Black and
whitespace pass. Selectel descriptions explicitly retain experimental status.

## Stage 33: host network planning report stages

Separate management-interface lookup and interface/VLAN/address reporting while
keeping the original lookup order, reference-only policy and exact output. Four
new scoped/ambiguous/missing network cases pass before extraction together with
13 golden report cases. Focused post-change suite: 29 passed. Full suite: 2352
passed, 491 skipped, one existing warning. Pylint 9.23/10, zero Error/Fatal; no
complexity or missing-doc findings remain in netbox_planner. Black and whitespace
pass. Planning keeps its existing differences from the write path.

## Stage 34: worker and inventory contract documentation

Add 87 descriptions across 33 modules covering worker boundaries, scoped
registration/placement evidence, discovery snapshots, guarded creation and
read-only reports. Executable AST unchanged for each file. Full suite before
and after: 2352 passed, 491 skipped, one existing warning. Pylint 9.27/10, zero
Error/Fatal. Black checks all 227 Python files; whitespace passes.

## Stage 35: bounded diagnostic and conflict collection

Extract one child progress-record projection and one interface conflict collector.
Preserve exact-integer bounds, newest-64 retention, discarded partial lines,
per-interface deduplication, scope evidence and distinct VM/LXC identity namespaces.
Sixteen new cases and 11 existing inventory cases pass before and after extraction.
Full suite: 2368 passed, 491 skipped, one existing warning. Pylint 9.27/10, zero
Error/Fatal; no nested-block findings remain anywhere in the package. No control-flow
findings remain in either changed module. ConflictParticipant retains its public
serialized fields; reducing their count would change the API evidence contract.
Black and whitespace pass.

## Stage 36: VM/LXC network write stages

Split interface, MAC, IP and primary-IPv4 writes into small provider-specific
functions. Preserve output, VRF payloads, mutation order, per-run counters and
the VM manual-primary rule versus LXC replacement behavior. Ten new reused-record
failure cases plus 58 existing write/report cases pass before and after extraction.
Full suite: 2378 passed, 491 skipped, one existing warning. Pylint 9.28/10, zero
Error/Fatal; no findings remain in either network write module. Black and
whitespace pass.
## Stage 37: lifecycle and operation journal documentation

Add 66 descriptions across 17 modules covering lifecycle transitions, durable
journals, registration, worker supervision and inventory prerequisites. Executable
AST unchanged in every file. Full suite: 2378 passed, 491 skipped, one existing
warning. Pylint 9.31/10, zero Error/Fatal. Black checks all 227 Python files;
whitespace passes. Remaining documentation: 12 classes and 90 functions.
## Stage 38: host write stages

Extract device, interface, address and primary-address stages with local counters.
Two new multi-host ordering cases pass with 20 existing write/preflight cases before
and after extraction. Preserve late conflict failures and already completed writes.
Full suite: 2380 passed, 491 skipped, one existing warning. Pylint 9.31/10, zero
Error/Fatal. No control-flow or documentation findings remain in host_apply_writes;
its existing public arguments remain for caller compatibility. Black and whitespace
pass.
## Stage 39: registration and recovery contracts

Add 77 descriptions across eight modules: durable registration, legacy admission,
identity verification, recovery, retirement, directory access and catalog creation.
Executable AST unchanged for every file. Full suite: 2380 passed, 491 skipped,
one existing warning. Pylint 9.34/10, zero Error/Fatal; Black checks all 227 modules.
Remaining documentation: three classes and 42 functions. Whitespace passes.
## Stage 40: retained legacy network write stages

Separate legacy guest address selection, address/prefix writes and VLAN attachment.
Five new cases pin interface-name priority, historical last-octet prefix derivation,
empty-list failure timing and absent-address behavior. They and seven existing
mutation-trace cases pass before/after. Full suite: 2385 passed, 491 skipped, one
existing warning. Pylint 9.34/10, zero Error/Fatal; no complexity or documentation
findings remain in legacy_netbox_writes. Black and whitespace pass. Legacy behavior
is intentionally not replaced with modern VM/LXC rules.
## Stage 41: complete provider contract descriptions

Add 49 descriptions in 11 pfSense and experimental Selectel modules. Executable
AST unchanged in all files. Full suite: 2385 passed, 491 skipped, one existing
warning. Pylint 9.36/10, zero Error/Fatal; no missing class or function descriptions
remain. Black checks all 227 modules; whitespace passes. Complexity audit remains
open: 32 branch, 26 statement, 74 local-variable, 14 return and 32 boolean-expression
findings, plus argument/record-shape compatibility metrics. Counts overlap.
## Stage 42: pfSense preview stages

Separate runtime address/detail parsing, snapshot metadata, target validation,
configured-interface projection, matching and VLAN projection. Preserve input
bounds, exception boundaries, matching priority and source order. Ten new edge
cases plus 28 existing preview/IPAM cases pass before/after. Full suite: 2395
passed, 491 skipped, one existing warning. Pylint 9.37/10, zero Error/Fatal; no
complexity/doc findings remain in pfsense_preview. Exact integer checks intentionally
reject booleans. Black and whitespace pass.
## Stage 43: per-source execution isolation

Separate one source execution from input validation and deterministic iteration.
Preserve audit start/finalization behavior, diagnostic context cleanup, SystemExit
isolation and clock ordering. Two new generator/clock cases and 25 existing
orchestration/scheduled cases pass before/after. Full suite: 2397 passed, 491 skipped,
one existing warning. Pylint 9.37/10, zero Error/Fatal; control-flow/doc findings
resolved in orchestrator. SourceRunResult retains its public execution/history
fields consumed by entrypoint reporting and scheduler results. Black and whitespace
pass.
