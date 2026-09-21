# Add-source wizard: review checkpoint (2026-09-21)

This is an **incomplete implementation checkpoint**, not release acceptance.
Baseline: e7df50b541439789d9baa359a293ad0a1390db08. No deployment or live-system access.

## Implemented independent UI

- Three visible steps, completed-step navigation and browser Back; source settings survive return and connection receipt expiry. Route query contains only the step number.
- Exit confirmation for a filled draft, native tab-close warning, secret show/hide. Secret values remain only in the mounted input; no password/token in browser storage or URLs. Successful checks clear the input; failed checks retain it for correction. A full reload loses secrets.
- Changed connection invalidates the receipt; pending controls are locked and a response after unmount cannot advance a new wizard.
- Existing site auto-selected only when the complete unfiltered result contains exactly one choice. Exact hardware suggestions remain manufacturer/model based. Existing cluster must match the chosen source name, site and type in the UI; existing backend placement validation remains authoritative.
- Review summary, final Add source action, no redundant confirmation checkbox. Scheduler remains off. No discovery/plan/apply is started by registration.
- Admin may assign an existing team through the existing protected endpoint. A team assignment failure after successful registration is shown separately and does not repeat registration. Source-list success notification is dismissible and expires after 10 seconds; errors do not auto-dismiss.
- Existing catalog creation remains Admin-only. Operator view has no catalog/team management controls. EN/RU, existing light/dark theme, narrow screen and keyboard checks.
- Data router is used for the navigation blocker; routes and server SPA contract are unchanged.

## Server integration and remaining work

1. **Operator registration implemented after explicit user authorization.** Only source.probe/source.register were added. Probe policy exposes its revision, not the administrative policy. Direct API tests use the real authorization middleware and AuthPolicy state machine for Admin/Operator/Viewer; provider/NetBox external I/O is replaced only in those unit tests.
2. **Final-action cluster creation implemented.** The existing bootstrap worker reads the protected apply token itself; API/browser never receives it. The closed action accepts name, site ID and cluster-type ID only. A valid actor receipt, matching checked destination/TLS/port, unused source identity and fresh catalog fingerprints are checked before dispatch. Cluster name must equal source name. Shared apply/configuration locks and the durable catalog journal prevent blind replay; a different intent cannot claim an earlier creation. After a created cluster but unconfirmed registration, REGISTRATION_CLUSTER_RETAINED preserves the cluster and stops automatic retry. A narrow registration-status endpoint derives the journal UUID from the authenticated principal, source and registration nonce; it can only reconcile/read, never POST a new object. Operator cannot read arbitrary catalog journals or use the Admin catalog API.
3. **Deleted-source recovery is not implemented.** There is no working Restore button. See inventory-conflicts-and-source-recovery.md: source tombstones and identity reservation remain enforced. Safe revival needs independently proven provider identity, prior ownership/placement, admin authorization, atomic coordination with removal/workers, audit and new credentials. An address/name match is not enough.
4. A persistent “Not yet synchronized” source-state contract has not been added; existing diagnostics remain unchanged. Durable recovery presentation and compact automatic placement still require the remaining integration. The final-cluster action is now included in the review summary.
5. No live acceptance has been performed. Local Linux and production Compose results are recorded below; deployment capabilities, networks, broker isolation and scheduler configuration are unchanged.

## Approval-review boundary

The earlier automatic-review refusal applied to the proposed persistent Operator permissions and privileged final-registration creation. The user subsequently explicitly authorized this narrow boundary. That approval is now implemented; the previous refusal is not an outstanding blocker. No broader role, token access, removal/team administration or recovery permission was granted to Operator.

## Local demonstration (fixtures only)

From frontend/:

```text
npm test
npm run build
npx playwright test add-source-wizard.spec.ts source-placement.spec.ts source-access.spec.ts ui-hardening.spec.ts durable-lifecycle.spec.ts --reporter=line
```

The tests intercept API calls; they do not connect to providers or NetBox. Use `--headed` to watch the fixture flows. Screenshots are written under frontend/test-results/ and may be replaced by subsequent runs. The dedicated wizard suite includes all three steps, Admin/Operator layouts, RU dark narrow views, connection refusal, and unconfirmed team assignment. Never use real credentials with these fixtures.

## Later stand acceptance, after remaining gates

1. Review and finish Operator server permissions and final-cluster journaling; prove forbidden direct API requests still fail.
2. Use a disposable authorized source/account and prepared NetBox placement. Verify Admin then Operator, one/multiple sites and compatible/incompatible clusters. Verify no cluster POST before final addition.
3. Exercise expired receipt, concurrent placement change, lost response and repeat confirmation; reconcile before retry. Verify one source/cluster, stable identity, protected credentials and schedule off.
4. Verify the new source notification, EN/RU, keyboard, narrow layout and refresh. Do not start PLAN/apply as part of this wizard acceptance.
5. Test recovery only after implementing its independent identity/ownership gates. Never substitute deleting/re-adding a live source as a workaround.

## Earlier UI-only checkpoint validation

