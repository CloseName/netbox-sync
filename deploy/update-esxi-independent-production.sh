#!/usr/bin/env bash
# Sync-only rollout from the verified two-host production baseline.
set -Eeuo pipefail
umask 077
root=/netbox/containers
previous=fe19677cd5d0d3f1f4481033da492adc089fbc99
repo=$(cd "$(dirname "$0")/.." && pwd)
release=$(git -C "$repo" rev-parse HEAD)
timer=netbox-sync.timer
stage=preflight
trap 'echo "UPDATE_FAILED_STAGE=$stage; check journal and $timer before retrying" >&2' ERR
[[ $EUID == 0 && $(hostname -s) == netbox-sync ]]
exec 9>/run/lock/netbox-sync-esxi-update.lock
flock -n 9
[[ -z $(git -C "$repo" status --porcelain) && ! -e "$root/production-update-state" ]]
[[ $(readlink -f "$root/current") == "$root/releases/$previous" ]]
[[ $(docker inspect -f '{{.Image}}' netbox-sync-api) == "$(docker image inspect -f '{{.Id}}' "netbox-sync:$previous")" ]]
docker exec --user 0 netbox-sync-bootstrap-worker python -B -c "from urllib.parse import urlsplit; from netbox_sync.bootstrap_state import runtime_netbox; assert urlsplit(runtime_netbox('/var/lib/netbox-sync/netbox/bootstrap.json','read')[0]).hostname == 'netbox.indeed-id.hq'"
install=(python3 -B "$repo/deploy/install.py" --root "$root" --source "$repo")
backup=(python3 -B "$repo/deploy/backup.py" --root "$root")
"${install[@]}" --check
"${install[@]}" --check-tls
"${backup[@]}" preflight
https=(curl -fsS --max-time 15 --noproxy '*' --resolve netbox-sync.indeed-id.hq:443:127.0.0.1 -o /dev/null https://netbox-sync.indeed-id.hq/)
if ! "${https[@]}"; then
    # Some installations trust their corporate CA only inside the Sync deployment.
    https+=(--cacert "$root/secrets/ca/netbox-ca.pem")
    "${https[@]}"
fi
was_active=$(systemctl show -p ActiveState --value "$timer")
[[ $was_active == active || $was_active == inactive ]]
save=$(mktemp -d /var/tmp/netbox-sync-esxi-backup.XXXXXX)
printf 'previous=%s\ntimer=%s\n' "$previous" "$was_active" > "$save/previous-state"
echo "Backup directory: $save"
stage=drain
systemctl stop "$timer"
idle=false
for ((attempt=0; attempt<180; attempt++)); do
    service=$(systemctl show -p ActiveState --value netbox-sync.service)
    runners=$(docker ps -q --filter label=com.docker.compose.project=netbox-sync --filter label=com.docker.compose.service=netbox-sync-scheduler)
    running=$(docker exec netbox-sync-postgres psql -XAt -v ON_ERROR_STOP=1 -U netbox_sync_bootstrap -d netbox_sync -c "SELECT (SELECT count(*) FROM netbox_sync.sync_runs WHERE status='RUNNING') + (SELECT count(*) FROM netbox_sync.source_operations WHERE status='RUNNING')")
    if [[ $service == inactive && -z $runners && $running == 0 ]]; then idle=true; break; fi
    sleep 5
done
[[ $idle == true ]]
stage=backup
"${backup[@]}" create --output "$save/sync"
shopt -s nullglob
bundles=("$save"/sync/netbox-sync-backup-*)
[[ ${#bundles[@]} == 1 ]]
"${backup[@]}" verify "${bundles[0]}"
stage=install
"${install[@]}" --release-id "$release" --no-systemd
stage=verify
[[ $(readlink -f "$root/current") == "$root/releases/$release" ]]
image=$(docker image inspect -f '{{.Id}}' "netbox-sync:$release")
for name in api apply-worker bootstrap-worker schedule-worker; do
    [[ $(docker inspect -f '{{.Image}} {{.State.Running}}' "netbox-sync-$name") == "$image true" ]]
done
for name in api proxy; do
    for ((attempt=0; attempt<30; attempt++)); do
        health=$(docker inspect -f '{{.State.Health.Status}}' "netbox-sync-$name")
        [[ $health == starting ]] || break
        sleep 2
    done
    [[ $health == healthy ]]
done
docker exec netbox-sync-api python -B -c "from netbox_sync.application.sync_plan import PLANNER_VERSION; assert PLANNER_VERSION == 'web-5a-20'"
"${https[@]}"
stage=scheduler
if [[ $was_active == active ]]; then systemctl start "$timer"; fi
[[ $(systemctl show -p ActiveState --value "$timer") == "$was_active" ]]
echo "PROD_UPDATE_OK: $release | timer=$was_active | backup=${bundles[0]}"
