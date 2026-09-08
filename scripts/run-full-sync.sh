#!/bin/sh
set -eu

: "${NETBOX_SYNC_LEGACY_SOURCE_ROOT:?Set the reviewed historical checkout directory explicitly}"
cd "$NETBOX_SYNC_LEGACY_SOURCE_ROOT"

/usr/bin/install -d -m 0750 /run/netbox-sync

exec /usr/bin/flock \
  -n \
  /run/netbox-sync/apply.lock \
  /usr/bin/docker compose \
    -f compose.yml \
    -f compose.apply.yml \
    run \
    --rm \
    --no-deps \
    -v "$NETBOX_SYNC_LEGACY_SOURCE_ROOT/netbox_sync:/app/netbox_sync:ro" \
    -e PYTHONPATH=/app \
    -e SYNC_MODE=apply \
    -e APPLY_SCOPE=full \
    -e APPLY_CONFIRM=FULL_WRITE \
    netbox-sync
