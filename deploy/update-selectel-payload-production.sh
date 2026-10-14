#!/usr/bin/env bash
# Sync-only update; Guard and the NetBox database schema are unchanged.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 && $(hostname -s) == netbox-sync ]]
ROOT=/netbox/containers
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
RELEASE=$(git -C "$REPO" rev-parse HEAD)
[[ -z $(git -C "$REPO" status --porcelain) && -d "$ROOT/current" ]]
[[ ! -f "$ROOT/production-update-state" ]] || { echo 'Previous two-host update is unfinished. Complete it before this update.' >&2; exit 1; }
docker exec --user 0 -i netbox-sync-bootstrap-worker python -B - <<'PY'
from netbox_sync.bootstrap_state import runtime_netbox
from urllib.parse import urlsplit
from pathlib import Path
from netbox_sync.selectel_control import read, running
for path in Path('/var/lib/netbox-sync/netbox/selectel').glob('*.json'):
    if path.stem.isdigit() and running(read(path)):
        raise SystemExit('Selectel collection is active; wait for completion before updating.')
url, _ = runtime_netbox('/var/lib/netbox-sync/netbox/bootstrap.json', 'read')
assert urlsplit(url).hostname == 'netbox.indeed-id.hq', 'Unexpected NetBox target'
PY
python3 "$REPO/deploy/install.py" --root "$ROOT" --source "$REPO" --check
python3 "$REPO/deploy/install.py" --root "$ROOT" --source "$REPO" --check-tls
TIMER_WAS_ACTIVE=0
if systemctl is-active --quiet netbox-sync.timer; then TIMER_WAS_ACTIVE=1; fi
restore_timer() {
    if [[ $TIMER_WAS_ACTIVE == 1 ]]; then systemctl start netbox-sync.timer; else systemctl stop netbox-sync.timer; fi
}
trap restore_timer EXIT
systemctl stop netbox-sync.timer
# Do not terminate an active synchronization to obtain the backup lock.
if ! flock --exclusive --timeout 600 /run/netbox-sync/apply.lock true; then
    echo 'Active synchronization did not finish; update not started.' >&2
    exit 1
fi
BACKUP=$(mktemp -d /var/tmp/netbox-sync-selectel-payload-backup.XXXXXX)
echo "Backup: $BACKUP"
readlink -f "$ROOT/current" > "$BACKUP/previous-release"
python3 "$REPO/deploy/backup.py" --root "$ROOT" create --output "$BACKUP/sync"
shopt -s nullglob
BUNDLES=("$BACKUP"/sync/netbox-sync-backup-*)
[[ ${#BUNDLES[@]} -eq 1 ]]
python3 "$REPO/deploy/backup.py" --root "$ROOT" verify "${BUNDLES[0]}"
python3 "$REPO/deploy/install.py" --root "$ROOT" --source "$REPO" --release-id "$RELEASE"
docker exec netbox-sync-bootstrap-worker python -B -c "from netbox_sync.selectel_payload import MAX_BYTES, inventory_document, referenced_catalogs; from netbox_sync.selectel_runner import child_result; assert MAX_BYTES == 16*1024*1024; print('OK: scoped Selectel catalog filtering installed')"
echo "Updated Sync. Backup: $BACKUP. Refresh the Selectel page and start one new collection. Existing bindings are retained."
