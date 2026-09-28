# ESXi duplicate instance UUIDs: BIOS resolution and PAM acceptance

Status: local implementation and isolated runtime acceptance completed. No live
ESXi/NetBox connection, deployment, push, backup or dump is part of this work.

## Cause and identity contract

The operator independently confirmed four groups / 13 PAM VMs with shared
`config.instanceUuid` and `summary.config.instanceUuid`, but distinct BIOS UUIDs
and MoRefs. The previous mapper selected the first usable UUID per VM; it did
not examine inventory-wide uniqueness. The resulting VM_IDENTITY block was a
correct integrity refusal for those chosen keys, not evidence of NetBox duplicates.
No claim is made about why ESXi contains these duplicate instance UUIDs.

Discovery still captures the complete inventory with the existing batched
PropertyCollector and records normalized instance/BIOS UUIDs in memory. No extra
per-VM network call, ESXi write or identity-by-name fallback is introduced.
Resolution runs before planning and again in the actual ESXi executor; Discovery
comparison also uses the resolved inventory. Web prepare/apply and scheduled
execution therefore use the same algorithm with fresh NetBox reads.

1. Count BIOS UUIDs across **every VM in every discovered host of this source**,
   not only the duplicate instance group. Incomplete collection remains a failure.
2. Keep normal unique instance identities unchanged (AM/CM compatibility).
3. For a new duplicate group with usable, globally unique BIOS UUIDs and no
   ambiguous previous ownership, select
   `esxi-bios-v1/<original-instance-uuid>/<bios-uuid>`.
4. Store that key using the existing v2 `sync_identities` VM record through normal
   guarded creation. No extra custom field, DB table, token or permission is added.
   NIC keys use the same VM key plus the existing stable NIC device key.
5. On every subsequent complete read, search this source's persisted VM identities.
   Reuse its exact BIOS key even when only one group member remains or the instance
   UUID changes/disappears. Do not rewrite NetBox IDs, identities or creation claims.
   Missing provider VMs retain their existing NetBox objects under normal policy.
6. Refuse missing/duplicate BIOS evidence, multiple stored owners, a previously
   managed shared instance UUID, incompatible old BIOS/MoRef preference, or a lost
   BIOS identity for a remaining historical member. Refuse the entire plan with
   VM_IDENTITY evidence; never discard individual VMs or choose one by name/MoRef.

The original instance UUID encoded in the key is historical evidence, not a second
matching alias. Names, guest addresses and MoRefs are not used to adopt old objects.
No migration of an existing ambiguous shared-key object is included: its owner
cannot be established from the supplied evidence. Explicit legacy adoption tools
remain separate and unchanged. Old managed keys are not silently converted.

Persistence starts with the actual guarded VM creation. A changed group before
its first successful apply may legitimately invalidate a previous plan. Partial
creation retries re-use existing keys and deterministically select the remaining
new keys. If an operator deletes provenance or alters BIOS UUIDs outside Sync,
this patch cannot manufacture continuity from a name/address.

Guard creation/retirement treats external_id as an opaque nonempty source-scoped
key. Existing object-generation, parent ownership, fingerprints and creation
receipts remain authoritative. Retained-source recovery keeps its namespace and
recorded keys. Full source retirement removes owned objects through the unchanged
Guard flow and purges the namespace; fresh re-registration selects new source-scoped
identities without claiming another source's objects. No Guard/schema migration
is required for this change.

## Networking

The UUID resolver does not alter IP/MAC policy. For the reported `10.11.5.25/32`
on two VM interfaces, existing explicit `observe` mode stores both observations
and excludes the disputed IPAM assignment. Strict mode remains blocking. No IP
or MAC is stolen, and no VM is excluded to make the plan pass.

## Local evidence

- Final combined Linux suite: **359 passed**, no skips (38.12 seconds), covering
  ESXi collection/runtime/migration/adoption/identity, Guard creation, observations,
  scopes, recovery, apply, Discovery Web/transport, Proxmox and canonical plans.
  All four cross-UID worker timeout/plan cases ran. Two dependency deprecation
  warnings remain unchanged.
- The focused BIOS suite contains 16 cases. Raw discovery reproduces 13 equal
  instance identities before resolution. Cases cover whole-inventory collisions,
  unusable BIOS, legacy ownership, partial creation, group shrink, changed/lost
  instance UUID, lost BIOS/both UUIDs, foreign objects, unchanged replan and exact
  NIC-parent identity. The original ambiguity is not hidden by filtering VMs.
- Browser EN/RU durable-plan/lifecycle suite: **38 passed**. Frontend unit suite:
  **88 passed**. TypeScript/Vite and Docker build passed.
- The SOAP batch regression compares 147 VM inventories byte-for-byte with the
  previous accessor path, bounds requests and checks descriptions and timeout
  cleanup. No collection/timeout/security boundary was relaxed.
- Existing synthetic tests that copied a VM and replaced only its old external_id
  were updated to keep their new instance/BIOS evidence consistent. Their initial
  identity failures were fixture inconsistencies, not waived product validation.
- Windows lacked OpenSSL for SOAP tests; those tests were executed successfully
  in the isolated Linux image instead. No remaining skip in the final combined runs.

