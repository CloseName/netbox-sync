# Large-source retirement: implementation and acceptance evidence

Status: implementation and isolated production runtime acceptance completed;
operator review and live acceptance remain separate. No user VM, live NetBox, backup or dump has been accessed.

## Reported case and what is established

Source `n2df674f7ae9c69958f1f8f2ea0b65e0f-esxi-e12c12fab1134a7fa5ae`, cluster 15,
host 7, 276 VMs, 1099 objects. Reported nonces:
`e03df625-0de9-45a0-8c84-c4ece0be3e5a` and
`f1630d63-5202-44f2-8f9b-f177bc106532`.

HTTP 409 at 30081/30058 ms without the closed server response code does **not**
prove a particular refusal. The actual live server code is still unknown.
RETIREMENT_DEADLINE is consistent with the 30-second budget, but database refusal
or another dependency check must not be relabelled without evidence.

Confirmed local defects:

- The original per-VM Collector traversal is expensive. In real NetBox 4.7.0 /
  PostgreSQL, 276 VMs and exactly 1099 claimed objects required 33830 SQL queries
  and 28.826 / 29.458 seconds for deletion. Review required 4964 queries and
  3.042 / 3.493 seconds. No artificial SQL latency was added to these measurements.
- The 15-second HTTP read timeout expired before Guard's 30-second budget. That
  loses the result while the server may still be inside an atomic transaction.
- SOURCE_NAMESPACE_BUSY was treated as terminal SOURCE_OPERATION_ACTIVE, allowing
  an incorrectly blocked UI state. A shared file-lock refusal named
  SOURCE_APPLY_ACTIVE does not prove a synchronization is running; retirement
  uses this same lock.
- RETIREMENT_DEADLINE and DEPENDENCY_DATABASE_REFUSAL were not recognised safe
  transport codes, hiding confirmed rollback behind a generic unknown response.

The existing partial unique index `retirement_inflight_source` already prohibits
multiple active retirement rows for one source. Two Guard nonces do not establish
that both are active in Sync. Recovery must inspect the persisted states.

## Narrow optimization and preserved boundaries

Whole-source deletion groups homogeneous VM roots, then hosts, then the cluster.
The legacy arbitrary-root API is unchanged. `_claims`, generation checks, parent
ownership, foreign-object rules and the table/namespace fences remain unchanged.
Every batch still compares its complete Collector snapshot with the immutable
review, checks exact per-model delete counts, and participates in one transaction
with the closure and genuine receipt. A failure rolls everything back.

Before applying this optimization, a real 1099-object regression compared the
batch snapshot/field updates with the union of individual roots; they matched.
It deleted all objects in a transaction and deliberately rolled that transaction
back. A foreign interface appeared in both snapshots and was refused by the
unchanged ownership check. The proposed broader rewrite of ownership queries was
rejected by automatic review and was **not applied**. The narrower Collector-only
change was accepted after this evidence.

Optimized measurements: 17996 queries, 17.548 and 13.466 seconds. The test also failed
receipt creation after the actual large deletion and verified rollback of all
1099 claims/objects, no namespace closure, and successful retry of the same nonce.
This is local performance evidence, not proof that the live deletion is resolved.

## Timing and diagnostics

Guard retains the 30-second budget, PostgreSQL's 2-second lock timeout and
10-second statement timeout. Budget checks now also run between SQL statements
inside the independent transaction, including Collector signals. They do not
block rollback or advisory unlock outside that transaction. One in-flight SQL
statement can consume its bounded statement timeout before rollback.

Source Guard HTTP reads allow 45 seconds (connect 3); ordinary object/receipt
requests retain 15 seconds. Worker child deadline is 70 seconds, Unix client 75,
lifecycle retirement client 170, browser retirement call 175. Existing product
nginx read timeout is 360. A lifecycle continuation may read the original receipt,
resume the identical intent, and verify local cleanup. The removal-request queue
and status-only UI polling remain separate bounded requests; browser disconnection
never supplies a new deletion nonce or new approval.

