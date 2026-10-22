# Production operations: discovery required

Production is not changed by this PR or by the test updater. No production update
command is prescribed here until the actual topology has been verified.

The operator reports working production and two servers described as NetBox and
NetBoxCE. The exact role mapping, Sync host, current releases, paths, Compose
projects, database placement and backup/recovery state are NOT established by
this runbook. A production UI at `netbox.indeed-id.hq` and its `esxi_events` field
were shown on 22 October 2026; that is not authorization or a fresh infrastructure
inventory. Do not infer SSH targets from that URL.

Before proposing production commands, collect read-only, secret-free evidence:

1. Identify each server's role and which Sync writes to which NetBox URL/Guard instance.
2. Record running image tags/IDs, current release, Compose working-directory labels,
   ingress mode and service ownership. Check configuration without disclosing tokens.
3. Establish current schedule/worker state, running or pending jobs, maintenance window,
   backup procedure and restore capability for each database and configuration set.
4. Compare the reviewed release and migrations with the installed version. Decide
   separately whether Sync, Guard or NetBox itself needs updating. Do not update
   both merely because the repository contains both components.
5. Record successful test acceptance for that release and obtain explicit authorization
   for the concrete production change and any subsequent schedule resumption.

The older [two-host procedure](../production-two-host-update.md) is a reference for
its recorded topology, not evidence that its host/path assumptions apply now.
Its resume step activates schedules. Do not execute it as a generic update recipe.

Rollback must account for database migrations and any completed writes. An image
downgrade alone is not data rollback. Preserve failed-run evidence and backups;
never automatically restore a live database or replay an uncertain import.
