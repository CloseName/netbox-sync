#!/usr/bin/env bash
# Interactive token entry, read-only Selectel collection, then a reviewable TEST import.
set -Eeuo pipefail
[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]] || { echo 'Run as root on netbox-test only.' >&2; exit 1; }
ACCOUNT=${1:?Usage: collect-selectel-test.sh ACCOUNT [NETBOX_ACTOR]}
ACTOR=${2:-admin}
[[ $ACCOUNT =~ ^[0-9]{1,20}$ ]]
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
RELEASE=$(git -C "$REPO" rev-parse HEAD)
[[ $(docker inspect netbox --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}') == /netbox-test ]]
umask 077
WORK=$(mktemp -d /var/tmp/selectel-servers.XXXXXX)
mkdir "$WORK/output"
chown 65532:65532 "$WORK/output"
docker run --rm -it --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  --mount "type=bind,src=$WORK/output,dst=/output" \
  "selectel-audit:$RELEASE" --profile servers --account "$ACCOUNT" --without-netbox
INPUT=$(find "$WORK/output" -type f -name inventory.json -print -quit)
[[ -n "$INPUT" ]]
TASK_DIR=$(docker exec netbox sh -c 'umask 077; mktemp -d /tmp/selectel-servers.XXXXXX')
RUNTIME_UID=$(docker exec netbox id -u)
RUNTIME_GID=$(docker exec netbox id -g)
docker cp "$INPUT" "netbox:$TASK_DIR/inventory.json"
docker exec --user 0 netbox chown "$RUNTIME_UID:$RUNTIME_GID" "$TASK_DIR/inventory.json"
docker exec --user 0 netbox chmod 600 "$TASK_DIR/inventory.json"
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py selectel_inventory \
  --input "$TASK_DIR/inventory.json" --account "$ACCOUNT" --actor "$ACTOR" --output "$TASK_DIR/review.json"
docker cp "netbox:$TASK_DIR/review.json" "$WORK/review.json"
echo "Review saved: $WORK/review.json"
python3 - "$WORK/review.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
print('Servers:', r['server_count'], 'bound:', r['bound_count'], 'unmatched:', r['unmatched_count'])
for v in r['resources']:
    if v['target']:
        print('UPDATE:', v['target'], 'changed:', v['projection_changed'])
PY
FINGERPRINT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["fingerprint"])' "$WORK/review.json")
NONCE=$(python3 -c 'import uuid; print(uuid.uuid4())')
# Save an exact repeatable command before writing, including its idempotency nonce.
printf '#!/usr/bin/env bash\nset -Eeuo pipefail\n[[ $(hostname -s) == netbox-test ]]\n' > "$WORK/apply.sh"
printf '%q ' docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py selectel_inventory \
  --input "$TASK_DIR/inventory.json" --account "$ACCOUNT" --actor "$ACTOR" \
  --apply --fingerprint "$FINGERPRINT" --nonce "$NONCE" >> "$WORK/apply.sh"
printf '\n' >> "$WORK/apply.sh"
echo "After reviewing the targets and coverage, apply with: bash $WORK/apply.sh"
echo 'This writes the server registry and provider fields on existing bound objects only.'
