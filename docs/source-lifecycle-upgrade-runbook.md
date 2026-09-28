# Lifecycle upgrade and operator acceptance

**This is the earlier production backup-based procedure.** For the explicitly
no-backup disposable September 2026 rehearsal, use
[Sync-only clean reinstall](sync-only-clean-reinstall.md) and the current
[product lifecycle evidence](product-lifecycle-20260927-progress.md). Do not run
the backup commands below on that test stand. Production backup policy is unchanged.

Operator commands only. No deployment/live connection was performed during development.
Read [model and evidence](source-lifecycle-20260927.md) first.

## Preserve both products before switching

The known Sync root is `/netbox-sync-test`; NetBox is independently managed under
`/netbox-test`, services `netbox` and `netbox-worker`. Do not reconstruct configuration,
rotate credentials, change the DB volume or rerun onboarding.

```sh
set -eu
ROOT=/netbox-sync-test
sudo readlink -f "$ROOT/current"
sudo python3 "$ROOT/current/deploy/compose.py" --root "$ROOT" ps
sudo systemctl is-active netbox-sync.timer
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" preflight
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" create
: "${BUNDLE:?Set the exact successfully created backup directory}"
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" verify "$BUNDLE"
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" inspect "$BUNDLE"
```

Stop on failure. Record original service/timer state. Make and verify the independent
full NetBox backup through its existing supported procedure, including Guard tables.
Do not substitute a journal-only dump. A full vanilla NetBox logical restore was not
certified by these tests (known ltree/search_path issue); establish an operator-tested
recovery method before any production maintenance/deletion.

```sh
: "${RELEASE_COMMIT:?Set the full published reviewed commit}"
case "$RELEASE_COMMIT" in *[!0-9a-f]*|'') exit 1;; esac
test "${#RELEASE_COMMIT}" -eq 40
test -z "$(git -C "$ROOT/repo" status --porcelain)"
test "$(git -C "$ROOT/repo" remote get-url origin)" = https://github.com/CloseName/netbox-sync.git
git -C "$ROOT/repo" fetch origin
git -C "$ROOT/repo" merge-base --is-ancestor "$RELEASE_COMMIT" origin/main
git -C "$ROOT/repo" switch --detach "$RELEASE_COMMIT"
test "$(git -C "$ROOT/repo" rev-parse HEAD)" = "$RELEASE_COMMIT"
```

Stop on a dirty checkout or provenance mismatch. No reset, force or automatic merge.

## Guard first, with all NetBox consumers using the same image

Confirmed current base: `netbox-with-sync-guard:1094800-fixed`. Build the new package
on that exact locally verified image, preserving other operator code/configuration:

```sh
GUARD_IMAGE="netbox-with-sync-guard:$RELEASE_COMMIT"
sudo docker image inspect netbox-with-sync-guard:1094800-fixed --format '{{.Id}}'
sudo docker build --build-arg NETBOX_BASE_IMAGE=netbox-with-sync-guard:1094800-fixed   -f "$ROOT/repo/deploy/Dockerfile.netbox-guard" -t "$GUARD_IMAGE" "$ROOT/repo"
sudo docker run --rm --network none --read-only --cap-drop ALL   --security-opt no-new-privileges --user netbox   --entrypoint /opt/netbox/venv/bin/python "$GUARD_IMAGE" -B -c   'import pathlib,importlib.util,os; assert os.getuid()!=0; p=pathlib.Path(importlib.util.find_spec("netbox_guard").origin); assert str(p).startswith("/opt/netbox-sync-guard/"); [compile(f.read_text(),str(f),"exec") for f in p.parent.rglob("*.py")]; print("Guard package readable under non-root user")'
```

A previous PYTHONPATH environment or plugin bind mount may override the baked module.
Stop if its imported path is wrong. Do not blindly chmod configuration/secrets or copy
code into a running container. The Dockerfile gives package files readable/traversable
modes and preserves the base USER and Python search paths.

Before maintenance, check the independent NetBox Compose **complete file list and
project name** from its existing operator configuration/container labels. This repo
does not know its filenames/extra overrides and must not invent them. In the commands
below, run `docker compose` from `/netbox-test` only if its normal default invocation
resolves the existing project and both known services; otherwise append the verified
existing `-f` and `-p` options to EVERY command. Never start a second project.

```sh
cd /netbox-test
sudo docker compose config --services
sudo docker compose ps netbox netbox-worker
sudo docker compose exec -T netbox /opt/netbox/venv/bin/python   /opt/netbox/netbox/manage.py shell -c   'from netbox_guard.models import GuardIdentity; value=str(GuardIdentity.objects.get(pk=1).identifier); assert value=="37818780-136b-433f-8bce-ef9a1e5cd60a"; print(value)'
```

