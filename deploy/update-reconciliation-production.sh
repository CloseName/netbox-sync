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
url, _ = runtime_netbox('/var/lib/netbox-sync/netbox/bootstrap.json', 'read')
assert urlsplit(url).hostname == 'netbox.indeed-id.hq', 'Unexpected NetBox target'
PY
python3 "$REPO/deploy/install.py" --root "$ROOT" --source "$REPO" --check
python3 "$REPO/deploy/install.py" --root "$ROOT" --source "$REPO" --check-tls
BACKUP=$(mktemp -d /var/tmp/netbox-sync-reconciliation-backup.XXXXXX)
echo "Backup: $BACKUP"
readlink -f "$ROOT/current" > "$BACKUP/previous-release"
python3 "$REPO/deploy/backup.py" --root "$ROOT" create --output "$BACKUP/sync"
shopt -s nullglob
BUNDLES=("$BACKUP"/sync/netbox-sync-backup-*)
[[ ${#BUNDLES[@]} -eq 1 ]]
python3 "$REPO/deploy/backup.py" --root "$ROOT" verify "${BUNDLES[0]}"
python3 "$REPO/deploy/install.py" --root "$ROOT" --source "$REPO" --release-id "$RELEASE"
docker exec netbox-sync-bootstrap-worker python -B -c "from netbox_sync.run_reconciliation import RunReconciliation; assert hasattr(RunReconciliation, '_waiting_lock'); print('OK: reconciliation coordination installed')"
echo "Updated Sync. Backup: $BACKUP. Review from the UI without stopping the timer. Configured schedules are active."
