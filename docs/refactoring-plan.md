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
