# Known test installation: reviewed release updates

The current operator contract forbids manual shell diagnostics on the server.
Release checks run inside the reviewed updater or through the application UI.
For the optional Guard stage and receipt reconciliation, see
[automated Selectel recovery](selectel-recovery.md). Deployment still requires
separate approval of an exact merged SHA; a PR or CI pass is not deployment approval.

## Recorded environment and scope

Operator-confirmed on 22 October 2026; revalidate before each update:

| Setting | Value |
| --- | --- |
| SSH shell / server | root on `netbox-test` |
| Sync root / checkout | `/netbox-sync-test` / `/netbox-sync-test/repo` |
| Releases / current | `/netbox-sync-test/releases/<SHA>` / `current` symlink |
| Public Sync URL | `https://netbox-sync-test.indeed-id.hq` |
| Target NetBox | `https://netbox-test.indeed-id.hq`, previously resolved to `10.24.0.6` |
| Ingress | external; host nginx forwards to the Sync proxy |
| NetBox Compose root | `/netbox-test`; Guard updated only with explicit `--with-guard` |
| Scheduling | `netbox-sync.timer` inactive, schedule worker stopped; Selectel schedules off |

The operator confirmed PR #111 deployed and the UI recovered after the explicit
service start. This is historical acceptance, not a claim about the current server.
Do not pin future updates to that old commit. ESXi and pfSense synchronization and
observation timestamp saving were previously confirmed; repeat affected scenarios
after new changes. Proxmox and ESXi clock-only plans must disable manual sync.

On 25 October 2026 the operator confirmed the updater's full real Linux cycle for
`99676f7351940b598c02ae9530274d74f9a3315f`, backup
`/netbox-sync-test/backups/netbox-sync-backup-20261025-084202`, and subsequent UI
behavior. This is dated evidence, not acceptance of Selectel or a future update.
The updater is not a general installer or production tool.
By default it updates Sync only. The explicit `--with-guard` mode described below
also updates the installed test Guard without backups. Neither mode changes account schedules, invokes synchronization,
prunes Docker, or restores data. Existing `update-*-test*.sh` scripts are historical
special-purpose procedures: some skip backups, change Guard and/or enable schedules.
Do not substitute them for this procedure.

The test updater creates no Sync or NetBox database/configuration backups, including
with `--with-guard`. Existing backups are not deleted. Production backup tools and
the standalone backup/restore utility are unchanged.

## Before starting

### Repeated Selectel account lifecycle acceptance

Only on test, with schedules off and no active writes:

1. For a settled account, record the provider UUID and NetBox ID of an adopted
   physical server, a proven account-created cloud VM, and their current IPs.
   An uncertain account must complete receipt reconciliation or a reviewed
   historical baseline first; deletion cannot bypass that state.
2. Open **Отсоединение и удаление** and click **Удалить аккаунт**. Preparation
   disables new collections automatically. Review the compact counts and
   consequences, then use the single account-level checkbox and confirmation.
   No per-resource confirmation or expanded retained-object list is required.
   Adopted cards and their existing IP assignments must remain; proven imported
   cards and network objects must disappear and the provider registry must be
   empty. Selectel claims are removed from adopted objects; an adopted prefix's
   VLAN introduced by the original projection is restored if unchanged.
   Missing origin evidence or foreign dependencies block the whole transaction;
   record the grouped reason and object details rather than bypassing it.
   No scheduler stop is needed; busy writes produce a retry message. Lost responses
   require checking the same operation, not a new deletion.
3. In the deleted account, prepare and confirm reconnection. Under **Доступ**, choose
   **Указать доступ и запустить сбор**, enter credentials, then **Подключить и собрать**.
   First collection/import starts automatically; schedules remain off. Editing
   credentials of an existing connection does not launch collection.
4. Wait for confirmed import, record its run ID and counts, then manually collect
   once more. Strongly identified adopted cards keep their IDs; newly created cards
   are reused by provider identity on subsequent collections. No duplicate cards
   or IP changes are expected. Missing hardware IDs still require reviewed first
   creation, and ambiguous candidates remain unresolved rather than auto-adopted.
5. Repeat deletion/reconnection two more times. Account-created cards may receive
   new IDs after deliberate deletion; pre-existing adopted cards must retain theirs.
   Record delete/retain counts, import run IDs, candidate reasons and screenshots
   in the test journal. Do not treat counts alone as proof of matching correctness.

Deletion does not restore historical native names/status/placement on adopted
cards. Unowned legacy placement and audit/deletion fences remain deliberately.
Never use production's manually confirmed bindings as test matching evidence.

### Dedicated first-creation acceptance

