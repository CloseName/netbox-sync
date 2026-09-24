# Legacy admission and scoped Guard audit — 24 September 2026

Base: 2440575cf098351722c0d7db9f52fa716f669b8e. This release supersedes the Guard upgrade statements for that earlier UUID-only fix. Live systems were not accessed.

## Confirmed causes and solution

All ESXi registry rows without an anchor, including tombstones, previously gated every new registration. This did not prove that AM and SUP were the same server. The new Admin-only investigation is available directly in the blocked wizard and on active/removed source pages. It reads the old source's saved endpoint, port and TLS option. If the existing destination policy refuses the saved old endpoint, Admin must review that exact hostname in the existing destination-permission settings; no network exception is added automatically. A probe requires separately entered credentials for that old source; it never reuses AM credentials, writes a credential file, or edits a NetBox object.

Admin can record either:

- **Observed endpoint UUID**: a fresh, actor/source/revision-bound probe records the key only in `legacy_admission.observed_uuid`, never in verified `provider_identity`, and reserves that observed BIOS key against duplicate registrations. This is explicitly NOT proof of physical continuity or historical object ownership. A conflicting retained or pending UUID claim refuses the decision; no automatic merge. Both administrative decisions explicitly confirm disabling the old row; runtime writes remain blocked. This decision does not reactivate it or authorize restoration of old objects; independent historical identity and placement evidence remain required.
- **Isolate unverified record**: for an unavailable/decommissioned old endpoint, a reason and explicit confirmation record an append-only administrative admission decision. The old row is disabled, scheduling is disabled, old plans invalidated. Source ID, tombstone, credentials, history and reservations remain. No UUID is invented. New registration may proceed outside the old protected site/cluster. This is permission to admit an unrelated registration despite incomplete history, not proof of difference or ownership.

Every unresolved legacy row requires its own decision. Known UUID collisions and pending attempts still gate connection and atomic registration. A shared PostgreSQL admission lock covers registration side effects; Admin decisions take its exclusive counterpart plus the unchanged shared apply/source locks. Active/uncertain writes, pending recovery and retirement refuse changes. Nonce, actor and row revision fence retries; the same decision survives an API restart without retaining the probe credential. Decisions are included in ordinary Sync backups.

For old ownership, inspect recorded source identities and Guard object inventory. Recovery requires the original Source ID, provider BIOS UUID, original placement and unambiguous source provenance; retained recovery does not grant deletion. If old objects record `ha-host` rather than a BIOS UUID, or no original placement/provenance survives, recovery stays blocked. This release does not invent that missing evidence or implement historical identity conversion. Preserve the objects and collect original source/provisioning audit and current provider/asset identity for a reviewed transition. Isolation still permits AM in a separate placement, without deleting SUP infrastructure. Identical BIOS UUIDs are collision keys, not hardware attestation.

The live Guard denial's exact missing right is still unknown. Code inspection confirmed audit uses the **apply integration token** from protected bootstrap.json through the NetBox-only retirement-worker, not the read token or the signed-in Sync Admin's permissions. Audit creates an AUDIT_ONLY journal record, so NetBox's native write-enabled-token restriction applies. The former `retire_retirementintent` requirement was unnecessarily coupled to deletion authorization. New native `audit_retirementintent` is source constrained, independently of `retire`; neither an audit receipt nor audit permission can authorize deletion. Native NetBox object view constraints remain enforced for every present object; refusal returns no hidden object references.

Closed diagnostics distinguish token authentication failure, token write restriction, missing Guard audit permission, source scope denial and object view denial. The configured integration validation checks pinned capabilities/audit permission/token write setting with the apply token. These are preliminary checks: actual source/object scope is checked on each audit. Health alone is insufficient. Older Guard capabilities fail closed until its independent update; UUID must be retained.

## Separate NetBox update and minimum permissions

NetBox remains operator managed. First take its independently supported complete backup and record the verified Compose file/project, web/background service names, plugin bind mount versus baked image, Python/manage.py paths and Guard UUID. Never print token strings, env contents or private keys. Do not substitute the known journal-only backup for a complete NetBox recovery procedure.

