#!/usr/bin/env bash
# Test-only UI update. No backup is created; NetBox is not rebuilt.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]] || { echo 'Run as root on netbox-test only.' >&2; exit 1; }
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
RELEASE=$(git -C "$REPO" rev-parse HEAD)
LOG="/var/tmp/netbox-sync-ui-update-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
trap 'echo "Update failed at line $LINENO. Review $LOG before retrying." >&2' ERR
echo "Updating test Sync to $RELEASE without creating a backup."
[[ -z $(git -C "$REPO" status --porcelain) ]]
[[ -d /netbox-sync-test/current && -d /netbox-test ]]
[[ $(docker inspect netbox --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}') == /netbox-test ]]
UNIT=$(systemctl cat netbox-sync.service)
[[ "$UNIT" == *'/netbox-sync-test/'* ]] || { echo 'Test Sync ownership not confirmed.' >&2; exit 1; }
python3 - <<'PY'
from pathlib import Path
from urllib.parse import urlsplit
values = dict(line.split('=', 1) for line in Path('/netbox-sync-test/config/api.env').read_text().splitlines()
              if line and not line.startswith('#') and '=' in line)
assert urlsplit(values['NETBOX_SYNC_PUBLIC_URL']).hostname == 'netbox-sync-test.indeed-id.hq'
PY
docker exec --user 0 -i netbox-sync-bootstrap-worker python -B - <<'PY'
from netbox_sync.bootstrap_state import runtime_netbox
from urllib.parse import urlsplit
url, _ = runtime_netbox('/var/lib/netbox-sync/netbox/bootstrap.json', 'read')
assert urlsplit(url).hostname == 'netbox-test.indeed-id.hq', 'Unexpected NetBox target'
PY
python3 "$REPO/deploy/install.py" --root /netbox-sync-test --source "$REPO" --check
python3 "$REPO/deploy/install.py" --root /netbox-sync-test --source "$REPO" --check-tls
python3 "$REPO/deploy/install.py" --root /netbox-sync-test --source "$REPO" \
  --release-id "$RELEASE" --public-url https://netbox-sync-test.indeed-id.hq
[[ $(readlink -f /netbox-sync-test/current) == "/netbox-sync-test/releases/$RELEASE" ]]
docker ps --filter 'name=netbox-sync-' --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
printf '\nInstalled release: %s\nLog: %s\n' "$RELEASE" "$LOG"
echo 'Open https://netbox-sync-test.indeed-id.hq and refresh with Ctrl+F5.'
