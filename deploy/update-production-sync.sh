#!/usr/bin/env bash
# Run pause on netbox-sync, update Guard on netbox, then run resume here.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 && $(hostname -s) == netbox-sync ]]
ROOT=/netbox/containers
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
RELEASE=$(git -C "$REPO" rev-parse HEAD)
STATE=$ROOT/production-update-state
[[ -z $(git -C "$REPO" status --porcelain) && -d "$ROOT/current" ]]
case ${1:-} in
pause)
  [[ ! -e "$STATE" ]]
  docker exec --user 0 -i netbox-sync-bootstrap-worker python -B - <<'PY'
from netbox_sync.bootstrap_state import runtime_netbox
from urllib.parse import urlsplit
url, _ = runtime_netbox('/var/lib/netbox-sync/netbox/bootstrap.json', 'read')
assert urlsplit(url).hostname == 'netbox.indeed-id.hq', 'Unexpected NetBox target'
PY
  python3 "$REPO/deploy/install.py" --root "$ROOT" --source "$REPO" --check
  python3 "$REPO/deploy/install.py" --root "$ROOT" --source "$REPO" --check-tls
  BACKUP=$(mktemp -d /var/tmp/netbox-sync-production-backup.XXXXXX)
  readlink -f "$ROOT/current" > "$BACKUP/previous-release"
  python3 "$REPO/deploy/backup.py" --root "$ROOT" create --output "$BACKUP/sync"
  shopt -s nullglob
  BUNDLES=("$BACKUP"/sync/netbox-sync-backup-*)
  [[ ${#BUNDLES[@]} -eq 1 ]]
  python3 "$REPO/deploy/backup.py" --root "$ROOT" verify "${BUNDLES[0]}"
  printf '%s\n%s\n' "$RELEASE" "$BACKUP" > "$STATE"
  systemctl mask --runtime --now netbox-sync.timer
  # Drain an in-flight apply before stopping all write entrypoints.
  exec 9>/run/netbox-sync/apply.lock
  flock -w 300 9
  systemctl mask --runtime --now netbox-sync.service
  PROJECT=$(docker inspect netbox-sync-api --format '{{index .Config.Labels "com.docker.compose.project"}}')
  [[ -n "$PROJECT" && "$PROJECT" != '<no value>' ]]
  mapfile -t CONTAINERS < <(docker ps --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Names}}' | grep -v '^netbox-sync-postgres$')
  [[ ${#CONTAINERS[@]} -gt 0 ]]
  docker stop --time 60 "${CONTAINERS[@]}"
  echo "Sync paused. Backup: $BACKUP. Now update Guard on netbox. Do not reboot until resume."
  ;;
resume)
  [[ -f "$STATE" && $(head -n 1 "$STATE") == "$RELEASE" ]]
  systemctl unmask --runtime netbox-sync.service netbox-sync.timer
  python3 "$REPO/deploy/install.py" --root "$ROOT" --source "$REPO" --release-id "$RELEASE"
  [[ $(readlink -f "$ROOT/current") == "$ROOT/releases/$RELEASE" ]]
  mv "$STATE" "$STATE.completed.$(date +%s)"
  echo 'Production Sync updated. Rebuild existing plans. Configured schedules are active.'
  ;;
*) echo 'Usage: update-production-sync.sh pause|resume' >&2; exit 2;;
esac
