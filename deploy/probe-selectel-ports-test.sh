#!/usr/bin/env bash
# Only provider GET requests. No NetBox import, service restart or network changes.
set -Eeuo pipefail
[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]] || {
  echo 'Run as root on netbox-test only.' >&2; exit 1;
}
ACCOUNT=${1:?Usage: probe-selectel-ports-test.sh ACCOUNT}
[[ $ACCOUNT =~ ^[0-9]{1,20}$ ]] || { echo 'Invalid account number.' >&2; exit 1; }
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
RELEASE=$(git -C "$REPO" rev-parse HEAD)
umask 077
WORK=$(mktemp -d /var/tmp/selectel-ports.XXXXXX)
mkdir "$WORK/output"
chown 65532:65532 "$WORK/output"
echo "Reports will be saved under: $WORK/output"
docker run --rm -it --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  --mount "type=bind,src=$WORK/output,dst=/output" \
  --entrypoint python "selectel-audit:$RELEASE" \
  -m selectel_audit.port_probe --account "$ACCOUNT" < /dev/tty
echo "Done. Reports: $WORK/output"
echo 'NetBox, management IPs, pfSense assignments and provider settings were not modified.'
