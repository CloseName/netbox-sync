# Selectel: experimental status

Status recorded 19 October 2026. This integration is not accepted for production.
The repository consolidation is separate from any production deployment.

## Known limitations

- The test installation reported an unconfirmed import for two accounts. Some
  writes may have committed. The screenshot does not identify the underlying
  exception or prove a matching failure; reconcile the original run in NetBox
  before considering a new import.
- Native resource matching and dedicated server port-to-NIC identity remain under
  investigation. See [port evidence](selectel-port-evidence.md) and
  [outstanding work](selectel-backlog.md).
- The GitHub integration run for 11a48eb failed in the native Selectel scenario:
  `provider_placement.ensure` raised `DependencyGuardBlocked: PERMISSION_DENIED`
  while creating a Region. This is an open native-import acceptance failure,
  not evidence of successful end-to-end integration.

## Existing execution boundaries

- Collection needs explicit account credentials and a configured importer token.
- A missing schedule defaults to off. Account disable blocks new collection;
  it does not cancel an already running write.
- `IMPORT_UNCONFIRMED` and `RUN_INTERRUPTED` block manual collection and scheduled
  retries. Do not clear these states merely to obtain a green UI.
- Native reconciliation requires the explicit Guard configuration
  `selectel_native_reconcile = True`; it must not be enabled as part of repository
  consolidation.
- No production services, schedules, configuration or data are changed by this
  documentation update. No completion or production acceptance is claimed.

## Local work reviewed during consolidation

The three local Selectel evidence/backlog updates are retained. The future product
architecture and its Map decision link are retained as future plans, not runtime
requirements. The separate early `netbox_sync/selectel/` reconnaissance prototype,
its probe files and tests are preserved in the original local working directory;
they are not installed alongside the newer collector in `tools/selectel_audit`.
The local production inventory remains local because it contains deployment details;
its 11 October records are historical evidence, not a fresh version check.
