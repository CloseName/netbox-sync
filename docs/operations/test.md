# Known test installation: Sync-only updates

## Recorded environment and scope

Operator-confirmed on 22 October 2026; revalidate before each update:

| Setting | Value |
| --- | --- |
| SSH shell / server | root on `netbox-test` |
| Sync root / checkout | `/netbox-sync-test` / `/netbox-sync-test/repo` |
| Releases / current | `/netbox-sync-test/releases/<SHA>` / `current` symlink |
| Backup directory | `/netbox-sync-test/backups` |
| Public Sync URL | `https://netbox-sync-test.indeed-id.hq` |
| Target NetBox | `https://netbox-test.indeed-id.hq`, previously resolved to `10.24.0.6` |
| Ingress | external; host nginx forwards to the Sync proxy |
| NetBox Compose root | `/netbox-test`; not updated by this procedure |
| Scheduling | `netbox-sync.timer` inactive, schedule worker stopped; Selectel schedules off |

The operator confirmed PR #111 deployed and the UI recovered after the explicit
service start. This is historical acceptance, not a claim about the current server.
Do not pin future updates to that old commit. ESXi and pfSense synchronization and
observation timestamp saving were previously confirmed; repeat affected scenarios
after new changes. Proxmox and ESXi clock-only plans must disable manual sync.

The new updater has isolated orchestration tests; its first real Linux deployment
still requires operator observation. It is not a general installer or production tool.
It never updates NetBox/Guard, changes account schedules, invokes synchronization,
prunes Docker, or restores data. Existing `update-*-test*.sh` scripts are historical
special-purpose procedures: some skip backups, change Guard and/or enable schedules.
Do not substitute them for this procedure.

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

Use individual commands from the terminal (replace `REVIEWED_FULL_SHA` with the
actual 40-character merge SHA supplied with the release):

```sh
git -C /netbox-sync-test/repo status --short
git -C /netbox-sync-test/repo fetch origin main
git -C /netbox-sync-test/repo checkout --detach REVIEWED_FULL_SHA
python3 /netbox-sync-test/repo/deploy/update_test.py --commit REVIEWED_FULL_SHA
```

Default mode is read-only preflight. It checks host/root, clean checkout, ancestry
in the fetched origin/main, expected origin, free space (minimum 3 GiB, not a size
guarantee), target URLs/bootstrap, external ingress, scheduler state and backup
prerequisites. It rejects mismatches rather than rewriting configuration or printing
secrets. If DNS/routing/Guard configuration changed, repeat the read-only connection,
TLS, token and Guard checks before authorizing an update.

After `PREFLIGHT_OK` and the idle check:

```sh
python3 /netbox-sync-test/repo/deploy/update_test.py --commit REVIEWED_FULL_SHA --apply --idle-confirmed
```

Run this as a saved Python file, not `bash <<...`, `curl | bash`, or a pasted script
fed through stdin. Children receive `/dev/null` stdin. This prevents nested tools
from consuming later commands, the suspected cause of the 22 October update stopping
after installation while the UI returned 502.

The script stops selected Sync services, creates and verifies a backup using the
installed release, installs with `--no-start --ingress-mode external`, then starts
only the explicit allowlist (API, proxy, auth, broker, probe, bootstrap, lifecycle,
apply). The schedule worker is excluded. Selectel state is checked again before
bootstrap starts because it contains its own scheduler. Successful completion
requires selected containers running/healthy on the requested image, inactive
scheduling entrypoints and HTTP 200 through public HTTPS with certificate verification.
Only `UPDATE_OK` establishes script completion, not `Built` or `migrate completed`.

## Failure and recovery

Record `UPDATE_FAILED_STAGE`, `PREVIOUS_RELEASE` and `BACKUP_VERIFIED`/`BACKUP_PATH`.
Do not rerun the entire updater blindly. No automatic rollback is performed.
Before install, the old release is still selected; after install it may be the new
release and migrations may have completed. Keep schedules off in either case.

Inspect locally (redact secrets before sharing logs):

```sh
readlink -f /netbox-sync-test/current
systemctl show netbox-sync.timer -p ActiveState
python3 /netbox-sync-test/current/deploy/compose.py --root /netbox-sync-test ps -a
docker logs --tail 100 netbox-sync-api
docker logs --tail 100 netbox-sync-proxy
```

A 502 can mean stopped services or an upstream/ingress fault; it does not prove a
failed migration. If install completed, verify current SHA, private configuration
and pending work before reissuing just the allowlisted start below. Never start all
services or use a historical resume script. If startup itself failed, diagnose
its logs first. Host nginx may serve other applications; do not restart it blindly.

```sh
python3 /netbox-sync-test/current/deploy/compose.py --root /netbox-sync-test up -d --no-deps --wait --wait-timeout 120 netbox-sync-secret-broker netbox-sync-auth-worker netbox-sync-probe-worker netbox-sync-bootstrap-worker netbox-sync-lifecycle-worker netbox-sync-apply-worker netbox-sync-api netbox-sync-proxy
```

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
