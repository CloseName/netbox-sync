#!/usr/bin/env bash
# Reviewed test environment only. Preserve the original manual account for recovery.
set -euo pipefail
umask 077
release=${1:?Pass the reviewed full commit}
[[ "$release" =~ ^[0-9a-f]{40}$ ]]
repo=/var/tmp/netbox-sync-reinstall.r2cFVc/repo
test -d /netbox-sync-test/current
test -z "$(git -C "$repo" status --porcelain)"
git -C "$repo" fetch origin main
git -C "$repo" switch --detach "$release"
test "$(git -C "$repo" rev-parse HEAD)" = "$release"
# Update Guard first and prove existing manual collection still works.
bash "$repo/deploy/pfsense/activate-test-inventory.sh" "$release"
# Existing unit paths stay valid; do not restart the stopped synchronization timer.
python3 "$repo/deploy/install.py" --root /netbox-sync-test --source "$repo" --release-id "$release" --no-systemd
systemctl stop netbox-sync.timer
echo 'Open Sources > pfSense in Sync. Keep the existing netbox-sync account until the new connection is verified.'