Structured Guard records correlate `retirement_operation` with Sync's operation
UUID. Records contain action, phase, duration_ms, query count, SQL time, object
count, a closed code and an allowlisted SQLSTATE. SQL, parameters, responses,
credentials and infrastructure contents are never recorded. Phases distinguish
inventory/ownership, Collector traversal, deletion and the entire request.

Busy Guard remains pending with RETIREMENT_SERVER_BUSY. Confirmed rollback uses
RETIREMENT_BUDGET_EXCEEDED or RETIREMENT_DATABASE_REFUSAL. Transport loss remains
UNCERTAIN. EN/RU distinguishes waiting, execution, unknown outcome and confirmed
NetBox completion followed by local cleanup.

## Existing operations and recovery contract

No new removal is prepared while another confirmed operation remains unresolved,
including queued removal. Continuation prioritizes the unique active operation;
only then may it reconcile an old BLOCKED/SOURCE_OPERATION_ACTIVE record. That
narrow repair requires saved credential-cleanup consent, an unchanged source
revision/generation and the original format-2 intent. It reads the original
receipt first and compares the exact pinned Guard, nonce, digest and manifest.
It does not manufacture receipts, edit infrastructure or grant new approval.

A real closed, complete receipt permits normal filesystem/credential checks and
the existing constrained source purge. Other historical nonces cannot write after
that namespace closes. A changed manifest, ownership conflict, uncertain sync run,
unconfirmed credentials or different Guard installation remains a blocker.

## Executed acceptance

- Real NetBox 4.7.0 / PostgreSQL: exactly 276 VMs / 1099 objects. Batch/individual
  snapshot and field-update equivalence; foreign-child refusal; full rollback
  after deletion and before receipt; expiry inside Collector SQL; namespace
  unlock; original-nonce completion. Final measured execute: 13.466 seconds,
  17996 queries, versus 28.826–29.458 seconds and 33830 before batching.
- Full production Compose project `netbox-sync-retirement-331c6edeece9-product`:
  **283 VMs / 1127 objects**, real Guard HTTPS and actual worker bundle. Client
  timed out while the real deletion transaction was active; bootstrap/retirement
  worker and lifecycle worker restarted; status-only reconciliation completed
  the original nonce, full purge and same-host re-registration. A repeated
  original confirmation returned the completed outcome. Captured execute nonces
  contained only the original UUID. Production timeout/capability settings were
  not replaced by test settings; the test-only middleware held an actual DELETE
  briefly to make interruption deterministic.
- The same gate passed clean setup, manual ESXi sync with IP observations,
  unchanged replan, scheduler, f6d297f component upgrade retaining the exact DB
  container/volume and credential/onboarding/policy/history state, Proxmox VM/LXC,
  removal while a read-only plan is active, missing-cluster recovery, and
  isolated Sync-only reinstall. Its final real worker/broker/NetBox/PostgreSQL
  purge test passed in 80.23 seconds. Harness exited 0 and removed only its own
  labelled resources. No user resources, backup or dump was involved.
- Backend/API/transport/creation/review suite: **136 passed**. An additional
  continuation run after expanding both age orders of the legacy nonce case:
  **10 passed**. Native partial uniqueness remains unchanged. Direct resumption
  of the second legacy nonce is refused while another is active.
- Bare Unix/child/HTTPS lost-response runtime: **1 passed** (17.71 seconds).
- Frontend unit suite: **88 passed**. Final EN/RU browser suite: **40 passed** (2.2 minutes). TypeScript,
  Vite and both production Docker builds passed; the known large-bundle warning
  is unchanged. No Compose topology, role or privilege changes were required.

The production backend image was
`sha256:1118d1b71ae4aaff2c4828cbb97907d1c50d13f2ff5075f5cad0829c53ed4084`.
The final image with the additional browser polling correction is
`sha256:21fbab405176724624f9f2ccfdc436c40eee510c0b8c100f71c89d2fb20e44fd`;
All 146 backend Python files in both images were compared byte-for-byte with
the final checkout and matched. The browser correction starts receipt polling
automatically after a lost confirmation response, retaining the same operation.

