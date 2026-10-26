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
fed through stdin. Children receive `/dev/null` stdin. This prevents nested tools
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
Send this report for diagnosis. Keep using preflight without `--apply` until the
cause is understood. Diagnostic collection does not bypass the hash check.
