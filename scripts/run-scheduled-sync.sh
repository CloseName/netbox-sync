#!/bin/sh
set -eu

if [ -n "${NETBOX_SYNC_ROOT:-}" ]; then
  install_root="$NETBOX_SYNC_ROOT"
else
  script_release=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
  test "$(basename -- "$(dirname -- "$script_release")")" = releases
  install_root=$(dirname -- "$(dirname -- "$script_release")")
fi
release_root="${install_root}/current"

cd "${release_root}"
/usr/bin/install -d -m 0750 /run/netbox-sync

# A pending reconciliation gets the gap after the current run. Never interrupt
# an existing writer; the intent is released automatically when its process exits.
/usr/bin/flock -s -n /run/netbox-sync/apply.lock.reconciliation true || exit 0

# This is the sole scheduled lock boundary. The manual apply worker mounts the
# same host directory and opens the same inode.
exec /usr/bin/flock -n /run/netbox-sync/apply.lock \
  /bin/sh -c '/usr/bin/flock -s -n /run/netbox-sync/apply.lock.reconciliation true || exit 0; exec "$@"' scheduled-sync \
  /usr/bin/python3 "${release_root}/deploy/compose.py" --root "${install_root}" \
    --profile scheduled \
    run --rm --no-deps netbox-sync-scheduler
