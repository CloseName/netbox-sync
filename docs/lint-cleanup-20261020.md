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
