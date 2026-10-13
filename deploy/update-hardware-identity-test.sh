#!/usr/bin/env bash
# Test-only collector + Guard update; no provider binding apply.
set -Eeuo pipefail
[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]] || { echo 'Run as root on netbox-test only.' >&2; exit 1; }
[[ $(docker inspect netbox --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}') == /netbox-test ]]
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
umask 077
WORK=$(mktemp -d /var/tmp/hardware-identity-check.XXXXXX)
cp "$REPO/deploy/check-provider-network-preservation.py" "$WORK/check.py"
REMOTE=$(docker exec netbox mktemp -d /tmp/hardware-identity-check.XXXXXX)
docker cp "$WORK/check.py" "netbox:$REMOTE/check.py"
docker exec --user 0 netbox chmod 644 "$REMOTE/check.py"
docker exec -e PROVIDER_CHECK_MODE=capture -e PROVIDER_CHECK_DEVICES=28,29 \
  -e "PROVIDER_CHECK_FILE=$REMOTE/before.json" netbox /opt/netbox/venv/bin/python \
  /opt/netbox/netbox/manage.py shell -c "import runpy; runpy.run_path('$REMOTE/check.py', run_name='__main__')"
docker cp "netbox:$REMOTE/before.json" "$WORK/before.json"
# Keep a repeatable, read-only acceptance check after containers are recreated.
{
  printf '#!/usr/bin/env bash\nset -Eeuo pipefail\n'
  printf 'WORK=%q\n' "$WORK"
  cat <<'CHECK'
[[ $EUID -eq 0 && $(hostname -s) == netbox-test ]]
[[ $(docker inspect netbox --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}') == /netbox-test ]]
REMOTE=$(docker exec netbox mktemp -d /tmp/hardware-identity-check.XXXXXX)
docker cp "$WORK/check.py" "netbox:$REMOTE/check.py"
docker cp "$WORK/before.json" "netbox:$REMOTE/before.json"
RUNTIME_UID=$(docker exec netbox id -u)
RUNTIME_GID=$(docker exec netbox id -g)
docker exec --user 0 netbox chown "$RUNTIME_UID:$RUNTIME_GID" "$REMOTE/check.py" "$REMOTE/before.json"
docker exec --user 0 netbox chmod 600 "$REMOTE/check.py" "$REMOTE/before.json"
docker exec -e PROVIDER_CHECK_MODE=compare -e PROVIDER_CHECK_DEVICES=28,29 \
  -e "PROVIDER_CHECK_ALLOW_BINDING_REVISION=${PROVIDER_CHECK_ALLOW_BINDING_REVISION:-0}" \
  -e "PROVIDER_CHECK_FILE=$REMOTE/before.json" netbox /opt/netbox/venv/bin/python \
  /opt/netbox/netbox/manage.py shell -c "import runpy; runpy.run_path('$REMOTE/check.py', run_name='__main__')"
CHECK
} > "$WORK/check.sh"
bash "$REPO/deploy/update-host-topology-test.sh"
docker exec -i netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell -c 'import sys; exec(sys.stdin.read())' <<'PY'
from extras.models import CustomField
from netbox_guard.managed_fields import compatible
from netbox_guard.hardware_identity import canonical
field = CustomField.objects.get(name='hardware_identity')
assert compatible(field, 'json', ('dcim.device',)), 'Incompatible hardware identity field'
assert field.ui_visible == 'hidden' and field.ui_editable == 'no'
assert canonical('system_serial', 'unknown') is None
assert canonical('service_tag', 'default') is None
assert canonical('system_serial', '0123456789') is None
print('Hardware identity schema ready. No native Device.serial or IP changes requested.')
PY
bash "$WORK/check.sh"
printf '\nAfter ESXi / Proxmox synchronization, run: bash %q\n' "$WORK/check.sh"
printf 'After Selectel metadata collection, run: PROVIDER_CHECK_ALLOW_BINDING_REVISION=1 bash %q\n' "$WORK/check.sh"
echo 'Then: docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py provider_hardware_check --account 29916 --actor admin'
echo "Acceptance baseline: $WORK/before.json"
