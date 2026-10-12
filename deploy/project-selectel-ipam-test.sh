#!/usr/bin/env bash
# Uses the existing accepted bindings and imported registry. No credentials/API calls.
set -Eeuo pipefail
[[ $# -eq 0 || ( $# -eq 1 && $1 == --apply ) ]] || { echo 'Usage: project-selectel-ipam-test.sh [--apply]' >&2; exit 1; }
[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]] || { echo 'Run as root on netbox-test only.' >&2; exit 1; }
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
RELEASE=$(git -C "$REPO" rev-parse HEAD)
[[ -z $(git -C "$REPO" status --porcelain) ]]
[[ $(docker inspect netbox --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}') == /netbox-test ]]
IMAGE=$(docker inspect netbox --format '{{.Image}}')
[[ $(docker image inspect "$IMAGE" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}') == "$RELEASE" ]]
umask 077
WORK=$(mktemp -d /var/tmp/selectel-ipam.XXXXXX)
CONTAINER_WORK=$(docker exec netbox mktemp -d /tmp/selectel-ipam.XXXXXX)
cat > "$WORK/request.json" <<'JSON'
{"account":"29916","routing_context":"public-global","targets":[
  {"device_id":28,"provider_key":"[\"selectel\",\"29916\",\"dedicated\",\"e4ceedd1-a611-470c-a532-ea94f4f68f43\"]"},
  {"device_id":29,"provider_key":"[\"selectel\",\"29916\",\"dedicated\",\"b35f4e5e-9f52-4377-8ed9-79c35979169f\"]"}
]}
JSON
docker cp "$WORK/request.json" "netbox:$CONTAINER_WORK/request.json"
RUNTIME_UID=$(docker exec netbox id -u)
RUNTIME_GID=$(docker exec netbox id -g)
docker exec --user 0 netbox chown "$RUNTIME_UID:$RUNTIME_GID" "$CONTAINER_WORK/request.json"
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py selectel_ipam \
  --actor admin --request "$CONTAINER_WORK/request.json" --output "$CONTAINER_WORK/review.json"
docker cp "netbox:$CONTAINER_WORK/review.json" "$WORK/review.json"
FINGERPRINT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["fingerprint"])' "$WORK/review.json")
NONCE=$(python3 -c 'import uuid; print(uuid.uuid4())')
{
  printf '%s\n' '#!/usr/bin/env bash' 'set -Eeuo pipefail'
  printf '%s\n' '[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]]' \
    '[[ $(docker inspect netbox --format '\''{{index .Config.Labels "com.docker.compose.project.working_dir"}}'\'') == /netbox-test ]]'
  printf 'EXPECTED_RELEASE=%q\n' "$RELEASE"
  printf '%s\n' 'IMAGE=$(docker inspect netbox --format '\''{{.Image}}'\'')' \
    '[[ $(docker image inspect "$IMAGE" --format '\''{{index .Config.Labels "org.opencontainers.image.revision"}}'\'') == "$EXPECTED_RELEASE" ]]'
  printf 'docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py selectel_ipam --actor admin --request %q --apply --fingerprint %q --nonce %q\n' \
    "$CONTAINER_WORK/request.json" "$FINGERPRINT" "$NONCE"
  printf '%s\n' 'VERIFY_DIR=$(docker exec netbox mktemp -d /tmp/selectel-ipam-verify.XXXXXX)'
  printf 'docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py selectel_ipam --actor admin --request %q --output "$VERIFY_DIR/verify.json"\n' \
    "$CONTAINER_WORK/request.json"
  printf 'docker cp "netbox:$VERIFY_DIR/verify.json" %q\n' "$WORK/verify.json"
  printf 'python3 -c %q %q\n' 'import json,sys; r=json.load(open(sys.argv[1])); assert r["changes"] == 0, "Repeat plan has changes"; print("OK: repeat plan has no changes; management IPs preserved")' "$WORK/verify.json"
} > "$WORK/apply.sh"
chmod 700 "$WORK/apply.sh"
echo "Review saved: $WORK/review.json"
echo "Apply this reviewed plan: bash $WORK/apply.sh"
if [[ ${1:-} == --apply ]]; then
  bash "$WORK/apply.sh"
fi
