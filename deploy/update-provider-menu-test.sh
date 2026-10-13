#!/usr/bin/env bash
# Navigation-only release, preserving the existing registry and network facts.
set -Eeuo pipefail
[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]] || { echo 'Run on netbox-test as root.' >&2; exit 1; }
[[ $(docker inspect netbox --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}') == /netbox-test ]]
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
registry_digest() {
  docker exec -i netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell \
    -c 'import sys; exec(sys.stdin.read())' <<'PY' | tail -n 1
import hashlib, json
from netbox_guard.models import ProviderResourceRegistry, ProviderResourceRegistryChange
data = [list(model.objects.order_by('pk').values()) for model in
        (ProviderResourceRegistry, ProviderResourceRegistryChange)]
print(hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest())
PY
}
BEFORE=$(registry_digest)
[[ $BEFORE =~ ^[a-f0-9]{64}$ ]]
bash "$REPO/deploy/update-provider-network-panel-test.sh"
AFTER=$(registry_digest)
[[ "$BEFORE" == "$AFTER" ]] || { echo 'Registry/history changed during update; inspect before proceeding.' >&2; exit 1; }
docker exec -i netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell \
  -c 'import sys; exec(sys.stdin.read())' <<'PY'
from django.urls import reverse
from netbox_guard.navigation import menu
print('Navigation loaded:', menu.label)
print('Registry URL:', reverse('plugins:netbox_guard:provider_resources'))
PY
echo 'SUCCESS: menu updated; registry, history and checked network facts preserved.'
