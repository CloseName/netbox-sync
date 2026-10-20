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
