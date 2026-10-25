# Selectel: experimental status

Status recorded 19 October 2026. This integration is not accepted for production.
The repository consolidation is separate from any production deployment.

For the refreshed code trace, read-only test evidence and remaining acceptance
boundaries see [25 October diagnosis](selectel-diagnosis-20261025.md).

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

### Native creation permission correction (25 October 2026)

Read-only operator diagnostics reproduced a model/object permission mismatch:
the dedicated non-superuser importer has `dcim.add_region` and `dcim.add_site`,
but NetBox denies these permissions against unsaved Region/Site instances.
The Selectel writer previously checked only the unsaved object, blocking creation.
Selectel now checks the model grant, validates and provisionally saves the object,
then checks the full object permission inside an atomic savepoint. Constraint
denial rolls back the row; the enclosing account transaction still owns inventory,
bindings, provenance and the final receipt. The shared Guard helper and other
providers are unchanged. A model grant alone never authorizes committed creation.

This is a reproduced current blocker, not a proven explanation of every historical
`IMPORT_UNCONFIRMED`. No account state is cleared by the correction. Native import
acceptance still requires disposable NetBox constraint/rollback tests and a separately
authorized test deployment/run.

### Rules for future implementation

Keep collection, normalization, identity evidence, planning/policy and Guard writes
in their existing layers. Extend the maintained integration rather than installing
the old reconnaissance prototype beside it. Do not match resources by display name
alone or promote weak port/NIC evidence to authoritative ownership. Test ambiguous
identity, pagination, duplicate observations, partial writes and lost responses.
Changes to shared policy must retain ESXi, Proxmox VM/LXC and pfSense contracts.
Use the [development workflow](development.md); do not enable native reconciliation
or account schedules in migrations, fixtures or deployment scripts. Acceptance
requires an explicitly authorized test run and reconciliation of its result.

### Runtime safeguards

- A completed account import requires a structured Guard result for the requested
  account, with nonnegative integer counts, boolean write/replay flags, placement
  results and a recognized native mode (including native counts in automatic mode).
  Empty, malformed or wrong-account responses remain `IMPORT_UNCONFIRMED`; no
  automatic retry or state reset follows. This validates the existing response
  contract; it does not implement historical receipt reconciliation or certify
  provider coverage/native matching.
- A typed, definitive Guard transport refusal is reported as
  `NETBOX_IMPORT_REFUSED`; possible writes still produce `IMPORT_UNCONFIRMED`.
  Existing uncertain account states are not reclassified or cleared retroactively.
  The UI distinguishes saved/unverified access from acknowledged import, shows the
  run UUID and disables collection for unresolved outcomes. It explicitly explains
  that collection currently includes import and does not offer a separate plan.

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

## Collection response boundaries

Collection retains already-read pages with an explicit diagnostic when next-page
metadata is malformed/conflicting or an explicit page limit is invalid. These
responses never become an empty successful collection. Existing same-collection
URL restrictions, page/request budgets and retained-missing policies remain.

Retriable API responses honor numeric or HTTP-date `Retry-After` up to 30 seconds
within the overall request budget. Longer or malformed values stop the attempt
with the HTTP diagnostic instead of retrying early or waiting without a bound.
Absent headers retain the existing bounded backoff; Guard writes are not retried.