### Repeating the isolated large fixture

From the repository checkout, with the local Docker Linux Engine available:

```powershell
$env:PYTHONUTF8='1'
python tests/run_large_retirement_profile.py
```

The runner creates uniquely labelled NetBox/PostgreSQL/Redis containers with no
external network, mounts this checkout read-only, and removes only its own
containers. It accepts no live database address. The production-worker gate uses
`tests/run_retirement_production_worker.py` with `NETBOX_SYNC_FULL_LIFECYCLE=1`
and `NETBOX_SYNC_LARGE_RETIREMENT=1`, plus that runner's explicitly labelled local
PostgreSQL fixture and locally built review image. It must not target the stand.

## Operator procedure after review/publication

Do not reinstall, create a new source, retry synchronization, remove infrastructure
manually, edit journal rows or make backups/dumps on this disposable stand.

1. Preserve the existing root, `current`, configuration, credentials, installation
   namespace, pinned Guard identity and DB volume. Record their metadata and both
   existing operation states through the Admin UI. An unresolved sync write must
   be reconciled separately; this fix does not override it.
2. Use steps 2–4 of [the exact-root update procedure](missing-cluster-retirement.md#operator-update-without-reinstall-or-backups), with the newly reviewed published
   full SHA. Both the independently managed NetBox Guard image/package and Sync
   must contain this fix. Do not infer the NetBox base image, Compose location or
   container names from historical examples. There is no new DB migration,
   permission grant, TLS change or network/capability expansion in this patch.
3. After healthy upgrade, open the existing source. Allow server continuation to
   reconcile its original nonce(s). Do not start a third removal. Follow the
   pending operation shown by Sync; do not choose one solely by UUID order.
4. Collect only correlated diagnostics from the verified NetBox container and
   the Sync lifecycle/bootstrap bundle. For example, after setting `NETBOX_CONTAINER`
   from actual host metadata:

   ```sh
   : "${NETBOX_CONTAINER:?Set the verified running NetBox container name}"
   docker logs --since 20m "$NETBOX_CONTAINER" 2>&1 | grep -E 'retirement_operation=(e03df625-0de9-45a0-8c84-c4ece0be3e5a|f1630d63-5202-44f2-8f9b-f177bc106532) '
   docker logs --since 20m netbox-sync-bootstrap-worker 2>&1 | grep -E 'retirement_operation=(e03df625-0de9-45a0-8c84-c4ece0be3e5a|f1630d63-5202-44f2-8f9b-f177bc106532) '
   docker logs --since 20m netbox-sync-lifecycle-worker 2>&1 | grep -E 'retirement_operation=(e03df625-0de9-45a0-8c84-c4ece0be3e5a|f1630d63-5202-44f2-8f9b-f177bc106532) '
   ```

   These commands read logs only. No output means evidence is unavailable, not that
   deletion succeeded. A confirmed refusal must be investigated using its code and
   last phase; do not bypass it or substitute an empty inventory.
5. Completion requires a genuine closed-generation receipt, full source purge,
   absence of the owned resources, preservation of shared/foreign data, and
   successful fresh registration of the same verified host. If any condition is
   unconfirmed, stop that operation and retain its original journal for analysis.


Intermediate test notes (not acceptance substitutions):
- The first baseline runner could not print NetBox UTF-8 startup output under the
  Windows default encoding. It cleaned only its own fixture; the baseline was
  repeated with UTF-8 and produced the measurements above.
- A first full product attempt stopped on baseline f6d297f manual apply with
  OUTCOME_UNCERTAIN, before large deletion. The test-only WSGI threading change
  was removed (it was unnecessary for client-disconnect testing), and safe apply
  failure frames were added to the harness. No uncertain write was replayed;
  the next rehearsal used new disposable databases/resources. The exact cause
  of that first fixture failure was not established.
- Tests initially asserting the old timeout/message strings were updated. The
  queued UI test waits across its actual five-second polling interval. The final browser repeat also checks automatic status reads before a page
  reload; a transient error message may already be replaced by the confirmed
  server execution state. Final repeat: all 40 tests passed.