After a separately approved coordinated update, use a freshly and successfully
collected Selectel account. In test NetBox open provider resources, an unmatched
dedicated resource's **Сведения**, then **Проверить возможность создания карточки**.
Check one resource with known candidates first: links must be shown and creation
must be unavailable. For a no-candidate resource, independently verify that no
card exists; absence of reported candidates is not proof. Confirm exactly one
creation only after this check. Verify its provider UUID, configuration, placement,
empty serial and absent primary IP; existing objects/IPs must remain unchanged.
Repeat the submitted form: it must return the same result, not another card.
Then run a fresh manual collection and verify the same Device ID is reused.
Keep schedules off and record any failures before broadening the test. Do not use
this action to bypass an uncertain import or to create another card for a known
ESXi/Proxmox host. Production remains out of scope.

Approve an exact merged commit. Fetch main, preserve any local modifications, and
check out that full SHA in the test checkout. Do not use an unreviewed moving branch
or `git reset --hard`. Confirm the checkout contains the reviewed updater itself.

Verify in the UI that no sync, discovery, registration, removal or retirement job
is running/pending and that nobody will launch jobs during maintenance. Selectel
must have schedules off, no next run and no running/pending lifecycle job. Keep
`IMPORT_UNCONFIRMED` accounts untouched; do not clear their state. The operator's
idle acknowledgement is required because this script does not infer queue idleness
from container health. Do not reboot during maintenance; this procedure does not
change persistent timer enablement. Check scheduling again after any reboot.

The release executor fetches the repository, preserves local changes and selects the
approved full commit. It runs the saved `deploy/update_test.py --commit <SHA>`
entrypoint first without `--apply`; this is read-only preflight. For a combined
release it includes `--with-guard` in both preflight and apply. The executor then
uses `--apply --idle-confirmed` only after the UI idle acknowledgement and deployment
approval. Do not substitute individually pasted diagnostic commands.

Preflight checks host/root, clean checkout, ancestry in fetched origin/main,
expected origin, free space, target URLs/bootstrap, external ingress, scheduler
state. It rejects mismatches instead of rewriting
configuration or printing secrets. `--with-guard` also discovers and validates the
existing test NetBox Compose installation and database identity.

Run this as a saved Python file, not `bash <<...`, `curl | bash`, or a pasted script
fed through stdin. Children receive `/dev/null` stdin, except the read-only Compose
hash subprocess which receives only its explicit in-memory configuration document.
No child inherits terminal/script input. This prevents nested tools
from consuming later commands, the suspected cause of the 22 October update stopping
after installation while the UI returned 502.

The script stops selected Sync services and installs with `--no-start --ingress-mode external`, then starts
only the explicit allowlist (API, proxy, auth, broker, probe, bootstrap, lifecycle,
apply). The schedule worker is excluded. Selectel state is checked again before
bootstrap starts because it contains its own scheduler. Successful completion
requires selected containers running/healthy on the requested image, inactive
scheduling entrypoints and HTTP 200 through public HTTPS with certificate verification.
Only `UPDATE_OK` establishes script completion, not `Built` or `migrate completed`.

## Failure and recovery

Record `UPDATE_FAILED_STAGE` and `PREVIOUS_RELEASE`. No backup is created by this test updater.
Do not rerun the entire updater blindly. No automatic rollback is performed.
Before install, the old release is still selected; after install it may be the new
release and migrations may have completed. Keep schedules off in either case.

Do not perform manual server-side diagnostic commands or blindly rerun a failed
update. Preserve the updater's stage report. Diagnose its evidence and prepare a
reviewed release change for any missing automated check or recovery step. The
updater already checks actual running images, health, public HTTPS, timers and
Selectel scheduling. A failed Guard stage may leave NetBox stopped; a failed Sync
stage may leave Sync stopped. No automatic database rollback or schedule restart
is attempted.

After recovery repeat image, scheduler and public HTTPS checks; a recovery start
alone does not verify them. Use [backup/restore](../backup-restore.md) for a reviewed
recovery plan. Do not downgrade an image as a substitute for restoring compatible
database/configuration state; never restore over a live target without a separate plan.

## Acceptance after startup

Hard-refresh the browser; verify login, source list and run history. Build a plan
for an authorized test source. A timestamp-only plan must have zero substantive
changes and a disabled review/sync button. Real changes may enable it; review them
before a separately authorized sync. Confirm `observed_at` saving with actual
content changes. Check ESXi, Proxmox (preserve VM/LXC differences) and pfSense as
affected. Keep Selectel experimental and paused. Record commit, checks and outcome
in the PR/release evidence without replacing this runbook with a chat transcript.

### Guard configuration mismatch

