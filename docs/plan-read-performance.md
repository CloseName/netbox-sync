# Plan read reuse and timing evidence

The worker previously constructed a discovery review before PLAN and then built
that review again inside runtime planning. PLAN now skips the unused preliminary
review. Discovery retains its review unchanged.

Each dry-run facade memoizes fully consumed remote all/filter selections only
within that plan. Nested planning overlays remain live. Partial-page failures are
propagated and never cached. This is not a transactionally consistent NetBox
snapshot; fresh prepare/apply planning still reads remote evidence again.

Safe timing stages separate mapping, review and simulation without recording
infrastructure payloads. The 120-second limit and bounded child cleanup remain.

Local regression uses real HTTP with 276 ESXi VMs, interfaces and addresses:
each identical GET selection is issued once; the unchanged plan has no creates
or updates; a subsequent changed NetBox field changes the next plan. HTTP fixture
pagination now exposes next links rather than silently truncating large results.

On 22 September 2026 the combined affected Linux backend suite passed 166 tests.
Production Compose worker/browser and populated-upgrade gates passed with both
bundled and external PostgreSQL (171.98s and 161.07s respectively). These runtime
gates also exercised the concurrent host-reservation draft in the working tree;
that draft is a separate feature and is not completed by this change.

The live PLAN timeout root cause remains unproved. Reduced redundant reads and
local runtime checks do not establish live latency. A separate ESXI-INFRA read-only
Discovery attempt timed out, so a provider-side delay may also remain. No automatic
retry, schedule change or live apply was performed for that attempt.