Stop if services/project/UUID differ. Establish the existing maintenance window:
stop new Sync jobs and wait/reconcile active/uncertain operations without replaying
apply; follow NetBox's own maintenance procedure. Set **both** service image values
to `$GUARD_IMAGE` in the operator's existing Compose configuration. This is an explicit
operator edit, not an automatic change to NetBox managed by Sync. Preserve volumes,
env, mounts, network settings and CA. Review only image/service metadata, not rendered
secret-bearing Compose output. Then, with consumers stopped through that procedure:

```sh
sudo docker compose run --rm --no-deps netbox /opt/netbox/venv/bin/python   /opt/netbox/netbox/manage.py migrate netbox_guard --noinput
sudo docker compose up -d --no-deps netbox netbox-worker
sudo docker compose exec -T --user netbox netbox /opt/netbox/venv/bin/python   /opt/netbox/netbox/manage.py shell -c   'from netbox_guard.models import GuardIdentity; from django.db.migrations.recorder import MigrationRecorder; import netbox_guard; assert netbox_guard.__file__.startswith("/opt/netbox-sync-guard/"); assert MigrationRecorder.Migration.objects.filter(app="netbox_guard",name="0004_source_closure").exists(); value=str(GuardIdentity.objects.get(pk=1).identifier); assert value=="37818780-136b-433f-8bce-ef9a1e5cd60a"; print("Guard 0004 ready",value)'
```

No new permission is auto-granted. Archive needs existing source-scoped `audit` and
`retire` on RetirementIntent plus native view on every present object/dependency.
New source CREATE requires the already reviewed create/native-add scopes for its new
Source ID. A finite old-Source-ID permission list must be extended explicitly for the
new registration; do not replace it with unrestricted scope just to pass a test.

## Sync supported installer

```sh
sudo docker build -f "$ROOT/repo/Dockerfile.web"   -t "netbox-sync:$RELEASE_COMMIT" "$ROOT/repo"
sudo python3 "$ROOT/repo/deploy/install.py"   --root "$ROOT" --source "$ROOT/repo"   --release-id "$RELEASE_COMMIT" --image "netbox-sync:$RELEASE_COMMIT"   --public-url https://netbox-sync-test.indeed-id.hq --ingress-mode external
sudo readlink -f "$ROOT/current"
sudo python3 "$ROOT/current/deploy/compose.py" --root "$ROOT" ps
curl --fail --silent --show-error https://netbox-sync-test.indeed-id.hq/api/v1/health
sudo systemctl is-active netbox-sync.timer
```

No --prepare-only/--no-start/--no-systemd for normal VM upgrade. The installer retains
the selected root, existing Guard pin, DB credentials/volume, onboarding and policy.
Stop on any failure; do not automatically rerun writes. Activation failure restores
current/config and quiesces uncertain new runtime, but does not downgrade the DB.
Do not restart an old writer after external retirement; use forward recovery and
exact receipt checks. After restoring Sync, Admin must recheck every archived receipt
before new ESXi registration; missing Guard evidence is a stop condition.

## Sequential acceptance

1. Sign in as Admin. Check old history, onboarding, mappings, schedules and credential
   presence without displaying values. Operator/Viewer must not expose removal or
   archive mutation controls; direct requests must be denied.
2. In central registration review classify old AM/SUP. First reconcile any uncertain
   run/credential dispatch. For observed-only AM review archive, inspect retained
   references, confirm once and reload. Missing objects remain a present observation;
   old Run status is unchanged. Unproved SUP device #5 must remain unchanged.
3. Add the same server normally with a new Source ID. DNS/IP aliases must not create
   a second active source; a simultaneous attempt/second server with the same UUID
   must refuse, not merge. An existing unproved object in the chosen placement is
   still protected and may require a different placement or independent evidence.
4. For a dedicated safely disposable source created under Guard, PLAN → prepare/apply
   → repeat PLAN must yield no CREATE/UPDATE. Verify the exact created object IDs.
5. Review normal **Remove Source**, inspect the exact list, confirm once. Close/reopen
   the page while pending. Only confirmed remote receipt + credential cleanup + local
   archive may show the final deletion heading. Verify the exact owned NetBox IDs are
   absent while shared catalogs/manual objects/history remain.
6. Add the same hardware again; expect a new Source ID and one active claim. Repeat
   the controlled cycle. Do not submit old consumed plans/uncertain operations as a
   test. Check schedules cannot write for the archived source.
7. A lost response must continue the original operation ID. Changed dependencies or
   denied rights must show a reason, no success. Use Inspect source objects for exact
   view-authorized dependency references. Preserve foreign/shared dependencies.

No real source removal or apply is performed by the development agent. Operator
acceptance above is deliberately limited to a reviewed disposable source; historical
AM ownership and prior unknown writes are not inferred from local fixtures.
