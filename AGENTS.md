# Working agreement

Read this file before changing code or proposing deployment commands. Read
[development](docs/development.md) and the relevant current contract in the
[documentation map](docs/README.md). Before operational work also read
[test operations](docs/operations/test.md) or
[production operations](docs/operations/production.md). These environment-specific
guides take precedence over historical examples for this installation.

- Start a focused `codex/` branch from freshly fetched main. Preserve unrelated
  local work. Do not assume that a previous chat merged, tested or deployed code.
- Preserve existing behavior unless the user explicitly requests a change.
  Keep intentional VM/LXC and planner/writer differences. Follow existing module
  boundaries; do not grow orchestration modules with provider-specific policy.
- For bug fixes add a regression test reproducing the failure; for extractions
  characterize behavior first. Run affected checks and the applicable verification
  baseline. Report exact results, skips and limits; absent CI is not passing CI.
- Use separate reviewable PRs; group related changes. Merge or deploy only within
  the user's authorization. A merge never implies a deployment.
- Production is out of scope unless explicitly authorized for the specific change.
  Never infer production hosts, paths, credentials or NetBox/NetBoxCE roles.
- Test schedules remain off. Never use an unrestricted `compose up`, enable the
  timer, or resume Selectel schedules as a side effect of an update.
- Selectel remains experimental. Read [status](docs/selectel-status.md) before work;
  preserve uncertain-outcome protection and explicit reconciliation boundaries.
- Use the reviewed on-disk test updater, not generated heredoc deployment blocks.
  Child processes must not consume the script's input. Successful build/migration
  is not deployment success: verify running images, HTTPS and scheduler state.
- Do not print or commit secrets, full environment dumps, private backup contents,
  tokens or credentials. Never prune Docker data or delete old releases/backups
  as a routine update step.
- Update the maintained contract/runbook when behavior changes. Dated evidence is
  historical, not a current deployment inventory. If required documentation or
  environment evidence is unavailable, say so before giving executable operations.

For new chat setup use [project instructions](docs/operations/chat-project.md).
Do not assume all chat clients automatically load GitHub AGENTS.md files.
