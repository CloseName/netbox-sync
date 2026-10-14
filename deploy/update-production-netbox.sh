#!/usr/bin/env bash
# Prerequisite: run update-production-sync.sh pause on the separate Sync host.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 && $(hostname -s) == netbox ]]
[[ ${SYNC_PAUSED:-} == yes ]] || { echo 'Pause Sync first, then set SYNC_PAUSED=yes.' >&2; exit 1; }
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
RELEASE=$(git -C "$REPO" rev-parse HEAD)
[[ -z $(git -C "$REPO" status --porcelain) ]]
ROOT=$(docker inspect netbox --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}')
FILES=$(docker inspect netbox --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}')
PROJECT=$(docker inspect netbox --format '{{index .Config.Labels "com.docker.compose.project"}}')
[[ -d "$ROOT" && -n "$FILES" && -n "$PROJECT" && "$PROJECT" != '<no value>' ]]
cd "$ROOT"
COMPOSE=(docker compose --project-directory "$ROOT" -p "$PROJECT")
IFS=',' read -ra CONFIGS <<< "$FILES"
for file in "${CONFIGS[@]}"; do [[ -f "$file" ]]; COMPOSE+=(-f "$file"); done
BACKUP=$(mktemp -d /var/tmp/netbox-production-backup.XXXXXX)
echo "Backup: $BACKUP"
trap 'echo "Update stopped. Backups: $BACKUP. Keep Sync paused." >&2' ERR
"${COMPOSE[@]}" config > "$BACKUP/compose-resolved.yml"
IMAGE=$("${COMPOSE[@]}" config --format json | python3 -c 'import json,sys; s=json.load(sys.stdin)["services"]; i=s["netbox"]["image"]; assert s["netbox-worker"]["image"]==i; print(i)')
[[ "$IMAGE" == netbox-with-sync-guard:* ]]
OLD=$(docker inspect netbox --format '{{.Image}}')
[[ $(docker inspect netbox-worker --format '{{.Image}}') == "$OLD" ]]
BASE=netbox-with-sync-guard:backup-$(date +%Y%m%d-%H%M%S)
docker image tag "$OLD" "$BASE"
printf '%s\n%s\n' "$BASE" "$IMAGE" > "$BACKUP/images"
# Back up resolved configuration, original compose files and runtime config, including operator overrides.
tar -czf "$BACKUP/compose-files.tgz" -- "${CONFIGS[@]}"
docker cp netbox:/etc/netbox/config "$BACKUP/config"
[[ ! -f .env ]] || cp .env "$BACKUP/compose.env"
docker build --pull=false --build-arg "NETBOX_BASE_IMAGE=$BASE" --label "org.opencontainers.image.revision=$RELEASE" \
  -f "$REPO/deploy/Dockerfile.netbox-guard" -t "netbox-with-sync-guard:$RELEASE" "$REPO"
# Pause NetBox UI and workers too, so the database dump precedes every migration/write.
"${COMPOSE[@]}" stop netbox netbox-worker
docker exec netbox-postgres sh -ec 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner' > "$BACKUP/netbox.dump"
[[ -s "$BACKUP/netbox.dump" ]]
docker exec -i netbox-postgres pg_restore --list < "$BACKUP/netbox.dump" > "$BACKUP/dump-contents.txt"
docker image tag "netbox-with-sync-guard:$RELEASE" "$IMAGE"
"${COMPOSE[@]}" up -d --no-deps --force-recreate --pull never --wait --wait-timeout 300 netbox netbox-worker
PYTHON=/opt/netbox/venv/bin/python
MANAGE=/opt/netbox/netbox/manage.py
docker exec netbox "$PYTHON" "$MANAGE" migrate --noinput
docker exec netbox "$PYTHON" "$MANAGE" check
docker exec -i netbox "$PYTHON" "$MANAGE" shell <<'PY'
from django.conf import settings
from extras.models import CustomField
from netbox_guard.managed_fields import configure_managed_fields
from netbox_guard.navigation import menu
from netbox_guard.vm_replacement import review, execute
assert 'netbox_guard' in settings.PLUGINS
configure_managed_fields()
for name in ('esxi_host_network', 'hardware_identity'):
    f = CustomField.objects.get(name=name)
    assert f.type == 'json' and f.object_types.filter(app_label='dcim', model='device').exists(), name
    assert not f.required and not f.unique, name
    assert not getattr(f, 'validation_regex', None) and not getattr(f, 'validation_schema', None), name
    assert f.validation_minimum is None and f.validation_maximum is None, name
    assert str(getattr(f, 'status', 'active')) == 'active', (name, getattr(f, 'status', None))
    print('READY:', name)
print('READY: NetBox Sync menu, provider registry and VM replacement Guard')
PY
echo "Guard updated; object data unchanged by schema preparation. Backup: $BACKUP"
echo 'Now resume/update Sync on netbox-sync, then rebuild the ESXi plan.'