1. Update **only** `deploy/netbox_guard` in the existing NetBox plugin build or verified bind mount. Use the conditional package-copy/build procedure in [the upgrade runbook](source-sync-upgrade-runbook.md#3-update-the-independently-installed-netbox-guard-first). Web and background services must run the same code. No guessed NetBox paths or new Compose topology are provided.
2. Run the new **0003_audit_permission** migration using the independently verified image/entrypoint, before resuming traffic. It changes model permission metadata, not claims, infrastructure, triggers or GuardIdentity. With confirmed service/path variables:

```sh
: "${NETBOX_COMPOSE:?Verified NetBox Compose file}"
: "${NETBOX_WEB_SERVICE:?Verified service name}"
: "${NETBOX_PYTHON:?Verified image Python path}"
: "${NETBOX_MANAGE:?Verified manage.py path}"
sudo docker compose -f "$NETBOX_COMPOSE" run --rm --no-deps "$NETBOX_WEB_SERVICE" \
  "$NETBOX_PYTHON" "$NETBOX_MANAGE" migrate netbox_guard --noinput
```

For a baked image, build/select that new image in the independent NetBox deployment first; running the old image cannot apply 0003. Honor that deployment's own entrypoint conventions and maintenance procedure. Restart its consumers using the independently verified Compose definition. Do not rotate UUID `37818780-136b-433f-8bce-ef9a1e5cd60a` on the reported installation.

3. For the user that owns Sync's **apply token**, add a native NetBox ObjectPermission for object type **netbox_guard / retirement intent**, action **audit**, with an explicit allowed source constraint. Example for the reported SUP only:

```json
{"source_instance": "esxi-07ea06c0bbf745d3b037"}
```

For an approved finite set use `source_instance__in` with exact Source IDs. Do not use empty constraints as a workaround. Sync role Admin is independent; Operator/Viewer cannot call its audit or legacy-decision routes. No extra privilege on the read token is required. The apply token must be enabled, unexpired, write-enabled, and allow the actual retirement-worker network address under any token IP restriction. AUDIT_ONLY needs no native `add/change/delete_retirementintent`, `retire`, generic delete or superuser grant; the Guard endpoint authorizes its private journal through native `audit` on the persisted source-bound record.

The exact native ObjectPermission can also be added through the verified NetBox management command below. This is an explicit operator configuration step, not a Sync API permission or an automatic upgrade grant. Set NETBOX_SERVICE_USER_ID to the numeric owner of the **apply** token after inspecting account metadata. The command creates only SUP audit scope; an existing conflicting permission aborts without changing it.

```sh
: "${NETBOX_SERVICE_USER_ID:?Numeric ID of the verified integration service user}"
sudo docker compose -f "$NETBOX_COMPOSE" exec -T \
  -e SYNC_SERVICE_USER_ID="$NETBOX_SERVICE_USER_ID" "$NETBOX_WEB_SERVICE" \
  "$NETBOX_PYTHON" "$NETBOX_MANAGE" shell <<'PY'
import os
from django.db import transaction
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from users.models import ObjectPermission
from netbox_guard.models import RetirementIntent
source = "esxi-07ea06c0bbf745d3b037"
with transaction.atomic():
    user = get_user_model().objects.get(pk=int(os.environ["SYNC_SERVICE_USER_ID"]))
    assert user.is_active and not user.is_superuser, "Select the dedicated active service user"
    ct = ContentType.objects.get_for_model(RetirementIntent)
    scope = {"source_instance": source}
    permission, created = ObjectPermission.objects.get_or_create(
        name="netbox-sync-audit-" + source,
        defaults={"enabled": True, "actions": ["audit"], "constraints": scope})
    if created:
        permission.object_types.add(ct)
        permission.users.add(user)
    else:
        assert permission.enabled and permission.actions == ["audit"] and permission.constraints == scope
        assert set(permission.object_types.values_list("pk", flat=True)) == {ct.pk}
        assert set(permission.users.values_list("pk", flat=True)) == {user.pk}
        assert not permission.groups.exists(), "Review existing permission; no automatic overwrite"
print("Scoped audit permission is ready; no retirement or object-view privilege added")
PY
```

4. Provide native **view** permission for the exact allowed inventory: dcim.device/interface/macaddress; virtualization.cluster/virtualmachine/vminterface/virtualdisk; ipam.ipaddress. Apply explicit approved object IDs or appropriate model-specific placement constraints; relations differ across models, so do not paste one cluster filter onto all models. For example `{"id__in":[<approved IDs>]}` is an exact native scope for each model. Audit fails closed if even one matching present object is outside view scope. Add/change rights used by ordinary synchronization and `create` on CreationReceipt remain separate and unchanged. `retire` on RetirementIntent is needed only for separately authorized retirement, with its existing ownership/dependency review. Do not grant it just to enable audit.

Metadata-only checks (no token values):

```sh
sudo docker compose -f "$NETBOX_COMPOSE" exec -T "$NETBOX_WEB_SERVICE" \
  "$NETBOX_PYTHON" "$NETBOX_MANAGE" shell -c \
  'from netbox_guard.models import GuardIdentity; from django.contrib.auth.models import Permission; from django.db.migrations.recorder import MigrationRecorder; print("guard UUID:", GuardIdentity.objects.get(pk=1).identifier); print("migration:", MigrationRecorder.Migration.objects.filter(app="netbox_guard", name="0003_audit_permission").exists()); print("audit permission:", Permission.objects.filter(content_type__app_label="netbox_guard", codename="audit_retirementintent").exists())'
```

In NetBox's native user/permissions/token administration inspect only username, enabled/expiry/write-enabled/allowed IP metadata, permission actions/object types/constraints. Do not open or share the token string. Then retry **Inspect source objects** in Sync: a source-specific code identifies the next boundary without remote exception text. With approved permissions it returns the inventory; it does not delete or adopt. If an intermediary denies the request before Guard can classify it, the generic refusal remains possible; collect status/safe code, not response bodies.

## Update NetBox Sync on /netbox-sync-test

Operator runs these after publication and the independent Guard update. Set RELEASE_COMMIT to the full delivered SHA; preserve current/config/secrets/volumes and the existing Guard pin. No reenrollment or env-file recreation.

```sh
set -eu
ROOT=/netbox-sync-test
: "${RELEASE_COMMIT:?Set the full published release SHA}"
case "$RELEASE_COMMIT" in *[!0-9a-f]*|'') exit 1;; esac
test "${#RELEASE_COMMIT}" -eq 40
sudo readlink -f "$ROOT/current"
sudo systemctl is-active netbox-sync.timer
sudo python3 "$ROOT/current/deploy/compose.py" --root "$ROOT" ps
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" preflight
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" create
```

Record original service/timer state; stop on an unexpected state. Set BUNDLE to the exact bundle directory returned by create:

```sh
: "${BUNDLE:?Exact successful backup bundle directory}"
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" verify "$BUNDLE"
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" inspect "$BUNDLE"
test -z "$(git -C "$ROOT/repo" status --porcelain)"
test "$(git -C "$ROOT/repo" remote get-url origin)" = https://github.com/CloseName/netbox-sync.git
git -C "$ROOT/repo" fetch origin
git -C "$ROOT/repo" merge-base --is-ancestor "$RELEASE_COMMIT" origin/main
git -C "$ROOT/repo" switch --detach "$RELEASE_COMMIT"
test "$(git -C "$ROOT/repo" rev-parse HEAD)" = "$RELEASE_COMMIT"
# Complete the independent Guard update above from this checked-out release first.
sudo docker build -f "$ROOT/repo/Dockerfile.web" -t "netbox-sync:$RELEASE_COMMIT" "$ROOT/repo"
sudo python3 "$ROOT/repo/deploy/install.py" --root "$ROOT" --source "$ROOT/repo" \
  --release-id "$RELEASE_COMMIT" --image "netbox-sync:$RELEASE_COMMIT" \
  --public-url https://netbox-sync-test.indeed-id.hq --ingress-mode external
sudo readlink -f "$ROOT/current"
sudo python3 "$ROOT/current/deploy/compose.py" --root "$ROOT" ps
sudo systemctl is-active netbox-sync.timer
curl --fail --silent --show-error https://netbox-sync-test.indeed-id.hq/api/v1/health
```

Stop on any failure; do not blindly rerun an immutable release ID, recreate credentials/volumes, clear reservations or move current manually. Sync migration head remains `0012`. Installer adds lifecycle SELECT only for provider/anchor/source_instance in host_reservations; journal remains append-only, registration is insert-only. Broker stays network_mode:none; lifecycle remains DB-only; API has neither NetBox token nor new egress. Existing timeouts, reaping, shared apply lock, TLS/CA and public authority are unchanged.

## Sequential live acceptance (operator only)

1. Sign in as Admin, check release/READY/unchanged sources. Do not enable schedules for this acceptance. Run integration validation with the already configured token; if Guard check fails, correct only the reported scoped permission/configuration.
2. Start AM with its real endpoint/account/TLS settings. If SUP remains unknown, the wizard explains missing evidence rather than claiming it is AM. Open **Review this legacy record** inline.
3. For SUP, enter its own credentials and probe its saved endpoint, or record **Isolate unverified record** with a reason if unavailable/decommissioned. Never enter AM credentials as evidence for SUP. Expect retained SUP Source ID/history/tombstone and no NetBox deletion. Other unresolved legacy rows require individual decisions. A UUID collision refuses automatic merging.
4. Recheck AM; select its approved separate placement, review and register once. Expect one source, scheduling off. Aliases/IP of the same BIOS key must point to that existing source. An isolated legacy placement must not be reused to bypass ownership checks.
5. Review AM PLAN, explicitly prepare/apply only that reviewed test source, then rebuild: unchanged input should yield no duplicate CREATE/UPDATE. Capture Run/event IDs; zero counters alone do not establish absence of prior writes.
6. On SUP choose **Inspect source objects**. Expect exact authorized references or one safe refusal category. Never invoke retirement merely to resolve admission. Compare metadata without printing secrets.
7. Separately, on an approved disposable synced source, test retain-only removal/recovery of the original namespace and IDs; distinguish this from separately reviewed complete guarded retirement then re-add/recovery. Both preserve Run History; no recovery may adopt another source or convert ha-host implicitly. Stop on uncertain operations and collect their original receipts.

## Local evidence

All checks use isolated local resources. Provider endpoints are controlled HTTPS/SOAP fixtures, not live hypervisors. Actual AM/SUP identity, historical provenance and the original live permission cause remain operator acceptance.

| Requirement | Executed evidence | Result / boundary |
| --- | --- | --- |
| Active, disabled, removed/no-credentials legacy row; multiple unknown rows; AM admission | `tests/test_legacy_admission.py`, actual PostgreSQL | 20 passed in the final targeted run. Includes separate old credentials, no persisted secret or verified identity, protected old placement, UUID collision/pending reservation, changed revision, concurrent decisions, durable same-actor retry after API restart, Admin/Operator/Viewer and active/uncertain-run refusal. |
| Existing registration, identity/recovery/lifecycle, transport and integrity contracts | Linux selection of 22 related test modules (command below) | 488 passed, 1 skipped. The skip was only host Compose rendering because the Linux runner has no Docker CLI; that exact test passed separately with host Docker. Targeted runs below overlap this selection and are not additional disjoint totals. |
| Bootstrap capability status survives worker/client/public API projection | `test_first_run.py`, `test_first_run_transport.py`, `test_prerequisite_preparation.py` | 68 passed after fixing the public DTO allowlist to include the new Guard check and its three closed bootstrap codes. Unrecognized remote codes remain rejected. |
| Least DB grants and complete backup/restore | `test_deployment_postgres.py`, `test_backup_restore_postgres.py`, actual PostgreSQL/pg_dump | 13 passed. Lifecycle may select only the three reservation identity columns, cannot read actor details/update/delete claims; restored legacy decisions/settings and other rows match the backup. |
| Native NetBox authorization | `netbox_guard_http_scenario.py` via `run_retirement_production_worker.py`, actual NetBox 4.7.0 + PostgreSQL | Invalid/revoked/v2 tokens, write-disabled token, missing audit permission, wrong source scope, denied object view, successful exact-ID view + source-scoped audit, AUDIT_ONLY execution refusal. No superuser/retire/CRUD intent privilege needed for successful audit. Guard model migration check reports no pending model changes. |
| Lifecycle modes stay separate | `test_retirement_production_worker.py` through the same isolated real-NetBox harness | 1 passed. Production retirement-worker, retain-only history/tombstone, uncertain receipt continuation, verified retirement finalization, recovery of the same Source ID, re-add/full executor paths for ESXi and Proxmox. Unknown `ha-host` ownership is not converted by these tests. The separate opt-in retirement runtime test also passed. |
| Final production workers, browser continuation and upgrade | `test_auth_compose_docker.py` with all full-sync/browser gates enabled (command below) | Bundled and external PostgreSQL variants; exact AM BIOS UUID and HTTPS port 8443; manual and scheduled ESXi and Proxmox VM/LXC; plan → prepare/apply → unchanged replan; mapping/uncertainty fences; populated installer upgrade preserves source rows, mappings, credentials, config, READY/policy and the same DB container/volume. Final-image result is recorded below. |
| Actual browser/API legacy resolution | `frontend/scripts/production-legacy-browser.mjs` invoked by the production scenario | Built SPA → real API/DB legacy refusal → inline Admin isolation → preserved AM form → actual probe → placement. Browser transport adapts HTTP to the private API Unix socket, not mocked application responses. The subsequent registration/manual/scheduled cycle runs via the API in the same scenario. |
| Full wizard including final registration, EN/RU | `frontend/e2e/add-source-wizard.spec.ts` | 27 passed (fixture-backed API), including both language variants for legacy resolution. These do not substitute for the production worker checks. |
| Frontend and deployment model | Frontend unit suite, TypeScript/Vite, standalone/external Compose models | 84 unit tests passed; final image builds with TypeScript/Vite. Standalone proxy retains 80/443; external publishes neither; broker remains network_mode:none; API/DB/workers have no published ports; one valid proxy tmpfs mount. Existing Vite bundle-size warning remains. |

The broad Linux selection was executed with `NETBOX_SYNC_TIMEOUT_TEST=1` against a dedicated PostgreSQL database and unique disposable schemas, with the repository mounted read-only:

```sh
python -m pytest -q -rs -p no:cacheprovider \
  tests/test_legacy_admission.py tests/test_host_registration.py \
  tests/test_source_identity_verification.py tests/test_first_run.py \
  tests/test_first_run_transport.py tests/test_retirement_transport.py \
  tests/test_retirement_auth_api.py tests/test_onboarding.py \
  tests/test_onboarding_postgres.py tests/test_operator_registration.py \
  tests/test_source_recovery_postgres.py tests/test_registration_continuation.py \
  tests/test_recovery_evidence.py tests/test_source_lifecycle_postgres.py \
  tests/test_host_uuid_contract.py tests/test_source_preview.py \
  tests/test_esxi_property_inventory.py tests/test_deployment_foundation.py \
  tests/test_backup_restore.py tests/test_retirement_journal_postgres.py \
  tests/test_retirement_review.py tests/test_guarded_creation.py
```

Production gate invocation on the local test host:

```sh
NETBOX_SYNC_AUTH_DOCKER_TEST=1 \
NETBOX_SYNC_WORKER_FULL_SYNC_TEST=1 \
NETBOX_SYNC_BROWSER_FULL_SYNC_TEST=1 \
NETBOX_SYNC_REVIEW_IMAGE=netbox-sync-legacy-audit-publish:20260924 \
python -m pytest -q -s -p no:cacheprovider tests/test_auth_compose_docker.py
```

This uses unique Compose projects and labelled test resources; the operator test container alone can access Docker, without privileged mode. Product Compose has no Docker socket. No live systems or foreign resources were modified. The real NetBox gate used the same final backend; the last UI-only confirmation wording was additionally rebuilt and passed through the final production image. Image manifest-list digest: `sha256:21d73796d19029aecf12eab84d716d2ec669935541e6c2425967fdcc6f149278`.

Final production-image gate: **2 passed in 384.22 seconds**, bundled and external PostgreSQL, on the image above. `git diff --check` passed. The single broad-suite skip was closed by `tests/test_deployment_foundation.py::test_canonical_compose_renders_without_provider_configuration` on the Docker-enabled host (1 passed).

### Explicit acceptance limits

- This proves the supported admission and authorization mechanisms locally, not the physical identity or NetBox ownership of the two reported real servers.
- An Admin decision does not repair missing historical evidence or reactivate an unproved old source. Old objects, manual data and history remain protected; a source with historical `ha-host` requires a separately reviewed provenance transition.
- The exact live Guard denial is unknown until the operator checks the new safe code/account metadata. Existing token IP restrictions or an intermediary may refuse before Guard can classify the cause.
- Guard code and migration 0003 plus explicit scoped audit permission are required operator steps. The upgrade does not silently grant them.
