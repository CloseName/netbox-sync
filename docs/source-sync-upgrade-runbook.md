# Source-sync update after review and publication

This task does not publish or deploy. Run these steps only after the operator approves and publishes the final reviewed commit. Keep normal host/systemd operation; do not use --no-systemd/--no-start/--prepare-only on the actual VM.

## 1. Preserve the installed release first

```sh
set -eu
ROOT=/netbox-sync-test
sudo readlink -f "$ROOT/current"
sudo systemctl is-active netbox-sync.timer
sudo python3 "$ROOT/current/deploy/compose.py" --root "$ROOT" ps
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" preflight
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" create
```

Record expected service/timer state. Set BUNDLE to the exact archive directory reported by create, without opening secret files:

```sh
: "${BUNDLE:?Set the exact backup directory}"
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" verify "$BUNDLE"
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" inspect "$BUNDLE"
```

Stop on any error or unexpected metadata. Use the installed supported backup utility, not a manual database-only copy. Do not activate a release before a verified backup exists.

## 2. Select the published reviewed commit

```sh
: "${RELEASE_COMMIT:?Set the approved full commit after publication}"
case "$RELEASE_COMMIT" in *[!0-9a-f]*|'') exit 1;; esac
test "${#RELEASE_COMMIT}" -eq 40
test -z "$(git -C "$ROOT/repo" status --porcelain)"
test "$(git -C "$ROOT/repo" remote get-url origin)" = https://github.com/CloseName/netbox-sync.git
git -C "$ROOT/repo" fetch origin
git -C "$ROOT/repo" merge-base --is-ancestor "$RELEASE_COMMIT" origin/main
git -C "$ROOT/repo" switch --detach "$RELEASE_COMMIT"
test "$(git -C "$ROOT/repo" rev-parse HEAD)" = "$RELEASE_COMMIT"
```

Stop on dirty checkout or provenance mismatch; no automatic reset/merge/rebase. The local task's unpushed commits will intentionally fail the published-ancestor gate.

## 3. Run the supported installer

For the existing authenticated external-ingress installation:

```sh
sudo python3 "$ROOT/repo/deploy/install.py" \
  --root "$ROOT" --source "$ROOT/repo" \
  --release-id "$RELEASE_COMMIT" \
  --public-url https://netbox-sync-test.indeed-id.hq   --ingress-mode external
```

Do not recreate env files, credentials, volumes, TLS directories, current or historical naming layout. The installer retains the selected root and protected configuration and applies the lifecycle column grants. This change adds no migration revision: head remains 0006_auth_policy. Existing administrator/onboarding state does not require re-enrollment. For a genuinely pre-auth installation follow local-admin-upgrade-runbook.md and its explicit acknowledgment instead.

Stop on installer failure. Do not blindly rerun an immutable release ID, delete containers/volumes, manually switch current, or roll back across database changes. First collect only phase/error, selected release path and service/volume metadata; retain the verified backup.

## 4. Operator acceptance

```sh
sudo readlink -f "$ROOT/current"
sudo python3 "$ROOT/current/deploy/compose.py" --root "$ROOT" ps
sudo systemctl is-active netbox-sync.timer
curl --fail --silent --show-error https://netbox-sync-test.indeed-id.hq/api/v1/health
```

Compare timer/service state to the initial record. Sign in at the public HTTPS URL and confirm completed onboarding, sources, names, mappings and policy. Do not enable automatic sync merely to verify the update.

For each source, explicitly review Discovery and the new plan before prepare/apply. Existing sources without api_port keep their previous 443/8006 defaults; newly registered sources can select a port. This stage does not add connection/credential editing to an existing source. The mappings editor is on Configuration and requires a successful Discovery within 24 hours. It changes placement only, retains absent-host mappings, preserves Source ID and invalidates previous plans. A conflicting revision or uncertain response requires reopening current state before another write.

Keep TLS verification enabled. Optional NetBox CA and operator ingress/certificate ownership remain unchanged. Never add a Docker socket to product containers. Verify the broker remains network_mode:none and API/PostgreSQL have no published ports.

The next live Proxmox check is still needed to establish whether the originally observed failure shares the locally reproduced dependency-preflight cause. Use the safe code, stage and event ID if it fails; do not expose raw credentials/configuration or enable unconditional stderr logging.


## Scheduled failure after manual sync succeeds

See [scheduled Proxmox diagnosis](scheduled-proxmox-review.md) for the full-path
regression and safe `SCHEDULED_FAILURE` journal record correlated with Run ID.
The one-shot scheduler logs to `netbox-sync.service`, not the persistent schedule
or apply worker. Zero failed-run counts/absent digest do not prove absence of
writes. Do not retry automatically or broaden provider/NetBox permissions without
the bounded stage/HTTP evidence. No new migration or credential change is needed.
