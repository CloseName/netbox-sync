#!/usr/bin/env bash
# Update only the NetBox presentation plugin. No collection or account changes.
set -euo pipefail
umask 077
release=${1:?Pass the reviewed full commit}
[[ "$release" =~ ^[0-9a-f]{40}$ ]]
root=/netbox-test
repo=/var/tmp/netbox-sync-reinstall.r2cFVc/repo
cd "$root"
test -f docker-compose.yml
test -f docker-compose.override.yml
test -z "$(git -C "$repo" status --porcelain)"
git -C "$repo" fetch origin main
git -C "$repo" switch --detach "$release"
test "$(git -C "$repo" rev-parse HEAD)" = "$release"
web=$(docker compose ps -q netbox)
worker=$(docker compose ps -q netbox-worker)
test -n "$web"
test -n "$worker"
base=$(docker inspect "$web" --format '{{.Config.Image}}')
base_id=$(docker inspect "$web" --format '{{.Image}}')
test "$(docker image inspect "$base" --format '{{.Id}}')" = "$base_id"
test "$(docker inspect "$worker" --format '{{.Image}}')" = "$base_id"
files=$(docker inspect "$web" --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}')
test "$files" = "$root/docker-compose.yml,$root/docker-compose.override.yml"
image="netbox-with-sync-guard:$release"
docker build --build-arg "NETBOX_BASE_IMAGE=$base" -f "$repo/deploy/Dockerfile.netbox-guard" -t "$image" "$repo"

# Parse YAML using the existing NetBox runtime; retain all other configuration values.
next=$(mktemp "$root/.pfsense-inventory-override.XXXXXX.yml")
docker compose exec -T netbox /opt/netbox/venv/bin/python -c '
import sys, yaml
value=yaml.safe_load(sys.stdin)
if not isinstance(value, dict): raise SystemExit("Invalid Compose override")
services=value.setdefault("services", {})
for name in ("netbox", "netbox-worker"):
    service=services.setdefault(name, {})
    if not isinstance(service, dict): raise SystemExit("Invalid service configuration")
    service["image"]=sys.argv[1]
sys.stdout.write(yaml.safe_dump(value, sort_keys=False))
' "$image" < docker-compose.override.yml > "$next"
chmod --reference=docker-compose.override.yml "$next"
chown --reference=docker-compose.override.yml "$next"
docker compose -f docker-compose.yml -f "$next" config --quiet

systemctl stop netbox-sync.timer
install -d /run/netbox-sync
exec 9>/run/netbox-sync/apply.lock
until flock -w 30 9; do echo 'Waiting for active synchronization...'; done
cp -p docker-compose.override.yml "docker-compose.override.yml.before-$release"
mv "$next" docker-compose.override.yml
docker compose up -d --no-deps --wait --wait-timeout 300 netbox netbox-worker
docker compose exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py check

echo "NetBox pfSense panels updated. Synchronization timer remains stopped."
