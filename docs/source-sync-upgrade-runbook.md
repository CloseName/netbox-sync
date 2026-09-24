# Source-sync update after review and publication

For the BIOS UUID fix on an already installed f90743a release, use [the narrower UUID update procedure](esxi-bios-uuid-acceptance-20260924.md). That fix does not change NetBox guard and does not require repeating the guard upgrade in section3 below.

The 24 September recovery task authorizes publication; deployment remains an operator action. Use only the final published full SHA from the delivery report. Current evidence and limits: [recovery acceptance](backend-completion-acceptance-20260924.md). Keep normal host/systemd operation; do not use --no-systemd/--no-start/--prepare-only on the actual VM.

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

## 3. Update the independently installed NetBox guard first

This release adds `sources/<source>/audit/` and corrects the optional-null ownership
field. An old plugin cannot support the new recovery review. There is no NetBox
installation entrypoint in this repository: Sync does not own its image, Compose
project, service names, plugin mount or database backup.

Before proceeding, record **metadata only** from the actual NetBox deployment:
NetBox version (supported:4.7.0), Compose file, web/background service names,
plugin code mount versus baked image, Python/manage.py paths inside that image,
and the current GuardIdentity UUID. Keep the UUID unchanged and verify it against
the already configured Sync pin. Do not print tokens, Compose env values or keys.
Back up the entire NetBox database and plugin state through its independently
supported recovery procedure. Journal-only backup is insufficient. See the known
full logical restore limitation in the guard README; do not invent a workaround.

For an **existing verified host bind-mounted plugin package**, the compatible code
copy is below. NETBOX_GUARD_DIR must be the directory containing the installed
`netbox_guard/__init__.py` (the package itself), never a parent deployment root.
This is conditional on that verified topology; it is not a guessed path for the
current VM. Stop all NetBox web/background consumers through their own maintenance
procedure before changing shared code. Do not run Sync writes during that window.

```sh
: "${NETBOX_GUARD_DIR:?Set the verified existing package bind-mount directory}"
test -d "$NETBOX_GUARD_DIR"
test ! -L "$NETBOX_GUARD_DIR"
test -f "$NETBOX_GUARD_DIR/__init__.py"
sudo rsync -ani --checksum --exclude='__pycache__/' \
  "$ROOT/repo/deploy/netbox_guard/" "$NETBOX_GUARD_DIR/"
# Review the dry-run against only that package. Stop if ownership/layout differs.
sudo rsync -rlt --checksum --exclude='__pycache__/' \
  "$ROOT/repo/deploy/netbox_guard/" "$NETBOX_GUARD_DIR/"
```

No plugin DB migration was added in this update. Preserve all existing migrations,
claims, receipts, triggers and GuardIdentity. New files must retain the existing
NetBox process's readable ownership/mode; the package contains no secrets. For a
**baked plugin image**, do not copy into a running container: update only the guard
source in the existing image recipe and rebuild using that project's own build
command. Both web and background consumers must use the same code.

The following is a metadata-only check after the operator's NetBox restart. Fill
these variables from the verified existing deployment, not from Sync conventions:

```sh
: "${NETBOX_COMPOSE:?Verified NetBox Compose file}"
: "${NETBOX_WEB_SERVICE:?Verified NetBox web service}"
: "${NETBOX_PYTHON:?Verified Python path in NetBox image}"
: "${NETBOX_MANAGE:?Verified manage.py path in NetBox image}"
sudo docker compose -f "$NETBOX_COMPOSE" exec -T "$NETBOX_WEB_SERVICE" \
  "$NETBOX_PYTHON" "$NETBOX_MANAGE" shell -c \
  'from netbox_guard.models import GuardIdentity; from netbox_guard.service import audit_source; from django.urls import resolve; p=resolve("/api/plugins/netbox-sync-guard/sources/probe/audit/"); print("audit route:", p.func.view_class.__name__); print("guard UUID:", GuardIdentity.objects.get(pk=1).identifier)'
```

This does not call audit or mutate infrastructure. Stop if the route is absent or
the UUID changed. The exact NetBox build/restart command cannot be made concrete
without its actual independent deployment metadata. Do not use speculative
`netbox`, `netbox-worker` service names or a guessed `/opt` plugin directory.

## 4. Rebuild and run the supported Sync installer

For the existing authenticated external-ingress installation:

```sh
sudo docker build -f "$ROOT/repo/Dockerfile.web" \
  -t "netbox-sync:$RELEASE_COMMIT" "$ROOT/repo"
sudo python3 "$ROOT/repo/deploy/install.py" \
  --root "$ROOT" --source "$ROOT/repo" \
  --release-id "$RELEASE_COMMIT" --image "netbox-sync:$RELEASE_COMMIT" \
  --public-url https://netbox-sync-test.indeed-id.hq \
  --ingress-mode external
```

