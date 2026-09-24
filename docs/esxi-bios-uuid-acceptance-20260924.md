# ESXi BIOS UUID compatibility — 24 September 2026

## Cause and contract

AM reports `00000000-0000-0000-0000-ac1f6be2c4da` in both `summary.hardware.uuid` and `hardware.systemInfo.uuid`. The previous host validator rejected fewer than eight nonzero bytes. AM has six. This rejection was reproduced locally (12 failing / 8 passing new contract cases before the correction). It does not establish the uniqueness or long-term stability of AM hardware.

Broadcom describes both [HostSystemInfo.uuid](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.host.SystemInfo.html) and [HostHardwareSummary.uuid](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.host.Summary.HardwareSummary.html) as BIOS identification. Neither specifies this entropy threshold. Hardware serialNumber is optional (since API 6.7); otherIdentifyingInfo is optional vendor-specific information. These may assist a physical inventory investigation but are not universally available independent identity proofs. No new mandatory privilege, serial-number heuristic, Admin override or BIOS change is introduced.

A BIOS UUID is an opaque collision key, not an RFC randomness score or cryptographic physical identity. Canonical case/braces/compact/spaced-byte forms remain compatible. Missing, malformed and nil values are unusable. Explicit all-FF and the existing single-one placeholder are refused; the latter is a retained product compatibility exclusion, not a claim that Broadcom guarantees a complete placeholder blacklist. VM UUID rules are unchanged.

Preview and Discovery now use one resolver. If both usable properties exist they must agree; disagreement yields `HOST_IDENTITY_INCONSISTENT`. One usable property with the other absent/unusable remains supported. A denied or failed hardware read is not treated as absence and is not bypassed using summary. Preview adds one bounded hardware property read (7 controlled SOAP requests total, no VM properties); Discovery reuses its run-local property cache and preserves batching. Timeouts, reaping, TLS, DNS pinning, network and privilege boundaries are unchanged.

## Admission, collisions and compatibility

- Probe evidence, not registration JSON, supplies the anchor. Exactly one HostSystem is required.
- Active, disabled, tombstoned and unfinished claims all participate in admission. DNS case/trailing dot, aliases, IP and display name do not define a second identity.
- Connection rejects a collision; final PostgreSQL reservation repeats the check atomically before secret/catalog/schedule effects. A collision means identity is already claimed, **not proof that the physical machines are the same**. No objects are merged or chosen by name.
- Same actor + source + registration nonce + immutable intent can resume a journalled attempt. Lost response/restart does not authorize a new namespace or another credential/cluster. An unfinished claim is not deleted automatically.
- Removed sources require the existing Admin recovery workflow: fresh provider identity, exact previous namespace/placement, provenance and ownership checks, revision fencing, shared lock and no active/uncertain work. Admin consent is permission, not physical proof. Same UUID on a different machine cannot be distinguished cryptographically by this contract. If hardware reuse/collision is suspected, do not confirm recovery: compare both provider UUID properties, authenticated endpoint/certificate under existing TLS policy, serial/vendor inventory and asset records; resolve contradictory evidence before proceeding. Never clear reservations with SQL.
- No DB/source IDs are rewritten. A new usable UUID differing from a NetBox host already owned by this source now fails with `HOST_IDENTITY_CHANGED`, even after a name change. Existing explicit host mappings also reject an unknown host ID. A historic `ha-host` to BIOS UUID transition is **not** silently implemented here; preserve the old object/namespace, collect its `sync_identities` and current provider evidence for a separately reviewed transition. New AM registration has no such legacy identity transition.
- The implementation does not provide hardware attestation. Without independent asset evidence it cannot prove that two appliances intentionally presenting an identical BIOS UUID are physically distinct. Conservative registration collision rejection remains in force.

## Executed local evidence