- Frontend unit/transport: **70 passed**, including the four preserved form tests.
- TypeScript and Vite build passed; Vite warns that the main chunk is ~634 kB (gzip ~188 kB). Data-router navigation adds bundle weight; no size claim is made.
- Final dedicated wizard suite: **14 passed**. Both placement-review receipt expiry regressions failed before the fix (the secret input never returned), then passed. The late-response test waits for actual receipt cancellation after leaving/reopening.
- Source placement suite: **31 passed** after the fix, including EN/RU, light/dark, 390/1440 widths, expiry, changed catalog, uncertain registration, catalog partial outcomes and keyboard.
- Other affected suites: **69 passed** in the broader run (source-access 13, durable-lifecycle 23, UI-hardening 33). The broad run was 111 passed / 1 failed because the new late-response test used the wrong link label; the dedicated suite was corrected and rerun in full. An intermediate later run exposed a test synchronization issue around dialog closure; awaiting closure resolved it. These are separate runs, not a claim of a single green 114-test run.
- Corrected a real focus regression: the query selected the hidden exit-dialog heading; it now targets the active form heading/legend.
- `git diff --check` passed. Backend/runtime tests were not rerun because no backend or deployment code changed; they are still mandatory for the unimplemented server work.
- Review gallery saved outside Git under the Codex visualization workspace, `netbox-sync-wizard-20260921/index.html`. Screenshots contain fixture names and masked or empty input fields, not real credentials.

No assertion of complete product acceptance is made here.


## Server integration continuation (2026-09-21)

- Linux backend suite: **181 passed, zero skips** (operator_registration, netbox_catalog, onboarding/security, auth_api/policy, directory_auth, catalog_creation). The previous seven Windows skips in this subset are closed by Linux execution, including root-owned durable journal checks. Directory protocol/live AD is not exercised by these state-machine tests.
- Frontend unit tests: **70 passed**. TypeScript/Vite passed (existing ~637 kB bundle warning).
- Runtime gate uses an independently named `netbox-sync-wizard:gate-20260921` image built from Dockerfile.web. The auth Compose harness supports NETBOX_SYNC_REVIEW_IMAGE to avoid replacing unrelated image tags. Only uniquely labelled disposable projects are created; cleanup uses their exact project labels. The operator helper uses the Docker socket only for the test, never in product containers.
- The controlled HTTPS peer now enforces the cluster write token and fixed fields, stores created clusters and filters reads accurately. The production API -> bootstrap worker -> unprivileged child -> HTTPS path creates the cluster only on final registration, then registers the source with sync disabled. Repeated final submission is refused. The journal status is read through the actor-bound endpoint.
- Existing cluster creation permissions in the configured NetBox apply token are required. A NetBox denial remains a refusal, not a grant of new rights. Allowed placement is the current server-validated catalog visible to the configured NetBox token; this change does not invent per-user site ACLs or broaden NetBox token permissions.

### Recovery remains incomplete: concrete evidence boundary

Legacy Proxmox preview persists node names as host IDs, not an independently verified physical/cluster identity; legacy ESXi may contain a managed-object-reference fallback rather than a hardware UUID. These are not sufficient proof that a server at the same address is the old server. Tombstones remain immutable reservations; lifecycle grants currently do not authorize an audited revival transaction. No Restore button or name/address-based adoption was added. Completing this path requires persisted identity provenance, an ownership/placement proposal read through the isolated NetBox component, and an Admin-only lifecycle transaction coordinated with workers. Existing tombstones, credentials ownership, source history and NetBox objects were not modified by this change.

The additional AD admission/per-user-role task and login password-control change remain separate unfinished work. They are not replaced by this authorization change. This checkpoint does not claim that the whole wizard/recovery or AD task is complete.


### Reproduce this integration gate locally

From the repository, build `docker build -f Dockerfile.web -t netbox-sync-wizard:gate-20260921 .`.
Run `tests/test_auth_compose_docker.py` with `NETBOX_SYNC_AUTH_DOCKER_TEST=1` and
`NETBOX_SYNC_REVIEW_IMAGE=netbox-sync-wizard:gate-20260921`. This opt-in starts only
labelled disposable local projects and needs the existing operator test-helper images;
it is not a deployment command. The test-helper Docker socket is outside product Compose.
From frontend/, run `npm test`, `npm run build`, and
`npx playwright test add-source-wizard.spec.ts source-placement.spec.ts --reporter=line`.

Before any later live acceptance, review the recovery limitation above. For the supported
new-source path, test Operator/Admin final addition and confirm sync remains disabled;
Viewer registration, Operator direct catalog creation, policy/team changes and source
removal must fail server-side. Check the result before retrying a lost final response.
No PLAN/apply, deletion or restoration of live sources is part of this gate.

### Final gate results

Implementation commit: `cbd90c4`.
Final affected browser suite: **48 passed** (57.8 s); unit/transport **70 passed**;
Linux backend **181 passed**, zero skips; production Compose **2 passed** (187.96 s),
bundled and external PostgreSQL, final rebuilt image. Dockerfile.web build includes
TypeScript/Vite and passed. `git diff --check` passed.

The production Compose checks include the new registration-status endpoint,
actual HTTPS catalog creation, protected token use, replay refusal, private API/DB,
networkless broker and retained backup/restore state. They use an authenticated local
Admin. Operator permission evidence is the direct API/AuthPolicy tests (including
negative permissions and both provider registration requests), not a simulated UI role;
no live LDAP or hypervisor acceptance is claimed.

New snapshots are retained outside Git in the Codex visualization workspace under
`netbox-sync-wizard-server-20260921/`: pending-cluster Admin/Operator settings and review.
The Operator review image was inspected; no secret values are displayed.
Test resources are removed by the harness using exact unique Compose project labels.
The independently named build image is retained for reproducibility.
