# Guard VM CREATE refusal: diagnosis and operator procedure

Baseline Sync `29bd8405485277d550a382b625f35322fa59af7f`; installed Guard
`e22515ee2b21fed26912cee1c7742e594abca828`. `git diff e22515e 29bd840 --
deploy/netbox_guard` is empty. No live connections, changes, retries, dumps or backups
were made during this investigation.

## Established facts and remaining limitation

The reported 409 is an HTTP refusal, not evidence of a timeout. The original body
and Guard response code are **not persisted** by these versions. CreationReceipt
contains successful creation proof/digest, not the failed payload. A nonce is
UUID5(run UUID, source + endpoint + per-endpoint sequence); the saved plan is sorted
and is not a journal of the actual request sequence. An old event cannot recover
its missing code retrospectively. Do not infer the failed VM from display order.

Locally reproduced defect: even a known `OBJECT_INVALID` / 409 loses its code in
`worker_failure.diagnostic` and subsequent closed diagnostics. Fixed by carrying
an allowlisted `guard` structure through worker and scheduled diagnostics:
`code`, `http_status`, `resource`, `nonce`, `run_id`. Unknown response content is
never forwarded, including unknown codes; HTTP status remains available. HTTP
refusal affects the individual request only. Existing apply handling still emits
OUTCOME_UNCERTAIN after entering the write phase. Device #23 and cluster #31 must
not be forgotten because the subsequent VM request was refused.

Guard now emits `GUARD_CREATE_REFUSED` with closed code/resource/nonce and, for
serializer refusals, field + validation-code pairs. It does not log payloads,
validation messages, headers, names, passwords, tokens or VM descriptions. The
nonce joins this event to Sync's guard diagnostic, which contains run_id; the
existing worker parent log also contains the public event_id. No new public API,
permission, network, retry, migration, or capability is introduced.

**The exact live PAM rejection is not established.** Local validation failures
prove transport/diagnosis behavior, not the cause of event
`4e5dfea4-f8a4-4ac6-8777-70f56ca50c1f`. No speculative VM-field workaround was added.
Writable fields and matching serializer.source do not prove valid values.

## All 409 branches reachable from objects/create in the installed Guard

`GuardView.handle_exception` maps DependencyGuardBlocked to 409, except the explicit
permission family (403). The CREATE route, including its transaction callees, can
produce:

| Code | Condition |
| --- | --- |
| GUARD_INSTANCE_CHANGED | Pinned namespace header differs from GuardIdentity |
| REQUEST_TOO_LARGE | Request body exceeds 32768 bytes |
| REQUEST_INVALID | Malformed/envelope mismatch, unsupported resource, non-object data, id/pk/tags, invalid nonce |
| OBJECT_FIELDS_UNSUPPORTED | Unknown/read-only wire field; validated key not a model field; nonempty M2M |
| OBJECT_INVALID | Standard NetBox serializer.is_valid() returned false |
| INVALID_SOURCE | Invalid source namespace grammar |
| INVALID_CREATE | Invalid internal values/resource/cluster contract (cluster CREATE with a cluster_id); invalid internal digest |
| SOURCE_NAMESPACE_CLOSED | Generation already closed |
| REQUEST_CONFLICT | Existing nonce has another actor or wire digest |
| CREATED_OBJECT_NO_LONGER_OWNED | Existing receipt's object/claim absent or creation generation differs |
| OWNERSHIP_CONFLICT | Malformed/foreign sync identities, foreign parent claim, or parent without proven ownership |
| PLACEMENT_UNPROVEN | Unsupported/unassigned parent for scoped IP/MAC |
| PLACEMENT_CHANGED | Actual cluster differs from supplied scope, including receipt replay |

For normal VM creation the useful distinguishing branches are serializer validation,
model-field compatibility, namespace, ownership, placement, and nonce conflict.
`UNSAVED_REFERENCE` / `INVALID_CREATE_VALUE` exist for internal create_owned callers
using model-value hashing; HTTP CREATE supplies the wire digest and skips that path.
Other Guard endpoints have their own 409 codes (dependency/retirement/audit); they
are not evidence for a refusal at **objects/create**. SOURCE_NAMESPACE_BUSY is not
raised by this CREATE path: its blocking advisory lock has a finite lock timeout.

PERMISSION_DENIED and token/scope permission failures are 403. Native DRF exceptions
retain their HTTP status with REQUEST_REFUSED/AUTHENTICATION_REQUIRED; parsing or
throttling errors are not this documented 409 family. Unexpected Django model,
DB, lock or representation exceptions return 503 GUARD_UNAVAILABLE. A representation
exception may occur after commit, so it must not be recast as definite no-write.

## Read-only diagnosis of the saved candidates

