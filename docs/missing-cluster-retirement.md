# Retirement after an externally removed cluster

Case: source `n2df674f7ae9c69958f1f8f2ea0b65e0f-esxi-e2eaffeaaa054033b04a`,
cluster `14`, operation `b0496a60-ab40-4b31-8210-d902bc52ae68`.
No live system was accessed during this fix. No backup or dump is permitted on
this disposable stand. No unrelated NetBox data may be changed.

## Cause and corrected contract

The old complete-source inventory could be empty after external cluster deletion,
but `_cluster_fingerprint` still required that cluster to exist. OBJECT_MISSING
was also absent from the transport's known refusal vocabulary, so a definite
409 was presented as GUARD_RESPONSE_UNCONFIRMED. Absence is not proof that a prior
retirement succeeded, and a cluster-only inventory cannot prove no detached
source objects remain.

The corrected Guard checks under its existing certified DB dependency fence:

- actual cluster presence, not a caller-provided absence flag;
- every active creation claim and historical creation-receipt ID for the source;
- every supported model's source identities, independent of cluster/parent FKs;
- every object ID in the original immutable retirement manifest.

A surviving VM, host, interface, disk, IP, MAC or cluster reached through any of
these references blocks absence completion. This includes detached objects, lost
active claims, changed metadata and reused historical IDs. The code does not delete
or adopt those objects. Inspect their ownership/dependencies through the existing
Admin UI; resolve the specific conflict separately, preserving foreign/shared data.
No name/IP matching, arbitrary choice, fake VRF or broad cleanup is introduced.

Only proven complete absence permits an atomic real RetirementReceipt and source
generation seal. `deleted` is empty: externally removed objects are not reported as
Sync deletions. For an old nonempty manifest, `already_absent` accounts for its exact
keys; digest/manifest/nonce are unchanged. Sync accepts only an exact complete
partition (this path permits no mixed deletion/absence), then uses its normal
credential/file verification and constrained purge. This is not a forged receipt
or direct row-removal workaround. Interrupted receipt creation rolls back the seal;
an exact retry is safe. A replacement object with the same ID blocks completion.

Sync still checks shared apply lock, revision/generation, other source ownership,
running operations, unresolved apply results and credential recovery before any
remote completion or local purge. An unknown write never becomes safe merely
because a cluster is absent. Existing confirmed SENDING/UNCERTAIN operations are
resolved from the same Guard intent/receipt by the existing server continuation.
No new registration, UUID reservation edit or SQL repair is required.

New absence reviews explain the missing cluster in EN/RU. Residual objects produce
RETIREMENT_SOURCE_OBJECTS_REMAIN with a human explanation. Status is polled
automatically; no second write is sent by the browser's polling loop.

## Operator update, without reinstall or backups

This is an instruction for later reviewed deployment, not a performed action.
Both Sync and the external Guard package require the fix. No new DB migration,
permission or network access is added. Guard remains independently operated.

1. Record read-only metadata: exact current Sync release/image, service health,
   existing source/operation status in Admin UI, and whether any sync write has an
   uncertain result. Do not print environment files or token/private-key values.
   Do not repeat a plan/apply, reset the source or create another retirement nonce.
   If an unresolved write exists, reconcile its evidence first; this patch does
   not override it.
