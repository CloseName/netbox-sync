#!/usr/bin/env bash
# Account-wide READ ONLY collection. No NetBox token, imports, restarts or apply command.
set -Eeuo pipefail
[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]] || {
  echo 'Run as root on netbox-test only.' >&2; exit 1;
}
ACCOUNT=${1:?Usage: audit-selectel-account-test.sh ACCOUNT}
[[ $ACCOUNT =~ ^[0-9]{1,20}$ ]] || { echo 'Invalid account number.' >&2; exit 1; }
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
RELEASE=$(git -C "$REPO" rev-parse HEAD)
umask 077
WORK=$(mktemp -d /var/tmp/selectel-account.XXXXXX)
mkdir "$WORK/output"
chown 65532:65532 "$WORK/output"

docker build --build-arg "VCS_REF=$RELEASE" -f "$REPO/tools/selectel_audit/Dockerfile" \
  -t "selectel-audit:$RELEASE" "$REPO"
echo "Reports will be saved under: $WORK/output"
docker run --rm -it --read-only --cap-drop ALL --security-opt no-new-privileges \
  --pids-limit 64 --memory 1g --cpus 1 --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  --mount "type=bind,src=$WORK/output,dst=/output" \
  "selectel-audit:$RELEASE" --profile all --account "$ACCOUNT" --without-netbox < /dev/tty

python3 - "$WORK/output" <<'PY'
import json, pathlib, sys
reports = list(pathlib.Path(sys.argv[1]).glob('*/account.json'))
if len(reports) != 1:
    raise SystemExit('Expected exactly one account report; inspect the output directory.')
path = reports[0]
report = json.loads(path.read_text(encoding='utf-8'))
print('\n=== ACCOUNT COVERAGE ===')
print('Account:', report['account'], 'Visible projects:', report['projects_visible'])
for product in report['products']:
    print(product['title'] + ': ' + product['state_label'])
    print('  ' + product['limitations'])
print('Other catalog services:', ', '.join(report['unmapped_catalog_services']) or 'none observed')
print('Overview:', path)
print('HTML:', path.with_name('report.html'))
print('Send summary.json and account.json first; do not publish inventory.json in Git.')
print('READ ONLY: no NetBox writes, service restarts or provider resource changes.')
PY
