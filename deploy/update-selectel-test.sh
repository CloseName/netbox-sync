#!/usr/bin/env bash
# Only the known TEST NetBox Guard. No database backup or production operation.
set -Eeuo pipefail
[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]] || { echo 'Run as root on netbox-test only.' >&2; exit 1; }
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
RELEASE=$(git -C "$REPO" rev-parse HEAD)
[[ -z $(git -C "$REPO" status --porcelain) ]] || { echo 'Checkout is not clean.' >&2; exit 1; }
cd /netbox-test
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOG=/var/tmp/selectel-servers-test-$STAMP.log
exec > >(tee -a "$LOG") 2>&1
trap 'echo "Stopped. Check $LOG before retrying. No automatic database rollback." >&2' ERR
CONFIGURED_IMAGE=$(docker compose config --format json | python3 -c 'import json,sys; s=json.load(sys.stdin)["services"]; i=s["netbox"]["image"]; assert s["netbox-worker"]["image"]==i; print(i)')
[[ "$CONFIGURED_IMAGE" == netbox-with-sync-guard:* ]]
ACTUAL_ROOT=$(docker inspect netbox --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}')
[[ $(realpath "$ACTUAL_ROOT") == /netbox-test ]]
BASE_ID=$(docker inspect netbox --format '{{.Image}}')
BASE_TAG=netbox-with-sync-guard:selectel-base-$STAMP
docker image tag "$BASE_ID" "$BASE_TAG"
docker build --pull=false --build-arg "NETBOX_BASE_IMAGE=$BASE_TAG" \
  --label "org.opencontainers.image.revision=$RELEASE" \
  -f "$REPO/deploy/Dockerfile.netbox-guard" -t "netbox-with-sync-guard:$RELEASE" "$REPO"
docker build --build-arg "VCS_REF=$RELEASE" -f "$REPO/tools/selectel_audit/Dockerfile" \
  -t "selectel-audit:$RELEASE" "$REPO"
docker compose stop netbox-worker netbox
docker image tag "netbox-with-sync-guard:$RELEASE" "$CONFIGURED_IMAGE"
docker compose run --rm --no-deps -T --entrypoint /opt/netbox/venv/bin/python netbox \
  /opt/netbox/netbox/manage.py migrate --noinput </dev/null
docker compose up -d --no-deps --force-recreate --pull never --wait --wait-timeout 240 netbox netbox-worker
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py check
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py migrate --check
docker exec -i netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell -c 'import sys; exec(sys.stdin.read())' <<'PY'
from netbox_guard.provider_schema import check_schema
from netbox_guard.models import ProviderBinding
from django.db import connection
check_schema()
with connection.cursor() as c:
    c.execute("SELECT pg_get_functiondef('netbox_guard_provider_write()'::regprocedure)")
    assert 'selectel_inventory' in c.fetchone()[0]
print('OK: inventory schema, protection and existing bindings:', ProviderBinding.objects.count())
PY
for container in netbox netbox-worker; do
  IMAGE_ID=$(docker inspect "$container" --format '{{.Image}}')
  [[ $(docker image inspect "$IMAGE_ID" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}') == "$RELEASE" ]]
done
docker compose ps netbox netbox-worker
echo "TEST Guard ready: $RELEASE. Log: $LOG"
echo "Next: bash $REPO/deploy/collect-selectel-test.sh 29916"