Two narrow operator tools are supplied:

* `netbox_sync/guard_candidates.py` reads only the saved PLAN and the specified
  sync_runs row, using the existing lifecycle-worker DSN and SET TRANSACTION READ ONLY.
  Source, saved digest and recalculated canonical digest must agree. It exports
  VM CREATE candidates only. No provider connection or new PLAN is performed.
* NetBox management command `diagnose_sync_vm_creates` uses the **same helper and
  serializer** as CreateOwned, inside a PostgreSQL READ ONLY transaction. It never
  calls save/create, create_owned, a remote API or a POST. It reports the candidate
  index/external_id, validation field/codes and existing source creation receipts.
  It does not print VM descriptions or complete requests. Temporary FK IDs are
  refused as UNRESOLVED_PLAN_REFERENCE, never replaced with guessed IDs.

This is **SAVED_PLAN_NOT_ORIGINAL_REQUEST**, not reconstruction proof. Current
NetBox data/constraints may differ from September 28; serializer success does not
prove ownership/add/token permission checks, transaction success or safe retry.
Duplicate-name validation against an already created VM may be correct today.
The diagnostic does not change uncertain status or certify the full run outcome.
If the saved plan is missing/replaced, stop. A new discovery/plan would be new
candidate evidence, not the old failed body; it requires a separate reviewed action
and must not trigger apply. Do not clear the gate to obtain it.

### Commands for the operator (not executed on the stand)

Use a root shell. `REVIEW` is a checkout containing this reviewed change; it need
not be activated as current. No SQL edits, backup or DB dump is involved.

```sh
set -euo pipefail
ROOT=/netbox-sync-test
REVIEW="$ROOT/repo"
SOURCE=n2df674f7ae9c69958f1f8f2ea0b65e0f-esxi-fd2b076aae8743629f2c
RUN=f99b1736-be24-4626-8e8d-f270261475bd
umask 077
PRIVATE=$(mktemp -d /run/netbox-sync-guard-diagnosis.XXXXXX)
docker exec -i netbox-sync-lifecycle-worker python - --source "$SOURCE" --run-id "$RUN" < "$REVIEW/netbox_sync/guard_candidates.py" > "$PRIVATE/candidates.json"
```

Stop on nonzero exit; do not print candidates.json into a terminal/log/ticket.
This protected, transient file contains candidate infrastructure fields (including
comments), not credentials, and is not a backup. It is intentionally not stored
under releases, Git or ordinary env files. Do not regenerate the plan first.

Read only creation metadata and resolve the exact actor from the known device
receipt, without inspecting tokens. This works on the currently installed Guard:

```sh
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell -c 'from netbox_guard.models import CreationReceipt; s="n2df674f7ae9c69958f1f8f2ea0b65e0f-esxi-fd2b076aae8743629f2c"; print(list(CreationReceipt.objects.filter(source_instance=s).values("nonce","resource","object_id","actor")))'
ACTOR=$(docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell -c 'from netbox_guard.models import CreationReceipt; s="n2df674f7ae9c69958f1f8f2ea0b65e0f-esxi-fd2b076aae8743629f2c"; r=CreationReceipt.objects.get(source_instance=s,resource="device",object_id=23); print(r.actor)' | tail -n 1)
case "$ACTOR" in ''|*[!0-9]*) echo 'STOP: actor metadata ambiguous'; exit 1;; esac
```

After the separately approved Guard code update below (or an operator-prepared
one-off image with the same reviewed plugin and existing NetBox configuration),
run the management command. It does not replay the refused POST:

```sh
docker exec -i netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py diagnose_sync_vm_creates --actor-id "$ACTOR" < "$PRIVATE/candidates.json" | tail -n 1 > "$PRIVATE/report.json"
python3 -m json.tool "$PRIVATE/report.json"
```

NetBox image startup prints configuration filenames before command output;
`tail -n 1` selects the single JSON/actor line. Bash pipefail above preserves a
failed command status; stop on nonzero exit.

The report selects candidate indexes/external_ids for private inspection of the
corresponding entries in candidates.json. There is no claim that one of them was
historically the first refused VM unless independent request evidence confirms it.
If diagnosis reports SERIALIZER_VALID for every candidate, investigate the other
409 branches above; do not repeat Apply to obtain a code.

Safe existing-log search (absence cannot reconstruct old codes):

```sh
docker logs --since 2026-09-28T17:30:00Z --until 2026-09-28T17:33:00Z netbox 2>&1 | grep -E 'GUARD_CREATE_REFUSED|guard_event|objects/create'
docker logs netbox-sync-apply-worker 2>&1 | grep -F '4e5dfea4-f8a4-4ac6-8777-70f56ca50c1f'
```

