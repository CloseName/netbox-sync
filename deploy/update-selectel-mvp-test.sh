#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]] || { echo 'Run only as root on netbox-test.'; exit 1; }
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
bash "$REPO/deploy/update-hardware-identity-test.sh"
# Resolve the existing test-only bind mount instead of guessing a secret directory.
STATE=$(docker inspect netbox-sync-bootstrap-worker | python3 -c '
import json,sys
from pathlib import Path
row=json.load(sys.stdin)[0]
paths=[m["Source"] for m in row["Mounts"] if m["Destination"]=="/var/lib/netbox-sync/netbox" and m["Type"]=="bind"]
assert len(paths)==1
p=Path(paths[0]).resolve()
assert p.is_relative_to(Path("/netbox-sync-test")), "Not the test secret directory"
print(p)
')
[[ ! -L "$STATE/selectel" ]]
install -d -m 700 "$STATE/selectel"
if [[ ! -e "$STATE/selectel/netbox-token.json" ]]; then
  REMOTE=$(docker exec --user 0 netbox mktemp -d /tmp/selectel-mvp.XXXXXX)
  docker exec --user 0 netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py \
    configure_selectel_mvp --output "$REMOTE/token.json"
  docker cp "netbox:$REMOTE/token.json" "$STATE/selectel/netbox-token.json"
  chown root:root "$STATE/selectel/netbox-token.json"
  chmod 600 "$STATE/selectel/netbox-token.json"
  docker exec --user 0 netbox rm -- "$REMOTE/token.json"
fi
docker exec --user 0 -i netbox-sync-bootstrap-worker python -B - <<'PY'
import os
from pathlib import Path
from netbox_sync.bootstrap_state import BootstrapStore, runtime_netbox
from netbox_sync.selectel_control import read
from netbox_sync.selectel_runner import child
store = BootstrapStore(os.environ.get('NETBOX_SYNC_NETBOX_STATE_DIR', '/var/lib/netbox-sync/netbox'))
url, _ = runtime_netbox(store.path, 'read')
from urllib.parse import urlsplit
assert urlsplit(url).hostname == 'netbox-test.indeed-id.hq', 'Unexpected NetBox target'
instance = os.environ.get('NETBOX_SYNC_GUARD_INSTANCE', '')
assert instance, 'Guard instance is not configured'
token = read(store.root / 'selectel' / 'netbox-token.json')['token']
result = child(dict(operation='preflight', url=url, token=token, guard_instance=instance), 90)
assert result.get('ready') is True, 'Selectel import preflight failed: ' + str(result.get('error', 'IMPORT_UNCONFIRMED'))
print('OK: test NetBox target and Selectel import permissions verified; no inventory writes.')
PY
echo 'Ready: https://netbox-sync-test.indeed-id.hq/sources/selectel'
echo 'Connect the Selectel service user, then use Collect and update. No new native bindings are applied.'
