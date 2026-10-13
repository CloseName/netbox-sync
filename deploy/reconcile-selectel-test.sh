#!/usr/bin/env bash
# Idempotent account-wide runner, suitable after each successful inventory import.
set -Eeuo pipefail
[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]] || { echo 'Run on netbox-test as root.' >&2; exit 1; }
ACCOUNT=${1:?Usage: reconcile-selectel-test.sh ACCOUNT [--apply]}
MODE=${2:---review}
[[ $ACCOUNT =~ ^[0-9]{1,20}$ && ( $MODE == --review || $MODE == --apply ) ]]
[[ $(docker inspect netbox --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}') == /netbox-test ]]
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
REMOTE=$(docker exec netbox mktemp -d /tmp/provider-reconcile.XXXXXX)
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py provider_reconcile \
  --actor admin --account "$ACCOUNT" --output "$REMOTE/review.json"
[[ $MODE == --apply ]] || { echo "Review only: netbox:$REMOTE/review.json"; exit 0; }
docker cp "$REPO/deploy/check-provider-network-preservation.py" "netbox:$REMOTE/check.py"
docker exec --user 0 netbox chmod 644 "$REMOTE/check.py"
docker exec -e PROVIDER_CHECK_MODE=capture -e PROVIDER_CHECK_DEVICES=28,29 \
  -e "PROVIDER_CHECK_FILE=$REMOTE/before.json" netbox /opt/netbox/venv/bin/python \
  /opt/netbox/netbox/manage.py shell -c "import runpy; runpy.run_path('$REMOTE/check.py', run_name='__main__')"
FINGERPRINT=$(docker exec netbox /opt/netbox/venv/bin/python -c "import json; print(json.load(open('$REMOTE/review.json'))['fingerprint'])")
[[ $FINGERPRINT =~ ^[a-f0-9]{64}$ ]]
NONCE=$(python3 -c 'import uuid; print(uuid.uuid4())')
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py provider_reconcile \
  --actor admin --account "$ACCOUNT" --apply --fingerprint "$FINGERPRINT" --nonce "$NONCE" --output "$REMOTE/result.json"
docker exec -e PROVIDER_CHECK_MODE=compare -e PROVIDER_CHECK_DEVICES=28,29 \
  -e "PROVIDER_CHECK_FILE=$REMOTE/before.json" netbox /opt/netbox/venv/bin/python \
  /opt/netbox/netbox/manage.py shell -c "import runpy; runpy.run_path('$REMOTE/check.py', run_name='__main__')"
echo "Result: netbox:$REMOTE/result.json"
