#!/usr/bin/env bash
# Explicit operator import into TEST only. No provider calls or native IPAM writes.
set -Eeuo pipefail
[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]] || { echo 'Run on netbox-test as root.' >&2; exit 1; }
INPUT=${1:?Usage: import-resource-registry-test.sh REGISTRY_JSON ACCOUNT}
ACCOUNT=${2:?Account is required}
[[ -f "$INPUT" && $ACCOUNT =~ ^[0-9]{1,20}$ ]]
[[ $(docker inspect netbox --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}') == /netbox-test ]]
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
umask 077
bash "$REPO/deploy/update-provider-network-panel-test.sh"
REMOTE=$(docker exec netbox mktemp -d /tmp/resource-registry.XXXXXX)
docker cp "$INPUT" "netbox:$REMOTE/input.json"
docker cp "$REPO/deploy/check-provider-network-preservation.py" "netbox:$REMOTE/check.py"
RUNTIME_UID=$(docker exec netbox id -u)
RUNTIME_GID=$(docker exec netbox id -g)
docker exec --user 0 netbox chown "$RUNTIME_UID:$RUNTIME_GID" "$REMOTE/input.json" "$REMOTE/check.py"
docker exec --user 0 netbox chmod 600 "$REMOTE/input.json" "$REMOTE/check.py"
docker exec -e PROVIDER_CHECK_MODE=capture -e PROVIDER_CHECK_DEVICES=28,29 \
  -e "PROVIDER_CHECK_FILE=$REMOTE/before.json" netbox /opt/netbox/venv/bin/python \
  /opt/netbox/netbox/manage.py shell -c "import runpy; runpy.run_path('$REMOTE/check.py', run_name='__main__')"
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py provider_resource_registry \
  --input "$REMOTE/input.json" --account "$ACCOUNT" --actor admin --output "$REMOTE/review.json"
FINGERPRINT=$(docker exec netbox /opt/netbox/venv/bin/python -c \
  "import json; print(json.load(open('$REMOTE/review.json'))['fingerprint'])")
[[ $FINGERPRINT =~ ^[a-f0-9]{64}$ ]]
NONCE=$(python3 -c 'import uuid; print(uuid.uuid4())')
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py provider_resource_registry \
  --input "$REMOTE/input.json" --account "$ACCOUNT" --actor admin \
  --apply --fingerprint "$FINGERPRINT" --nonce "$NONCE"
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py provider_resource_registry \
  --input "$REMOTE/input.json" --account "$ACCOUNT" --actor admin --output "$REMOTE/repeat.json"
docker exec netbox /opt/netbox/venv/bin/python -c \
  "import json; r=json.load(open('$REMOTE/repeat.json')); assert r['changes']==0 and not r['writes_performed']; print('Repeat plan: no changes')"
docker exec -e PROVIDER_CHECK_MODE=compare -e PROVIDER_CHECK_DEVICES=28,29 \
  -e "PROVIDER_CHECK_FILE=$REMOTE/before.json" netbox /opt/netbox/venv/bin/python \
  /opt/netbox/netbox/manage.py shell -c "import runpy; runpy.run_path('$REMOTE/check.py', run_name='__main__')"
echo "TEST registry imported. Open /plugins/netbox-sync-guard/providers/$ACCOUNT/"
