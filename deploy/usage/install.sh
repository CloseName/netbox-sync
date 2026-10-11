#!/usr/bin/env bash
# Known production NetBox host only. No changes to NetBox Sync.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]]
systemctl is-active --quiet cron
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT=/netbox/containers
DEST=/netbox/usage-collector
DATA=/netbox/usage-data
EXTRA="$ROOT/docker-compose.usage.yml"
CONFIG="$ROOT/configuration/zz_usage.py"
[[ ! -e "$DEST" && ! -e "$EXTRA" && ! -e "$CONFIG" ]]
cd "$ROOT"
BASE=(docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.images.yml -f docker-compose.guard.yml)
WITH=("${BASE[@]}" -f docker-compose.usage.yml)
rollback() {
  trap - ERR
  echo 'Installation failed; disabling usage configuration.' >&2
  rm -f "$CONFIG" /etc/cron.d/netbox-usage-report
  "${BASE[@]}" up -d --no-deps --pull never --force-recreate --wait --wait-timeout 300 netbox netbox-worker || true
  echo 'Inspect container health before retrying. Installation files were retained.' >&2
  exit 1
}
trap rollback ERR
uid=$(docker exec netbox id -u netbox)
gid=$(docker exec netbox id -g netbox)
install -d -m 0755 "$DEST" "$DEST/netbox_usage"
install -d -m 0700 -o "$uid" -g "$gid" "$DATA"
install -m 0644 "$SOURCE"/netbox_usage/*.py "$DEST/netbox_usage/"
install -m 0700 "$SOURCE/report.py" "$DEST/report.py"
install -m 0700 "$SOURCE/uninstall.sh" "$DEST/uninstall.sh"
cat > "$CONFIG" <<'PY'
# Temporary usage measurement, installed explicitly by the operator.
from netbox_guard import NetBoxGuardConfig
_usage = 'netbox_usage.middleware.UsageMiddleware'
if _usage not in NetBoxGuardConfig.middleware:
    NetBoxGuardConfig.middleware = [*NetBoxGuardConfig.middleware, _usage]
PY
chmod 0644 "$CONFIG"
cat > "$EXTRA" <<'YAML'
services:
  netbox:
    volumes:
      - /netbox/usage-collector/netbox_usage:/opt/netbox-sync-guard/netbox_usage:ro
      - /netbox/usage-data:/var/log/netbox-usage
  netbox-worker:
    volumes:
      - /netbox/usage-collector/netbox_usage:/opt/netbox-sync-guard/netbox_usage:ro
      - /netbox/usage-data:/var/log/netbox-usage
YAML
chmod 0600 "$EXTRA"
"${WITH[@]}" config --quiet
"${WITH[@]}" up -d --no-deps --pull never --force-recreate --wait --wait-timeout 300 netbox netbox-worker
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell -c "from django.conf import settings; assert 'netbox_usage.middleware.UsageMiddleware' in settings.MIDDLEWARE; print('Usage middleware enabled')"
python3 "$DEST/report.py" --directory "$DATA"
cat > /etc/cron.d/netbox-usage-report <<'CRON'
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
*/15 * * * * root /usr/bin/flock -n /run/netbox-usage-report.lock /usr/bin/python3 /netbox/usage-collector/report.py --directory /netbox/usage-data
CRON
chmod 0644 /etc/cron.d/netbox-usage-report
echo 'Installed. Report: /netbox/usage-data/usage-report.txt'
echo 'During future NetBox updates include -f docker-compose.usage.yml, or uninstall this collector first.'
