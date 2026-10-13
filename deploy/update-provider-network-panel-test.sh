#!/usr/bin/env bash
# Update only test Guard; compare stored network facts before/after.
set -Eeuo pipefail
[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]] || { echo 'Run as root on netbox-test only.' >&2; exit 1; }
[[ $(docker inspect netbox --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}') == /netbox-test ]]
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
umask 077
WORK=$(mktemp -d /var/tmp/provider-panel-check.XXXXXX)
REMOTE=$(docker exec netbox mktemp -d /tmp/provider-panel-check.XXXXXX)
docker cp "$REPO/deploy/check-provider-network-preservation.py" "netbox:$REMOTE/check.py"
docker exec --user 0 netbox chmod 644 "$REMOTE/check.py"
docker exec -e PROVIDER_CHECK_MODE=capture -e PROVIDER_CHECK_DEVICES=28,29 \
  -e "PROVIDER_CHECK_FILE=$REMOTE/before.json" netbox /opt/netbox/venv/bin/python \
  /opt/netbox/netbox/manage.py shell -c "import runpy; runpy.run_path('$REMOTE/check.py', run_name='__main__')"
docker cp "netbox:$REMOTE/before.json" "$WORK/before.json"
bash "$REPO/deploy/update-selectel-test.sh"
REMOTE=$(docker exec netbox mktemp -d /tmp/provider-panel-check.XXXXXX)
docker cp "$REPO/deploy/check-provider-network-preservation.py" "netbox:$REMOTE/check.py"
docker cp "$WORK/before.json" "netbox:$REMOTE/before.json"
RUNTIME_UID=$(docker exec netbox id -u)
RUNTIME_GID=$(docker exec netbox id -g)
docker exec --user 0 netbox chown "$RUNTIME_UID:$RUNTIME_GID" "$REMOTE/check.py" "$REMOTE/before.json"
docker exec --user 0 netbox chmod 600 "$REMOTE/check.py" "$REMOTE/before.json"
docker exec -e PROVIDER_CHECK_MODE=compare -e PROVIDER_CHECK_DEVICES=28,29 \
  -e "PROVIDER_CHECK_FILE=$REMOTE/before.json" netbox /opt/netbox/venv/bin/python \
  /opt/netbox/netbox/manage.py shell -c "import runpy; runpy.run_path('$REMOTE/check.py', run_name='__main__')"
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py host_network_check \
  --actor admin --device 28 --device 29 --evidence
echo "Acceptance baseline: $WORK/before.json"
echo 'Test provider panel updated. Management IPs and guest assignments preserved.'