`GUARD_CONFIG_DRIFT` during read-only preflight stops before service mutation.
The updater emits `GUARD_CONFIG_REPORT` with service names, hash validity/match,
Compose versions, declared environment equality and counts, and image-reference
comparison. It never prints environment names/values, paths, hashes or raw errors.
The environment comparison covers declared settings only; matching values do not
prove the complete container configuration equivalent or authorize recreation.
The gate compares the container label with a hash of the fully resolved model,
including service env files. The rendered model is passed privately to Compose
via explicit stdin, allowing Compose to decode its own dollar escaping. No
configuration file or backup is written. `resolved_hash_matches` must be true
for both services; the unresolved CLI hash is diagnostic only. A changed env
file still blocks even when the unresolved hash happens to match.
Send a remaining mismatch report for diagnosis; do not use `--apply` while blocked.

### Existing Selectel run evidence

The saved updater accepts `--diagnose-selectel ACCOUNT RUN_UUID` with its pinned
`--commit` and normal test-host preflight. This cannot be combined with `--apply`
or `--with-guard`. It reads the current uncertain run and existing container logs;
it does not start collection, call import, accept a baseline, or change state.
No runtime deployment is needed to use this diagnostic from the reviewed checkout.
The report includes duration, presence of saved import intent, and fixed HTTP/error
categories from up to 500 log lines per container over the run time window.
Raw logs remain private and transient. Logs are time-correlated, not proven to belong
to that run; missing/truncated/rotated logs do not establish that no writes occurred.
Keep the uncertainty gate and schedules off regardless of the diagnostic outcome.

### Dedicated Selectel matching evidence

Use the reviewed checkout's `deploy/update_test.py --commit <SHA>
--diagnose-selectel-matching <ACCOUNT>` for a read-only explanation of pending
dedicated resources. It cannot be combined with apply, Guard update or run-log
diagnostics. Both Sync and Guard test preflights must pass. No image build,
restart, backup, collector, binding or IP write occurs; runtime deployment is
not required when the installed Guard already has `provider_hardware_check`.

The installed command runs as `netbox-sync-selectel` in a repeatable-read,
read-only database transaction and computes the existing reconciliation policy.
The report shows pending resource names/keys, proposed actions/reasons, candidate
IDs/names and evidence flags/counts, plus host hardware coverage. It omits raw
hardware identifiers, IP values, command banners and exception text. An absent
command, incompatible output or permission failure stops without changing state.

These are decisions from saved inventory, not a fresh provider observation or
permission to apply. Existing correctly bound resources are excluded; manual
bindings do not establish successful automatic matching. `fresh_inventory_required`
can identify retained/stale observations. Counts need not equal the latest import
summary. Diagnose each reason before authorizing changes; schedules stay off.

### Stored hardware field coverage

The separate `--diagnose-selectel-hardware <ACCOUNT>` mode uses both test
preflights and runs the reviewed `deploy/selectel_hardware_evidence.py` source
through the installed NetBox shell as an explicit argument, with disconnected
stdin. No container copy/build/restart or runtime deployment is needed. It cannot
be combined with apply, Guard update or other diagnostics. The dedicated importer
must retain full visibility and reconciliation permissions; PostgreSQL enforces
a repeatable-read, read-only transaction before the first query.

For all saved dedicated resources (including bound/retained ones), it reports
inventory age, resource/details/hardware section availability, retention and data
shape; missing/null/empty/invalid/valid-format states of the three recognized
root identity fields; and counts of component serials. Hardware/IP values,
credentials, arbitrary field names and raw errors are not printed. A valid-format
identifier alone does not prove freshness, uniqueness or matching ownership.

The normalized inventory has already discarded non-allowlisted API fields.
`raw_api_fields_not_preserved=true` is a limitation, not a discovered API failure.
This report cannot prove that Selectel omitted other identifiers or that a field
was lost before normalization. Component serials and provider hw_uuid remain
separate namespaces, never substitutes for system identity. Resolve coverage
before considering a separate authorized provider read or matching change.

### One-server live hardware metadata probe

`--probe-selectel-hardware ACCOUNT RESOURCE_UUID` is a separate, explicitly live
provider-read mode. Both test preflights must pass. It cannot be combined with
apply, Guard update or other diagnostic modes. The reviewed source is passed to
the existing bootstrap worker as an explicit Python argument; no runtime update,
backup, service restart or file copy is needed.

The probe privately reads existing account credentials and drops root privileges
before authenticating. IAM domain scope must match the selected account. Only
token issuance uses POST. Resource reads use the existing dedicated API: a bounded
resource list to verify the UUID and service type, then that resource's detail and
info endpoints. At most two listing pages and eight HTTP attempts are allowed.
It never invokes full collection, import, binding, IP writes or account-state writes.

Output contains fixed field paths and rejection categories, never raw values,
arbitrary API keys, credentials or exception text. Root serial/service_tag/system_uuid
are compared before/after the existing sanitizer; these are the normalizer's root
identity inputs. Other allowlisted aliases/component paths are diagnostic only.
The bounded path scan is not exhaustive API schema discovery and valid syntax does
not prove hardware identity or ownership. Schedules remain off.
