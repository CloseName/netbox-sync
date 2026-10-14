#!/usr/bin/env bash
# Test acceptance rollout only. Explicitly no backup and no inventory collection.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]] || { echo 'Run only as root on netbox-test'; exit 1; }
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
RELEASE=$(git -C "$REPO" rev-parse HEAD)
[[ -z $(git -C "$REPO" status --porcelain) ]]
LOG=$(mktemp /var/tmp/selectel-v2-test-update.XXXXXX)
exec > >(tee -a "$LOG") 2>&1
trap 'echo "STOPPED. Inspect $LOG; do not repeat automatically. Test scheduler may remain paused." >&2' ERR
[[ $(docker inspect netbox --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}') == /netbox-test ]]
[[ $(systemctl cat netbox-sync.service) == *'/netbox-sync-test/'* ]]
STATE=$(docker inspect netbox-sync-bootstrap-worker | python3 -c '
import json,sys
from pathlib import Path
r=json.load(sys.stdin)[0]
p=[Path(m["Source"]).resolve() for m in r["Mounts"] if m["Destination"]=="/var/lib/netbox-sync/netbox" and m["Type"]=="bind"]
assert len(p)==1 and p[0].is_relative_to(Path("/netbox-sync-test")), "Not test Sync state"
print(p[0])')
CONFIG=$(docker inspect netbox | python3 -c '
import json,sys
from pathlib import Path
r=json.load(sys.stdin)[0]
p=[Path(m["Source"]).resolve() for m in r["Mounts"] if m["Destination"]=="/etc/netbox/config" and m["Type"]=="bind"]
assert len(p)==1 and p[0].is_relative_to(Path("/netbox-test")), "Expected test NetBox config directory mount"
print(p[0])')
python3 - "$STATE/bootstrap.json" <<'PY'
import json, os, stat, sys
from urllib.parse import urlsplit
fd=os.open(sys.argv[1], os.O_RDONLY | os.O_NOFOLLOW)
with os.fdopen(fd) as stream:
    info=os.fstat(stream.fileno())
    assert stat.S_ISREG(info.st_mode) and info.st_uid==0 and stat.S_IMODE(info.st_mode)==0o600
    assert info.st_size<=32768
    state=json.load(stream)
assert state.get('status')=='READY', 'Test bootstrap state is not ready'
assert urlsplit(state['url']).hostname=='netbox-test.indeed-id.hq', 'Not test NetBox target'
PY
python3 "$REPO/deploy/install.py" --root /netbox-sync-test --source "$REPO" --check
python3 "$REPO/deploy/install.py" --root /netbox-sync-test --source "$REPO" --check-tls
[[ -d "$STATE/selectel" && ! -L "$STATE/selectel" ]]
systemctl stop netbox-sync.timer
exec 8>"$STATE/selectel/collection.lock"
flock -w 900 8
exec 9>/run/netbox-sync/apply.lock
flock -w 300 9
docker stop --time 60 netbox-sync-bootstrap-worker
[[ ! -L "$CONFIG/zzzz_selectel_v2_test.py" ]]
CONFIG_TMP=$(mktemp "$CONFIG/.selectel-v2.XXXXXX")
install -m 644 "$REPO/deploy/selectel-v2-test-config.py" "$CONFIG_TMP"
mv -f -- "$CONFIG_TMP" "$CONFIG/zzzz_selectel_v2_test.py"
# Also works when the prior attempt left NetBox and bootstrap stopped.
# Validate the loader before building images or attempting migrations.
(cd /netbox-test && docker compose run --rm --no-deps -T \
  --entrypoint /opt/netbox/venv/bin/python netbox /opt/netbox/netbox/manage.py check </dev/null)
bash "$REPO/deploy/update-selectel-test.sh"
REMOTE=$(docker exec --user 0 netbox mktemp -d /tmp/selectel-v2-token.XXXXXX)
docker exec --user 0 netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py configure_selectel_mvp --native-resources --lifecycle --output "$REMOTE/token.json"
TOKEN=$(mktemp "$STATE/selectel/.token.XXXXXX")
docker cp "netbox:$REMOTE/token.json" "$TOKEN"
chown root:root "$TOKEN"
chmod 600 "$TOKEN"
mv -f -- "$TOKEN" "$STATE/selectel/netbox-token.json"
docker exec --user 0 netbox rm -- "$REMOTE/token.json"
docker exec -i netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell -c 'import sys; exec(sys.stdin.read())' <<'PY'
from django.conf import settings
from django.db.migrations.recorder import MigrationRecorder
assert settings.PLUGINS_CONFIG['netbox_guard']['selectel_native_reconcile'] is True
for name in ('0013_provider_creation_provenance','0014_provider_lifecycle'):
    assert MigrationRecorder.Migration.objects.filter(app='netbox_guard',name=name).exists(), name
print('OK: test native mode and migrations 0013/0014')
PY
flock -u 9
exec 9>&-
flock -u 8
exec 8>&-
python3 "$REPO/deploy/install.py" --root /netbox-sync-test --source "$REPO" --release-id "$RELEASE" --public-url https://netbox-sync-test.indeed-id.hq
docker exec --user 0 -i netbox-sync-bootstrap-worker python -B - <<'PY'
import os
from urllib.parse import urlsplit
from netbox_sync.bootstrap_state import BootstrapStore,runtime_netbox
from netbox_sync.selectel_control import read
from netbox_sync.selectel_runner import child
store=BootstrapStore(os.environ.get('NETBOX_SYNC_NETBOX_STATE_DIR','/var/lib/netbox-sync/netbox'))
url,_=runtime_netbox(store.path,'read')
assert urlsplit(url).hostname=='netbox-test.indeed-id.hq'
result=child(dict(operation='preflight',url=url,token=read(store.root/'selectel'/'netbox-token.json')['token'],guard_instance=os.environ['NETBOX_SYNC_GUARD_INSTANCE']),90)
assert result.get('ready') is True, result.get('error','IMPORT_UNCONFIRMED')
print('OK: test importer ready; no collection requested by updater')
PY
echo "TEST UPDATE COMPLETE: $RELEASE; log: $LOG; no backup created"
