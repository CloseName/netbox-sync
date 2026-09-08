#!/bin/sh
set -eu

install_root="${NETBOX_SYNC_ROOT:-/opt/netbox-sync}"
release_root="${install_root}/current"

cd "${release_root}"
/usr/bin/install -d -m 0750 /run/netbox-sync

# This is the sole scheduled lock boundary. The manual apply worker mounts the
# same host directory and opens the same inode.
exec /usr/bin/flock -n /run/netbox-sync/apply.lock \
  /usr/bin/python3 "${release_root}/deploy/compose.py" --root "${install_root}" \
    --profile scheduled \
    run --rm --no-deps netbox-sync-scheduler
