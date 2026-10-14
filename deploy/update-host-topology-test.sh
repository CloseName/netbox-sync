#!/usr/bin/env bash
# Test-only combined Guard + collector update, no backup, no IPAM apply.
set -Eeuo pipefail
[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]] || { echo 'Run on netbox-test as root.' >&2; exit 1; }
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
RELEASE=$(git -C "$REPO" rev-parse HEAD)
[[ -z $(git -C "$REPO" status --porcelain) ]]
[[ -d /netbox-sync-test/current && -d /netbox-test ]]
python3 - <<'PY'
from pathlib import Path
from urllib.parse import urlparse
p = Path('/netbox-sync-test/config/api.env')
values = dict(line.split('=', 1) for line in p.read_text().splitlines() if line and not line.startswith('#') and '=' in line)
assert urlparse(values['NETBOX_SYNC_PUBLIC_URL']).hostname == 'netbox-sync-test.indeed-id.hq', 'Not the expected test Sync URL'
PY
# The installer coordinates this service; reject a shared production timer.
UNIT=$(systemctl cat netbox-sync.service)
[[ "$UNIT" == *'/netbox-sync-test/'* ]] || { echo 'Test Sync systemd ownership not confirmed.' >&2; exit 1; }
python3 "$REPO/deploy/install.py" --root /netbox-sync-test --source "$REPO" --check
python3 "$REPO/deploy/install.py" --root /netbox-sync-test --source "$REPO" --check-tls
bash "$REPO/deploy/update-selectel-test.sh"
python3 "$REPO/deploy/install.py" --root /netbox-sync-test --source "$REPO" \
  --release-id "$RELEASE" --public-url https://netbox-sync-test.indeed-id.hq
[[ $(readlink -f /netbox-sync-test/current) == "/netbox-sync-test/releases/$RELEASE" ]]
echo 'Test topology collector and Guard updated. Apply a fresh ESXi/PVE plan, then run:'
echo 'docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py host_network_check --actor admin --device 28 --device 29'