## Update sequence, only after separate publication/deployment approval

1. Leave this source's schedules stopped and OUTCOME_UNCERTAIN unchanged. Do not
   repeat Apply, delete the source or recreate cluster/device. Confirm no active
   write operation before maintenance. Preserve DB volumes/config/credentials.
2. Use the reviewed full commit as RELEASE_COMMIT, verify clean checkout/exact HEAD.
   NetBox remains independently managed: retain its actual Compose project/files,
   mounts, CA, secrets and GuardIdentity. Both NetBox services must use the same
   resulting image. Stop if their imported plugin path is overridden unexpectedly.
3. Build on the **currently installed operator NetBox image**, not a guessed base:

```sh
RELEASE_COMMIT=<reviewed-full-commit>
test "$(git -C "$REVIEW" rev-parse HEAD)" = "$RELEASE_COMMIT"
test -z "$(git -C "$REVIEW" status --porcelain)"
BASE_IMAGE=$(docker inspect netbox --format '{{.Config.Image}}')
test "$(docker image inspect "$BASE_IMAGE" --format '{{.Id}}')" = "$(docker inspect netbox --format '{{.Image}}')"
GUARD_IMAGE="netbox-with-sync-guard:$RELEASE_COMMIT"
docker build --build-arg NETBOX_BASE_IMAGE="$BASE_IMAGE" -f "$REVIEW/deploy/Dockerfile.netbox-guard" -t "$GUARD_IMAGE" "$REVIEW"
```

Set netbox and netbox-worker image to GUARD_IMAGE in their **existing operator
Compose configuration**. Its filenames are not known to this repository: use the
verified existing `-f`/`-p` options; do not invent a second deployment. With that
normal invocation, `docker compose up -d --no-deps netbox netbox-worker` activates
code. There is no schema/grant migration for this fix. Verify management command
exists, then run read-only diagnosis above. Plugin update does not fix unknown data.

4. Sync code update uses its installer, with `--no-systemd` deliberately retaining
   existing unit definitions and leaving the timer stopped during investigation.
   The current units already reference ROOT/current; this patch changes no units.
   Unlike the default installer path, this does not enable/start the timer afterward.

```sh
docker build -f "$REVIEW/Dockerfile.web" -t "netbox-sync:$RELEASE_COMMIT" "$REVIEW"
python3 "$REVIEW/deploy/install.py" --root "$ROOT" --source "$REVIEW" --release-id "$RELEASE_COMMIT" --image "netbox-sync:$RELEASE_COMMIT" --public-url https://netbox-sync-test.indeed-id.hq --ingress-mode external --no-systemd
readlink -f "$ROOT/current"
python3 "$ROOT/current/deploy/compose.py" --root "$ROOT" ps
curl --fail --silent --show-error https://netbox-sync-test.indeed-id.hq/api/v1/health
if systemctl is-active --quiet netbox-sync.timer; then echo "STOP: timer unexpectedly active"; exit 1; fi
```

Expected timer inactive. Stop if activation
fails; do not reapply or auto-reconcile uncertain runs. Confirm the old run/source
still blocks writes and device #23/cluster #31 remain. Enabling schedules or resolving
the uncertain result requires separate evidence and an explicitly reviewed action.

## Local evidence

- Baseline diagnostic executed from git HEAD: known OBJECT_INVALID/409 disappears.
- Targeted transport/worker/scheduled/candidate suite: 105 passed on Linux (no skips).
  Includes real Unix worker socket: returned event_id equals the logged diagnostic;
  code/HTTP/resource/nonce/run are retained and OUTCOME_UNCERTAIN is unchanged.
- `python tests/run_guard_creation_diagnostics.py`: passed against actual NetBox
  4.7.0 + PostgreSQL 16 + Redis in unique networkless fixture containers. Valid
  candidate, duplicate-name refusal, invalid ChoiceField refusal (NetBox uses code
  `invalid`), temporary-reference refusal; read-only management command; deliberate
  write attempt rejected by PostgreSQL; candidate export CLI via SELECT-only role;
  HTTP 409 preserves code and prior device receipt. Existing authentication,
  nonce/digest conflict, lost-response receipt, ownership and closed-generation
  regressions passed. First attempt failed a test expecting DRF `invalid_choice`;
  inspected actual NetBox ChoiceField and corrected the test to `invalid`.
- `git diff --check` and parsing all changed Python sources passed.
- No production Compose/network/privilege changes; full deployment suite not rerun.
  Existing other-task containers untouched; runner removed only its own labelled
  fixtures. Docker Engine 29.7.2, desktop-linux.
- No live PAM payload was available. Live root cause remains unresolved pending
  read-only diagnosis; this change fixes evidence loss and supplies the safe tool.