- 267 targeted Linux tests: real HTTPS/SOAP/pyVmomi, 147-VM bounded property count/completeness, hardware permission fault, inconsistent properties, old identity refusal without writes, PostgreSQL atomic reservations, API duplicate rejection, normal/AM recovery, real Unix broker continuation after lost response/restart. No skips in this set.
- 84 frontend unit tests, TypeScript and Vite build passed; existing bundle-size warning remains.
- 25 local Chromium wizard cases passed, including exact AM UUID through placement/registration, EN/RU conflict explanation, retained form, retry, permissions, duplicate links and Admin recovery UI. These browser routes are controlled fixtures, not live provider acceptance.
- Production retirement-worker with real isolated NetBox 4.7 TLS and PostgreSQL passed: retained history, receipt reconciliation, original namespace restoration. AM is used for the recovery anchor and for the real-NetBox full executor inventory. Provider input in that gate is synthetic; separate production workers exercise real controlled SOAP.
- Both production Compose cases passed (320.21s), using the actual external-ingress topology with bundled and external PostgreSQL. They cover trusted HTTPS/SOAP preview, AM registration with real broker/DB failure and restart/resume, discovery/plan/prepare/apply/replan, manual and scheduled ESXi/Proxmox, bounded failed/uncertain writes, private services and networkless broker. The bundled case also rehearsed populated installer upgrade, retaining exact source rows/mappings/ports, credentials, READY onboarding, policy, the same DB container and mount metadata. These are controlled endpoints, not live AM. No deployment, SSH, live browser, or live hypervisor access was performed.

Initial failures during test development were explicit: old tests expected zero-heavy UUID -> `ha-host`; browser fixtures omitted registration-attempts; the minimal production SOAP fixture lacked hardware property support. Fixtures were corrected and the affected sets rerun. The product was not weakened to accept incomplete/denied inventory.

## Updating an existing external-ingress installation

This update changes no NetBox guard code, migrations, permissions or protocol. **Do not rebuild/reinstall NetBox guard for this UUID fix** if the already installed f90743a guard is verified. Guard compatibility/UUID pin must already satisfy the prior release contract; container health alone is not that verification.

Run on the host yourself, after publication. Set RELEASE_COMMIT to the full published SHA from the delivery report. Commands do not read credential values. Do not execute an apply as an upgrade check.

```sh
set -eu
ROOT=/netbox-sync-test
: "${RELEASE_COMMIT:?Set the full published UUID-fix SHA}"
case "$RELEASE_COMMIT" in *[!0-9a-f]*|'') exit 1;; esac
test "${#RELEASE_COMMIT}" -eq 40
sudo readlink -f "$ROOT/current"
sudo systemctl is-active netbox-sync.timer
sudo python3 "$ROOT/current/deploy/compose.py" --root "$ROOT" ps
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" preflight
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" create
```

Record the pre-update timer/service state. Stop on unexpected state or any failure. Set BUNDLE to the exact archive directory reported by create, then:

```sh
: "${BUNDLE:?Set the exact reported backup directory}"
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" verify "$BUNDLE"
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" inspect "$BUNDLE"
test -z "$(git -C "$ROOT/repo" status --porcelain)"
test "$(git -C "$ROOT/repo" remote get-url origin)" = https://github.com/CloseName/netbox-sync.git
git -C "$ROOT/repo" fetch origin
git -C "$ROOT/repo" merge-base --is-ancestor "$RELEASE_COMMIT" origin/main
git -C "$ROOT/repo" switch --detach "$RELEASE_COMMIT"
test "$(git -C "$ROOT/repo" rev-parse HEAD)" = "$RELEASE_COMMIT"
sudo docker build -f "$ROOT/repo/Dockerfile.web" -t "netbox-sync:$RELEASE_COMMIT" "$ROOT/repo"
sudo python3 "$ROOT/repo/deploy/install.py" --root "$ROOT" --source "$ROOT/repo" --release-id "$RELEASE_COMMIT" --image "netbox-sync:$RELEASE_COMMIT" --public-url https://netbox-sync-test.indeed-id.hq --ingress-mode external
sudo readlink -f "$ROOT/current"
sudo python3 "$ROOT/current/deploy/compose.py" --root "$ROOT" ps
sudo systemctl is-active netbox-sync.timer
curl --fail --silent --show-error https://netbox-sync-test.indeed-id.hq/api/v1/health
```