2. Prepare the reviewed exact commit in a clean canonical checkout, preserving the
   current root/config/credentials/DB volume. This patch is not a clean reinstall.
   Verify the checkout and published commit before using it:

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
   ```

   Stop on any mismatch/failure. No reset, force, broad cleanup or old config copy.
3. The NetBox operator builds `deploy/Dockerfile.netbox-guard` against the **actually
   installed and verified** NetBox base image; do not reuse a historical image tag
   from another runbook. Roll out that image through the existing NetBox deployment
   procedure for both NetBox and its worker. Preserve database, Redis, GuardIdentity,
   claims, intents, receipts and source closures. Do not change infrastructure data
   or permissions. The capability `absent_source_retirement: true` identifies the
   new code; the module loaded by all NetBox processes must be the matching package.
   Build command (the base image variable must come from verified host metadata):

   ```sh
   : "${NETBOX_BASE_IMAGE:?Set the verified installed NetBox base image}"
   sudo docker image inspect "$NETBOX_BASE_IMAGE" --format '{{.Id}}'
   sudo docker build --build-arg "NETBOX_BASE_IMAGE=$NETBOX_BASE_IMAGE" \
     -f "$CHECKOUT/deploy/Dockerfile.netbox-guard" \
     -t "netbox-with-sync-guard:$RELEASE" "$CHECKOUT"
   ```

   No Guard migration is needed. Exact NetBox Compose flags are operator-owned and
   must be verified locally, not invented by the Sync repository.
4. Upgrade Sync using the supported installer:

   ```sh
   sudo python3 "$CHECKOUT/deploy/install.py" \
     --root "$ROOT" --source "$CHECKOUT" --release-id "$RELEASE" \
     --image "netbox-sync:$RELEASE" \
     --public-url https://netbox-sync-test.indeed-id.hq --ingress-mode external
   sudo readlink -f "$ROOT/current"
   sudo python3 "$ROOT/current/deploy/compose.py" --root "$ROOT" ps
   curl --fail --silent --show-error https://netbox-sync-test.indeed-id.hq/api/v1/health
   ```

   Keep the existing Guard instance pin, namespace, credentials, volume, onboarding
   and permissions. Never disable TLS verification. Stop on failure, without
   manually changing current/config or restarting an obsolete writer.
5. Open the existing source as Admin. Its confirmed operation
   `b0496a60-ab40-4b31-8210-d902bc52ae68` continues automatically. Allow the lifecycle
   continuation to read the original intent, recheck full absence, commit the real
   receipt and finish normal local cleanup. The source remains disabled until it
   disappears on verified completion. Reloading the page is safe.
6. If residues are found, the UI must show the residue reason and preserve them;
   use Ownership details for permitted inventory/dependency information. Do not
   delete them blindly. If intent/actor/Guard identity differs, or a prior write is
   uncertain, stop and report that precise metadata. Missing RetirementReceipt
   alone is not a blocker; missing/mismatched original intent is not invented.
7. Only after completion, add the same host normally. It receives a new Source ID;
   old credentials/reservations/history must not block it. Do not recreate cluster
   14 or reuse its ID. Verify unrelated objects and external audit remain intact.

Guard-first installation is intentional: an older Sync may temporarily reject a
new absence receipt, but cannot falsely purge; the new Sync reconciles the exact
receipt after upgrade. Do not downgrade Sync while this reconciliation is pending.

## Local evidence

Providers
are synthetic fixtures; NetBox 4.7/PostgreSQL and production Compose workers are
real. Host systemd/VM deployment is not claimed. No live cluster was removed.

- Real NetBox fixture reproduced the original empty `_inventory` followed by
  `_cluster_fingerprint` OBJECT_MISSING. The new path passed: source identities
  without claims, detached claimed VM, historical-only reference, atomic receipt
  interruption/rollback, exact retry and unchanged old manifest/digest.
- Linux/PostgreSQL affected selection: 65 passed; one explicit runtime opt-in skip
  was subsequently executed in its own container. Runtime/transport selection:
  30 passed. API authorization/removal queue selection: 47 passed (overlapping
  selections are not presented as a unique full-suite total).
- 40 complete affected Playwright cases passed, including new EN/RU absence and
  residue messages, reload and automatic reconciliation; 88 UI unit tests passed.
  The first new browser fixture finished before reload read its source; corrected
  the fixture to await visible pending state, then reran the entire selection.
- TypeScript/Vite and Dockerfile.web image build passed. Tested image manifest:
  `sha256:f16e9ef46030a15f34097717d74212fa2fcd5339002c131775b702baeb7ab363`.
  Existing large-JavaScript-bundle advisory remains. Docker Engine 29.7.2.
- The first full gate stopped at an order-sensitive mount-list comparison during
  upgrade. The check now compares every mount field by destination, keeping the
  identical PostgreSQL container and volume assertions. The full repeat passed.

- Full production Compose gate passed (project
  `netbox-sync-retirement-cf1a73930b87`): real public API registration; fixture-only
  manual cluster deletion after immutable review; simulated unconfirmed execution
  response; lifecycle-worker stop/start; status-only reconciliation of the original
  nonce; complete purge; same-host re-add. Also passed cluster deletion before the
  first review followed by purge and another same-host registration.
- The same gate passed f6d297f component upgrade with unchanged DB container/volume,
  credentials/onboarding/policy/history; AM manual apply and unchanged plan;
  Proxmox VM/LXC manual/scheduled paths; and isolated Sync-only reinstall. These
  extra paths guard against compatibility regressions. They are not live actions.

- Final actual production bundle + real NetBox TLS + broker/PostgreSQL complete
  purge regression: 1 passed in 74.70s. Entire full harness exited 0; only its own
  uniquely labelled resources were cleaned. `git diff --check` passed.

The supplied live objects were not inspected or modified. Their remaining scope
can be established only by the upgraded Guard on the operator's installation.
An absent cluster alone does not guarantee that this specific operation will pass:
residual objects or unresolved writes must remain visible blockers.
