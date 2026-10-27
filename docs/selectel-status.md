# Selectel: experimental status

Status recorded 19 October 2026. This integration is not accepted for production.
The repository consolidation is separate from any production deployment.

For the refreshed code trace, read-only test evidence and remaining acceptance
boundaries see [25 October diagnosis](selectel-diagnosis-20261025.md).

## Known limitations

Dedicated resources without a usable chassis serial now have a separate
[reviewed first-creation path](hardware-identity.md#reviewed-first-creation-without-a-chassis-serial).
It requires administrator confirmation of absence and refuses known candidates;
normal automatic matching/creation gates are unchanged. This addresses first
creation only, not the outstanding weak-candidate adoption or reverse-matching
acceptance scenarios. No test-server or production acceptance is implied.

On 27 October the operator deployed PR #129 to test and opening the first-creation
review failed with `SimpleLazyObject has no attribute objects`. Browser authentication
wraps the user; Guard incorrectly derived the model manager from that wrapper's type.
Permission reloads now use Django's configured user model, keeping fresh permission
and object-constraint checks. The native form scenario exercises lazy request users
for GET, POST, refusal and receipt replay. This fixes the review/creation path, not
matching policy, and does not authorize new records or enable schedules by itself.

The coordinated test update and read-only receipt lookup are documented in
[automated recovery](operations/selectel-recovery.md). This adds evidence-based
confirmation for new runs; historical runs without an intent digest are not
automatically cleared, and missing receipts never authorize retry. No deployment
or live acceptance is implied by this implementation.

- The test installation reported an unconfirmed import for two accounts. Some
  writes may have committed. The screenshot does not identify the underlying
  exception or prove a matching failure; reconcile the original run in NetBox
  before considering a new import.
- Native resource matching and dedicated server port-to-NIC identity remain under
  investigation. See [port evidence](selectel-port-evidence.md) and
  [outstanding work](selectel-backlog.md).
- The GitHub integration run for 11a48eb failed in the native Selectel scenario:
  `provider_placement.ensure` raised `DependencyGuardBlocked: PERMISSION_DENIED`
  while creating a Region. PR #113 subsequently fixed creation permission checks
  against saved rows with transactional rollback. The historical failure is not
  current CI evidence, and the code fix is not acceptance of the test installation.

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
  contract; receipt reconciliation is a separate read-only operation and does not
  certify provider coverage/native matching.
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

### Atomic import refusal diagnostics (26 October 2026)

New Guard responses distinguish confirmed rollback from post-commit response failure.
The view catches import exceptions inside an outer atomic boundary and marks rollback;
commit failures and response construction remain outside that catch. Only a 409 with
PROVIDER_IMPORT_ROLLED_BACK, boolean rolled_back=true and the exact requested account
and nonce is recognized by Sync as NETBOX_IMPORT_REFUSED. Legacy generic 409 responses,
wrong-run responses, lost responses and 5xx retain uncertainty. Historical errors are
not reclassified from access logs or missing receipts.

Only closed reason categories, HTTP status and event UUID are retained through the
child, account state and public UI. No remote exception messages, SQL or invalid field
values are exposed. Coordinated test Sync/Guard deployment is required. This improves
future evidence; it does not establish the cause of the old 08cd3347 run or authorize
another import/baseline acceptance.

### Structural validation evidence (26 October 2026)

Test run `72ce8742-5935-4ce9-99b1-29aa7dee2347` received a confirmed atomic
OBJECT_VALIDATION refusal (event `fe88dd03-cd60-413a-ae8f-533ce23fdd9c`).
Its failing field is not yet known. Future refusals include allowlisted model,
positive object ID when available, validation phase, and up to 12 field/code pairs.
Exception messages, parameters and field values are never included. Unknown labels
are generalized; Sync revalidates the projection at process and public boundaries.
An ID identifies the object being validated, not proof that it was saved.

Validation, transaction boundaries, existing bindings and retry policy are unchanged.
Deploy both test Guard and Sync, then inspect a new manual collection's diagnostic.
Do not accept a historical baseline for this confirmed refusal. Production is out
of scope. Native rollback and browser-rendering regressions cover this contract.

### Legacy placement compatibility (26 October 2026)

Test run `1e23bb4a-eb98-457a-bf6b-81d8ea7df503` failed validation of an unsaved
Region (`__all__`, no detailed code). The operator confirmed existing account
29916 regions kz-1, ru-1, ru-3, ru-7, ru-8 and ru-9 (IDs 1, 5, 2, 3, 6, 4).
Source history exposes a reproducible upgrade defect: V1 created deterministic
placement slugs without creation provenance; V2 recognized only proven legacy
objects and otherwise attempted a duplicate with the same name. The exact live
conflicting slug has not been read; these observations support that diagnosis.

Resolve now reuses an unowned V1 Region/Site only at its exact account-scoped
legacy slug, with all expected values equal, a root Region and object view
permission. Any existing ownership proof outside the legacy migration path or
value mismatch refuses the operation. Reuse does not save the placement object
or add a creation proof: it does not authorize renaming or automatic deletion.
New objects and previously proven objects retain their existing policy. Tests
cover repeated reuse, mismatches, foreign ownership, permissions and native
imports retaining IDs/fields while excluding legacy placement from deletion.
