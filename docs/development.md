# Development

## Change workflow and architecture

Read [AGENTS.md](../AGENTS.md) and the [current module map](refactoring-completion-20261020.md)
before choosing where to implement a change. The map describes the structural
refactoring; confirm current call sites rather than copying historical snippets.

- Entry points and API routes orchestrate; collectors read provider data; preparation,
  matching, policy, reports and writes belong in their existing focused modules.
- Planning is read-only. Reuse proven pure transformations where semantics match;
  never invoke live writer code from a planner or normalize away intentional
  VM/LXC ordering, validation, addressing or conflict-handling differences.
- Preserve source ownership, confirmation/digest checks, permission boundaries,
  retained missing objects and uncertain-write handling. Do not make retries of
  uncertain writes automatic. UI counters and enabled actions must agree without
  changing the canonical plan. Timestamp-only observations do not enable manual sync.
- Add a regression/characterization test before the fix/extraction. Test externally
  visible behavior and failure paths, not just helper call counts. Keep performance
  work bounded and cover large inventory behavior without contacting live providers.
- Fetch main, inspect local changes, branch, implement a coherent change, run checks,
  and open a PR describing behavior, validation and remaining limitations. Verify
  the expected head before an authorized merge. Do not silently fix unrelated bugs
  inside a behavior-preserving extraction.
- Review whether new helpers clarify ownership rather than merely shrinking function
  length. Do not waive lint rules or duplicate implementations to bypass the design.

For Selectel start with [experimental status and implementation rules](selectel-status.md),
then the linked design/backlog for the affected capability. A passing mocked test
does not establish native-import, matching or production acceptance.

## Local checks

Use Python 3.12 (current image) or 3.13 (current CI). Keep the production CLI
entrypoint and existing tests intact. From repository root:

```sh
python -m pip install -e .
python -m pip install -r requirements-dev.txt
pytest -q
python -m black --check netbox_sync
pylint --fail-under=9.0 --max-line-length=120 netbox_sync
git diff --check
```

Alembic/SQLAlchemy are installed by requirements-dev.txt for development and by
requirements-migrations.txt in the canonical Dockerfile.web image for explicit
operator commands. Migration revisions ship in the repository; invoke
them from that checkout, not from a separately installed legacy PyPI package.
Package discovery explicitly includes only `netbox_sync*`, preventing deploy
and migration directories from becoming accidental Python distributions.

Normal tests use fakes, never a production source or NetBox. Live ESXi and
PostgreSQL tests remain opt-in. See [WEB-1 development and deployment](web.md)
for the optional API/frontend, and [architecture](architecture.md) and
[migrations](migrations.md) for runtime and database boundaries.

Before a refactoring PR, follow the [verification baseline](verification-baseline.md).
See the [documentation map](README.md) for historical reports and current guides.

The [lint cleanup report](lint-cleanup-20261020.md) records platform allowances,
compatibility exports and the unchanged score threshold. Error/Fatal findings
fail independently of the aggregate score. Format code with `python -m black netbox_sync`.
