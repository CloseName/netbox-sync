#!/usr/bin/env bash
# Both components, backed up; explicitly limited to the known test installation.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]] || { echo 'Run as root on netbox-test only.' >&2; exit 1; }
ROOT=/netbox-sync-test
NETBOX=/netbox-test
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
RELEASE=$(git -C "$REPO" rev-parse HEAD)
[[ -z $(git -C "$REPO" status --porcelain) && -d "$ROOT/current" && -d "$NETBOX" ]]
[[ $(docker inspect netbox --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}') == "$NETBOX" ]]
[[ $(systemctl cat netbox-sync.service) == *'/netbox-sync-test/'* ]]
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
python3 "$REPO/deploy/install.py" --root "$ROOT" --source "$REPO" --check
python3 "$REPO/deploy/install.py" --root "$ROOT" --source "$REPO" --check-tls
BACKUP=$(mktemp -d /var/tmp/netbox-vm-replacement-backup.XXXXXX)
echo "Backup directory: $BACKUP"
trap 'echo "Stopped. Preserve backups at $BACKUP; check the failed step before retrying." >&2' ERR
readlink -f "$ROOT/current" > "$BACKUP/previous-sync-release"
python3 "$REPO/deploy/backup.py" --root "$ROOT" preflight
python3 "$REPO/deploy/backup.py" --root "$ROOT" create --output "$BACKUP/sync"
shopt -s nullglob
BUNDLES=("$BACKUP"/sync/netbox-sync-backup-*)
[[ ${#BUNDLES[@]} -eq 1 ]]
python3 "$REPO/deploy/backup.py" --root "$ROOT" verify "${BUNDLES[0]}"
cd "$NETBOX"
CONFIGURED_IMAGE=$(docker compose config --format json | python3 -c 'import json,sys; s=json.load(sys.stdin)["services"]; i=s["netbox"]["image"]; assert s["netbox-worker"]["image"]==i; print(i)')
[[ "$CONFIGURED_IMAGE" == netbox-with-sync-guard:* ]]
BASE_ID=$(docker inspect --format '{{.Image}}' netbox)
BASE_TAG="netbox-with-sync-guard:vm-backup-$(date +%Y%m%d-%H%M%S)"
docker image tag "$BASE_ID" "$BASE_TAG"
printf '%s\n' "$BASE_ID" "$BASE_TAG" "$CONFIGURED_IMAGE" > "$BACKUP/previous-netbox-image"
docker compose config > "$BACKUP/netbox-compose-resolved.yml"
docker build --pull=false --build-arg "NETBOX_BASE_IMAGE=$BASE_TAG" \
  --label "org.opencontainers.image.revision=$RELEASE" \
  -f "$REPO/deploy/Dockerfile.netbox-guard" -t "netbox-with-sync-guard:$RELEASE" "$REPO"
systemctl stop netbox-sync.timer
exec 9>/run/netbox-sync/apply.lock
flock -w 180 9
docker exec netbox-postgres sh -ec 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner' > "$BACKUP/netbox.dump"
[[ -s "$BACKUP/netbox.dump" ]]
docker exec -i netbox-postgres pg_restore --list < "$BACKUP/netbox.dump" > "$BACKUP/netbox-dump-contents.txt"
CONFIG_FILES=()
for path in .env docker-compose.yml docker-compose.override.yml compose.yml compose.yaml compose.override.yml configuration; do
  [[ ! -e "$path" ]] || CONFIG_FILES+=("$path")
done
[[ ${#CONFIG_FILES[@]} -gt 0 ]]
tar -czf "$BACKUP/netbox-config.tar.gz" -- "${CONFIG_FILES[@]}"
docker image tag "netbox-with-sync-guard:$RELEASE" "$CONFIGURED_IMAGE"
docker compose up -d --no-deps --force-recreate --pull never --wait --wait-timeout 180 netbox netbox-worker
docker compose exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py check </dev/null
docker compose exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell -c \
  'from netbox_guard.vm_replacement import review, execute; print("OK: VM replacement Guard available")' </dev/null
flock -u 9
exec 9>&-
python3 "$REPO/deploy/install.py" --root "$ROOT" --source "$REPO" --release-id "$RELEASE"
[[ $(readlink -f "$ROOT/current") == "$ROOT/releases/$RELEASE" ]]
docker exec -i netbox-sync-bootstrap-worker python -B - <<'PY'
from netbox_sync.application.sync_plan import PLANNER_VERSION
assert PLANNER_VERSION == 'web-5a-17'
print('OK: replacement planner installed. Rebuild the plan before syncing.')
PY
echo "Updated test Guard and Sync. Backups: $BACKUP"
echo 'No inventory synchronization was requested by this script.'
