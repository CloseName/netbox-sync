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
