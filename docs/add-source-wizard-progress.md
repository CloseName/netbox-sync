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

## Mandatory remaining work

1. **Real Operator registration is not implemented.** Server roles still allow source.probe/source.register only for Admin. Browser Operator fixtures deliberately model the requested future permissions; they are UI evidence only, not server authorization acceptance. A minimal revision-only probe-policy operation is also needed; granting policy.read to Operator is not proposed.
2. **Final-action cluster creation is not implemented.** The wizard currently requires an existing compatible cluster and explicitly says creation is unavailable. No new privileged worker action or persistent role change was applied. Existing protected worker + catalog journal should be reused, with source/actor-bound intent, fresh dependency validation, explicit ownership handling, uncertain-outcome reconciliation, and no destructive rollback. This needs direct API and production runtime tests before acceptance.
3. **Deleted-source recovery is not implemented.** There is no working Restore button. See inventory-conflicts-and-source-recovery.md: source tombstones and identity reservation remain enforced. Safe revival needs independently proven provider identity, prior ownership/placement, admin authorization, atomic coordination with removal/workers, audit and new credentials. An address/name match is not enough.
4. A persistent “Not yet synchronized” source-state contract has not been added; existing diagnostics remain unchanged. Compact automatic placement, durable recovery presentation and final-cluster action summary require the remaining backend integration.
5. No live acceptance, production Compose or new direct-API permissions tests have been run for this UI checkpoint. Backend, capabilities, broker isolation, shared lock and scheduler were not changed.

## Approval-review boundary

Automatic approval review rejected a bundled backend edit that added Operator probe/register permissions and privileged final-registration cluster creation, citing persistent role changes and privileged catalog creation. The exact narrow changes were presented for confirmation; they have not been applied. The safe independent UI work continued. An earlier rejection of deleting a legacy unit-test file was resolved by preserving and adapting all four tests instead.

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

## Validation

- Frontend unit/transport: **70 passed**, including the four preserved form tests.
- TypeScript and Vite build passed; Vite warns that the main chunk is ~634 kB (gzip ~188 kB). Data-router navigation adds bundle weight; no size claim is made.
- Final dedicated wizard suite: **14 passed**. Both placement-review receipt expiry regressions failed before the fix (the secret input never returned), then passed. The late-response test waits for actual receipt cancellation after leaving/reopening.
- Source placement suite: **31 passed** after the fix, including EN/RU, light/dark, 390/1440 widths, expiry, changed catalog, uncertain registration, catalog partial outcomes and keyboard.
- Other affected suites: **69 passed** in the broader run (source-access 13, durable-lifecycle 23, UI-hardening 33). The broad run was 111 passed / 1 failed because the new late-response test used the wrong link label; the dedicated suite was corrected and rerun in full. An intermediate later run exposed a test synchronization issue around dialog closure; awaiting closure resolved it. These are separate runs, not a claim of a single green 114-test run.
- Corrected a real focus regression: the query selected the hidden exit-dialog heading; it now targets the active form heading/legend.
- `git diff --check` passed. Backend/runtime tests were not rerun because no backend or deployment code changed; they are still mandatory for the unimplemented server work.
- Review gallery saved outside Git under the Codex visualization workspace, `netbox-sync-wizard-20260921/index.html`. Screenshots contain fixture names and masked or empty input fields, not real credentials.

No assertion of complete product acceptance is made here.