Do not recreate env files, credentials, volumes, TLS directories, current or historical naming layout. The installer retains the selected root and protected configuration and applies the lifecycle column grants. The current chain advances to `0012_run_reconciliation`, preserving hardware reservations and the source recovery journal. Sources missing historical hardware evidence require explicit identity review before additional ESXi registration; do not invent UUIDs from addresses. Existing administrator/onboarding state does not require re-enrollment. For a genuinely pre-auth installation follow local-admin-upgrade-runbook.md and its explicit acknowledgment instead.

The explicit Docker build above guarantees a rebuild; the installer also invokes its staged Compose build before migrations/activation. There is no `--build` installer flag. Existing root/configuration/credentials/volume and configured NetBox guard UUID are preserved; do not pass a replacement guard UUID during upgrade. The DB head is0012.

Stop on installer failure. Do not blindly rerun an immutable release ID, delete containers/volumes, manually switch current, or roll back across database changes. First collect only phase/error, selected release path and service/volume metadata; retain the verified backup.

## 5. Operator acceptance

```sh
sudo readlink -f "$ROOT/current"
sudo python3 "$ROOT/current/deploy/compose.py" --root "$ROOT" ps
sudo systemctl is-active netbox-sync.timer
curl --fail --silent --show-error https://netbox-sync-test.indeed-id.hq/api/v1/health
```

Compare timer/service state to the initial record. Sign in at the public HTTPS URL and confirm completed onboarding, sources, names, mappings and policy. Do not enable automatic sync merely to verify the update.

For each source, explicitly review Discovery and the new plan before prepare/apply. Existing sources without api_port keep their previous 443/8006 defaults; newly registered sources can select a port. This stage does not add connection/credential editing to an existing source. The mappings editor is on Configuration and requires fresh bounded provider evidence within24 hours: successful Discovery, or specifically completed-provider evidence from NETBOX_PLACEMENT_MISSING. It never treats a provider/permission/transport failure as complete inventory. It changes placement only, retains absent-host mappings, preserves Source ID and invalidates previous plans. A conflicting revision or uncertain response requires reopening current state before another write.

Keep TLS verification enabled. Optional NetBox CA and operator ingress/certificate ownership remain unchanged. Never add a Docker socket to product containers. Verify the broker remains network_mode:none and API/PostgreSQL have no published ports.

The next live Proxmox check is still needed to establish whether the originally observed failure shares the locally reproduced dependency-preflight cause. Use the safe code, stage and event ID if it fails; do not expose raw credentials/configuration or enable unconditional stderr logging.


## Scheduled failure after manual sync succeeds

See [scheduled Proxmox diagnosis](scheduled-proxmox-review.md) for the full-path
regression and safe `SCHEDULED_FAILURE` journal record correlated with Run ID.
The one-shot scheduler logs to `netbox-sync.service`, not the persistent schedule
or apply worker. Zero failed-run counts/absent digest do not prove absence of
writes. Do not retry automatically or broaden provider/NetBox permissions without
the bounded stage/HTTP evidence. No new migration or credential change is needed.


## Host identity / registration continuation release

The current head is migration `0012_run_reconciliation`. The supported installer
runs forward migrations and narrow grants; no manual table creation or env edits
are required. Back up before upgrade and retain the old release/backup. Rollback
must not discard pending registrations or verified identity journals.

After reviewed publication/deployment, use the bounded read-only Admin procedure in
[host identity registration](host-identity-registration.md#minimal-read-only-evidence-for-the-two-esxi-infra-entries)
for the two ESXI-INFRA records. Do not enable schedules or remove a record to get past
an identity blocker. An uncertain registration can continue with the original actor,
source ID, nonce and parameters after a fresh authenticated probe; never clear its
reservation in SQL. Legacy verification requires existing matching ownership;
unknown UUIDs, empty inventory and matching DNS names are not enough.

Local acceptance on the final image: both production worker modes passed; a separate
bundled installer upgrade and host backup/verify/inspect/fresh-restore gate passed.
These are controlled local fixtures, not an assertion of live ESXI-INFRA ownership.


## Recovery journals after this upgrade

Migration0011 adds a secret-free immutable registration request. Existing rows may
have no request and are not reconstructed from names. Migration0012 adds append-only
baseline decisions and two SELECT-only gate views. The installer applies the narrow
role grants; no global pip, manual SQL or credential/volume replacement is needed.

Backup includes requests, recovery/retirement journals, baseline audit, credentials,
policy and onboarding. Restore retains audit but invalidates accepted baselines and
sessions; it does not replay pending remote writes. Recheck the actual external
NetBox receipts and current inventory before resuming any work. Follow the ordered
AM → CM → PAM / UNKNOWN / placement acceptance in the recovery report. Do not enable
schedules merely because upgrade succeeded.
