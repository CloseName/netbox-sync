# Plan revalidation: deterministic reads and diagnosable refusal

Base: 5a1a1075f40a943a230d8b79ba21c3898824b0ce.
Operator incident: 6ab818a3-4345-4539-8b16-233a1628bf81.
No live system was accessed. The exact incident remains unproven: no original
inventory, repeated plan or server failure reason is available.

## Locally reproduced causes

1. Reversing independent UPDATE mutations changed netbox_fingerprint, even
   though the canonical actions and every value were identical. Regression
   failed before the fix.
2. Reversing two Proxmox hosts changed allocation of virtual IDs, links and
   plan digest. A real pynetbox/strict HTTP fixture reproduced differing digests
   without any writes. Reversing interfaces alone already passed; it was not
   itself established as a defect in that fixture.

Plan and apply now use the same ordered copy of inventory: host/workload stable
identities; named interfaces, disks and storage; address and bridge membership.
No field values are discarded. A changed memory value still changes the digest.
Read-through planning endpoints order records by ID. The NetBox mutation
fingerprint orders independent objects while retaining the mutation sequence
within each object. Planner version is bumped; older saved plans require rebuild.

## Tokens, fingerprints and mutable evidence

Discovery uses the NetBox read credential. Preparation and application use the
apply credential and repeat the provider and NetBox reads. The token contents
are not in the digest, logs or public diagnostics. Equal relevant visibility
with different test tokens produces equal plans. Different relevant visibility
can produce different actions or a NetBox request failure and must not be ignored.
Operators must give both credentials equivalent view scope for the managed
objects, relations and required catalogs; only the apply token needs write scope.
Do not solve a mismatch by giving the API credentials or disabling revalidation.

The source and target fingerprints still bind configuration and placement.
Provider review evidence and exact managed before/after values bind the plan;
no new exclusion of changing managed fields was introduced. Generic telemetry
not used by the executor is not promoted to an apply precondition. No real
NetBox change is ignored to make confirmation succeed.

## Refusal reasons and correlation

The PLAN_STALE umbrella retains its 409 behavior. Closed reasons distinguish
missing operation, different generation, expired retention, non-READY status,
missing saved result, submitted digest mismatch, planner version, recomputed
plan mismatch, plan prohibition and source identity. Actual blocked preparation
continues to return PLAN_BLOCKED with PLAN_FORBIDDEN.

Only closed difference categories are exposed: SOURCE_CONFIGURATION,
TARGET_CONFIGURATION, PROVIDER_INVENTORY, NETBOX_OBSERVATION, PLANNED_ACTIONS,
PLAN_CONTRACT. No field values, raw responses, tokens or full plans are logged.
The child transports safe reasons; the worker emits a generated event_id in a
warning record. API retains that event_id, logs it with its own request_id, and
returns it for Technical details. An API-generated failure still has a correlated
server request/event ID. An old event without those diagnostics cannot be
reconstructed retrospectively. Preserve the deployment log retention policy.

Preparation does not create a synchronization Run. A refused preparation may
therefore leave Runs empty; this is not evidence of an attempted infrastructure
write. Apply creates its Run and retains the existing uncertain-outcome handling.
Shared apply lock, source gate, exact generation/digest checks and credential
boundaries remain in force.

## UI

Confirmation sits in the Review plan heading. A reviewed plan carries its own
operation_id, captured with its digest for both prepare and apply. A new plan
clears the previous STALE result. Partial/uncertain write warnings are retained.
Refusal before writes, pending work, successful, partial and unknown outcomes
remain distinct. Stale Technical details show reason, difference category and
event ID. Rendering virtual IDs as object names/relations is presentation only;
the original canonical plan and submitted digest are unchanged.

## Verification record

Executed on the final prepared code:
- Full Linux backend with isolated PostgreSQL: **1017 passed, 26 skipped**, 78.16 s;
  two existing dependency deprecation warnings. Operation/migration PostgreSQL
  tests ran. The general-run skip groups remain those listed in
  [source-sync acceptance](source-sync-acceptance.md#exact-general-run-skip-disposition):
  separate opt-ins and prohibited live ESXi. The affected production gates are
  executed separately below; unrelated naming, TLS and dedicated backup opt-ins
  were not repeated as substitutes for these gates.
- Frontend unit: **67 passed**; TypeScript/Vite passed (525.78 kB main bundle,
  existing >500 kB advisory).
- Complete affected sync Playwright file: **28 passed**, 23.5 s. Includes exact
  digest/operation binding, stale rebuild recovery, pending/success/partial/unknown,
  source navigation, modal focus and layouts 768–1440 px.
- Production Compose bundled/external PostgreSQL: **2 passed**, 272.17 s.
  Each uses real discovery/apply workers and both providers. Proxmox has two
  hosts with alternating API order, QEMU and LXC. NetBox collection reads are
  reversed. Creation, prepare/apply, object counts and replan without changes pass.
  The browser loads the built image and executes a subsequent placement-update
  plan/prepare/apply/result/replan for each provider in both variants.
- A real fixture memory change between plan and prepare returns PLAN_STALE,
  PLAN_DIGEST and PLANNED_ACTIONS; object counts remain unchanged; the returned
  event UUID appears in the API log. The old operation becomes STALE; a new
  generation is produced and succeeds; submitting the old generation fails
  with OPERATION_VERSION without invalidating the new plan.
- Bundled populated installer upgrade retains source rows, mappings/ports,
  configuration/credential hashes, READY/policy and the same DB container/mounts.
- Docker Engine 29.7.2 Linux / Compose 5.5.0. Final image
  `sha256:1dcf8b39650fcfb269cdd8980f58928edaa41079f9da166a0c4a203dbe9ec668`.
- `git diff --check` passed. Only test-owned resources were cleaned.

Intermediate failures were resolved and the complete affected suites repeated:
extra optional fields initially changed an unrelated error envelope; a test
selected the first reversed catalog row instead of an explicit ID; the new UI
regression used region instead of alert; Windows decoded browser output as
CP1251; and the browser assertion counted GET /sync navigation as an apply POST.
None was bypassed by weakening a product check. Two early automatic approval
attempts were rejected by the review service with "Selected model is at capacity";
no command executed then. Later retries succeeded; no approval blocker remains.

Screenshots generated locally under frontend/test-results/:
plan-stale-diagnostic.png, plan-ready-rebuilt.png,
production-full-proxmox-success.png and production-full-esxi-success.png.
They contain synthetic inventory and no displayed credentials.

After a separately approved update, build and review a fresh plan. If refusal
recurs, collect its event_id, reason, difference_categories, operation_id and
READY/STALE timestamps from the API/worker logs. Do not export tokens, raw
responses or entire inventory. The original live incident remains unverified.
 The production browser harness
loads the actual built SPA and forwards browser requests transparently to the
production API Unix socket. It does not fulfill API requests with test data;
real discovery/apply processes and grants perform the work. This is an
application/worker browser gate, not a browser TLS-termination rehearsal. The
operator harness alone has Docker access; product Compose does not change.
The session is synthetic, passed through stdin and a mode-0600 transient file in
the test-owned volume, then deleted. Resource cleanup remains scoped by unique
project labels. No deployment or publication is part of this work.