The first production Compose run passed both PAM registration/sync/removal cycles,
manual/scheduled AM and Proxmox, upgrade and reinstall, but its final independent
Guard exercise failed on another copied synthetic VM with stale UUID evidence.
That fixture was corrected. The repeat used project
`netbox-sync-retirement-39bcf9d46315-product` and image
`sha256:f9173820758984ff1763df2db9f26f1f6d2dcd578db44e3ef0c40902c259e5e5`.
The running API image was checked directly; all 147 backend Python files matched
the final checkout byte-for-byte. The final real Guard/worker/PostgreSQL test
passed in 73.08 seconds; the complete runner exited 0 and cleaned only its own
labelled resources.

This production run passed two PAM cycles (four duplicate groups / 13 BIOS-key
VMs plus three unique-instance VMs): guarded creation, parent/NIC ownership,
IP observations, unchanged replan, scheduled no-op, complete source removal and
same-host re-add. It also passed AM manual/scheduled compatibility, Proxmox VM/LXC,
component upgrade retaining credentials/DB volume/onboarding/policy/history,
missing-cluster retirement and isolated Sync-only reinstall. The upgrade fixture
starts at f6d297f, not a live e22515e installation. No actual AM/CM/PAM server or
user-owned NetBox was contacted. Old uncertain CM operations were not replayed.

To repeat the existing local production harness, build Dockerfile.web and supply
its reviewed local image using NETBOX_SYNC_REVIEW_IMAGE, enable
NETBOX_SYNC_GUARD_WORKER_TEST=1, NETBOX_SYNC_FULL_LIFECYCLE=1 and
NETBOX_SYNC_PAM_IDENTITIES=1, and use its explicit NETBOX_SYNC_GUARD_PG / label
validation for an isolated local PostgreSQL fixture. Run
`python tests/run_retirement_production_worker.py` with PYTHONUTF8=1.
The temporary operator container alone mounts Docker socket; product Compose
remains unchanged. Do not point this harness at a stand database.

TypeScript/Vite, Docker build and `git diff --check` passed. The existing Vite
large-chunk warning remains. No backup or dump was created.
Fixtures represent the reported shapes; they are not exported live infrastructure
or proof that PAM is fixed on the stand.

## Operator update and sequential acceptance (after publication)

Do not execute until this commit is reviewed and published separately. Keep the
existing installation, source ID, namespace, credentials, configuration, DB volume,
Guard pin and onboarding state. Do not remove/re-add PAM as an upgrade workaround.
No NetBox Guard update or permission expansion is needed for this patch.

On the operator host, set RELEASE to the reviewed full published SHA:

```sh
set -eu
ROOT=/netbox-sync-test
CHECKOUT="$ROOT/repo"
: "${RELEASE:?Set the reviewed published full commit SHA}"
case "$RELEASE" in *[!0-9a-f]*|'') exit 1;; esac
test "${#RELEASE}" -eq 40
test -z "$(git -C "$CHECKOUT" status --porcelain)"
test "$(git -C "$CHECKOUT" remote get-url origin)" = https://github.com/CloseName/netbox-sync.git
git -C "$CHECKOUT" fetch origin
git -C "$CHECKOUT" merge-base --is-ancestor "$RELEASE" origin/main
git -C "$CHECKOUT" switch --detach "$RELEASE"
test "$(git -C "$CHECKOUT" rev-parse HEAD)" = "$RELEASE"
sudo docker build -f "$CHECKOUT/Dockerfile.web" -t "netbox-sync:$RELEASE" "$CHECKOUT"
sudo python3 "$CHECKOUT/deploy/install.py" --root "$ROOT" --source "$CHECKOUT" \
  --release-id "$RELEASE" --image "netbox-sync:$RELEASE" \
  --public-url https://netbox-sync-test.indeed-id.hq --ingress-mode external
sudo readlink -f "$ROOT/current"
sudo python3 "$ROOT/current/deploy/compose.py" --root "$ROOT" ps
curl --fail --silent --show-error https://netbox-sync-test.indeed-id.hq/api/v1/health
```

Stop on any failure; no reset, hand-written config, backup/dump, or manual DB repair.
Then, sequentially through the authenticated UI:

1. Open existing PAM. Refresh Discovery and build a **new** plan. Confirm the full
   inventory is present, including all 13 members and VMs outside the groups.
2. Inspect all four groups. A globally duplicate/missing BIOS UUID or existing
   ambiguous ownership must still block with VM names and identifiers. Stop and
   investigate that evidence; do not force apply or edit UUIDs to bypass it.
3. Confirm `10.11.5.25/32` is an observation for both interfaces in the already
   approved observations mode, with no disputed IPAM assignment in the plan.
4. Only after reviewing the complete plan, confirm one normal sync. Verify the
   13 distinct VMs, their interfaces, parent relations and ownership; record their
   NetBox IDs. Rebuild: no repeated CREATE/UPDATE for unchanged data and same IDs.
5. Check AM and CM with read-only fresh plans for identity stability. Do not repeat
   any old OUTCOME_UNCERTAIN CM operation and do not trigger CM apply for this check.
6. Provider group shrink, complete removal/re-add and fault scenarios are covered
   by isolated fixtures; do not change live VM UUIDs or remove infrastructure merely
   to repeat those tests. Live PAM success remains unconfirmed until steps 1–4.