Installer preserves root, config, credentials, PostgreSQL volume and completed onboarding. DB head remains0012. No --build installer flag, no new guard pin, no clearing of reserves, no recreation of DB. Stop on installer error: do not blindly rerun the immutable release ID or switch current manually. Collect only failing phase/error and container/volume/service metadata before recovery.

## Sequential operator acceptance (AM)

1. Confirm installed release, health, completed onboarding and unchanged source list. Do not enable schedules for this acceptance.
2. Add ESXi AM with its actual account, port and the already chosen per-source TLS option. Expected preview: one host and canonical AM UUID; no invalid-placeholder refusal. A conflict or pending attempt should link to/continue the existing namespace, not create another source.
3. Review exact placement; add once. Expected one source, scheduling off. In another attempt use an alias/IP with identical provider UUID: expect the existing-source conflict before cluster/credential writes. Do not force a different source ID.
4. Build plan, review all operations, then explicitly prepare/apply only if authorized for this test source. Expect successful completion; repeat plan and check no duplicate creates/updates for unchanged inventory. Record Run/event IDs; counts alone do not prove no writes.
5. As Admin choose **remove from Sync only**, with no active/uncertain operation. Record Source ID and representative NetBox IDs first. Expect retained NetBox objects/history. Do not select infrastructure retirement as a substitute for this check.
6. Reconnect the same host: expect removed-source detection and explicit Admin recovery review of previous source and placement. Confirm only when provider and asset evidence refer to the same machine. Expected restored original Source ID/NetBox IDs/history, no duplicate credentials or objects, scheduling off. Repeat plan before any further apply.
7. Stop on UUID disagreement, changed identity, foreign ownership, inconsistent placement or uncertainty; retain bounded event/code evidence, never credentials or raw provider responses. Actual AM uniqueness/stability and the live lifecycle remain operator acceptance, not a claim from local tests.

## Reproducible test entrypoints

The targeted Linux set is `test_host_uuid_contract`, `test_source_preview`, `test_esxi_property_inventory`, `test_host_registration`, `test_source_recovery_postgres`, `test_registration_continuation`, `test_esxi`, `test_esxi_adoption`, `test_esxi_migration`, `test_esxi_runtime`, `test_probe_worker`, `test_identity_compatibility`, `test_recovery_evidence`, `test_source_identity_verification` (all under tests/, pytest). It ran in an isolated root Linux container with NETBOX_SYNC_TIMEOUT_TEST=1 and NETBOX_SYNC_TEST_POSTGRES_DSN pointing only to its labelled temporary PostgreSQL. No live credentials were used.

Production image was built from Dockerfile.web, tag `netbox-sync-uuid-web:20260924`, digest `sha256:720d55c4eea93839692a5eeb8b4deae219279d40d228e91ad650ca28094e388e`. Product code was unchanged between image build and final gates; subsequent edits were tests/docs only. Compose entrypoint: `NETBOX_SYNC_AUTH_DOCKER_TEST=1 NETBOX_SYNC_WORKER_FULL_SYNC_TEST=1 NETBOX_SYNC_REVIEW_IMAGE=<built image>` with `pytest tests/test_auth_compose_docker.py`. Its temporary operator container alone has the Docker socket, without privileged mode; product services never receive it. Resource cleanup uses each unique test project label.

The separate real NetBox gate uses `tests/run_retirement_production_worker.py` with its explicit opt-in, verified owned PostgreSQL label and the same review image. It preserves its pre-existing isolated DB service and only removes resources created by its own run.

Frontend: `npm test`, `npm run build`, `npx playwright test e2e/add-source-wizard.spec.ts`. Local RU/EN screenshots are emitted under frontend/test-results by the wizard tests, containing only masked synthetic input. `git diff --check` passed. Docker context was desktop-linux, Engine29.7.2; no virtual-disk files or live systems were accessed.
