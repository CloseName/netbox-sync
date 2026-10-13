#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]] || { echo 'Run on netbox-test as root.' >&2; exit 1; }
ACCOUNT=${1:?Account required}
[[ $ACCOUNT =~ ^[0-9]{1,20}$ ]]
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
bash "$REPO/deploy/update-provider-menu-test.sh"
# The exact source snapshot can repair discarded names without a new IAM session.
OBSERVED=$(docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell \
  -c "from netbox_guard.models import ProviderResourceRegistry; print(ProviderResourceRegistry.objects.get(pk='$ACCOUNT').observed_at.isoformat())" | tail -n 1)
INPUT=$(python3 - "$ACCOUNT" "$OBSERVED" <<'PY'
import json, sys
from pathlib import Path
from datetime import datetime
expected = datetime.fromisoformat(sys.argv[2])
matches = []
for path in Path('/var/tmp').glob('selectel-account.*/output/*/inventory.json'):
    if path.stat().st_size > 128 * 1024 * 1024:
        continue
    try:
        document = json.loads(path.read_bytes())
        if (document.get('schema') == 'selectel-audit-v1' and document.get('account') == sys.argv[1]
                and datetime.fromisoformat(document['finished_at'].replace('Z', '+00:00')) == expected):
            matches.append(path)
    except (ValueError, KeyError):
        continue
print(str(sorted(matches)[-1]) if matches else '')
PY
)
if [[ -n $INPUT ]]; then
  REMOTE=$(docker exec netbox mktemp -d /tmp/provider-names.XXXXXX)
  docker cp "$INPUT" "netbox:$REMOTE/inventory.json"
  RUNTIME_UID=$(docker exec netbox id -u)
  RUNTIME_GID=$(docker exec netbox id -g)
  docker exec --user 0 netbox chown "$RUNTIME_UID:$RUNTIME_GID" "$REMOTE/inventory.json"
  docker exec --user 0 netbox chmod 600 "$REMOTE/inventory.json"
  docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py provider_project_names \
    --input "$REMOTE/inventory.json" --account "$ACCOUNT" --actor admin
else
  echo 'Original matching inventory.json not found; project names will arrive with the next account import.'
fi
echo 'TEST UI updated. Native reconciliation is a separate reviewed command.'
