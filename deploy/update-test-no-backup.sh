#!/usr/bin/env bash
# Operator-run update of the known test installation. No backup is created.
set -Eeuo pipefail
ROOT=/netbox-sync-test
NETBOX=/netbox-test
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
RELEASE=$(git -C "$REPO" rev-parse HEAD)
STAMP=$(date +%Y%m%d-%H%M%S)
LOG=/var/tmp/netbox-sync-update-$STAMP.log
exec > >(tee -a "$LOG") 2>&1
trap 'echo "Обновление остановлено. Журнал: $LOG. Не повторяйте без проверки ошибки." >&2' ERR
[[ $EUID -eq 0 && -d "$ROOT/current" && -d "$NETBOX" ]]
[[ -z $(git -C "$REPO" status --porcelain) ]]
echo "Обновление тестовой установки до $RELEASE. Без создания бэкапа."
python3 "$REPO/deploy/install.py" --root "$ROOT" --source "$REPO" --check
python3 "$REPO/deploy/install.py" --root "$ROOT" --source "$REPO" --check-tls
cd "$NETBOX"
CONFIGURED_IMAGE=$(docker compose config --format json | python3 -c 'import json,sys; s=json.load(sys.stdin)["services"]; i=s["netbox"]["image"]; assert s["netbox-worker"]["image"]==i; print(i)')
[[ "$CONFIGURED_IMAGE" == netbox-with-sync-guard:* ]]
BASE_ID=$(docker inspect --format '{{.Image}}' netbox)
BASE_TAG=netbox-with-sync-guard:base-$STAMP
docker image tag "$BASE_ID" "$BASE_TAG"
docker build --pull=false --build-arg "NETBOX_BASE_IMAGE=$BASE_TAG" \
  --label "org.opencontainers.image.revision=$RELEASE" \
  -f "$REPO/deploy/Dockerfile.netbox-guard" \
  -t "netbox-with-sync-guard:$RELEASE" "$REPO"
systemctl stop netbox-sync.timer
# Same host lock as the Sync installer and apply workers; wait for active writes.
exec 9>/run/netbox-sync/apply.lock
flock -w 180 9
docker image tag "netbox-with-sync-guard:$RELEASE" "$CONFIGURED_IMAGE"
docker compose up -d --no-deps --force-recreate --pull never --wait --wait-timeout 180 netbox netbox-worker
docker compose exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py check </dev/null
flock -u 9
exec 9>&-
python3 "$REPO/deploy/install.py" --root "$ROOT" --source "$REPO" \
  --release-id "$RELEASE" --public-url https://netbox-sync-test.indeed-id.hq --ingress-mode external
[[ $(readlink -f "$ROOT/current") == "$ROOT/releases/$RELEASE" ]]
IMAGE_ID=$(docker inspect --format '{{.Image}}' netbox)
[[ $(docker image inspect "$IMAGE_ID" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}') == "$RELEASE" ]]
docker compose ps netbox netbox-worker
systemctl is-active netbox-sync.timer
echo "Готово: Sync и Guard $RELEASE. Журнал: $LOG"
echo 'Для обновления удалённого сборщика pfSense один раз выполните «Подключить и собрать».'
