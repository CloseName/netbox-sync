# NetBox simulation diagnostics

The ESXi runtime emits bounded phase metadata for preflight, host metadata,
host networking, event export, primary IP, VMs, VM networking, placement and disks.
Each completed phase reports duration_ms, requests and objects. Requests count
materialized endpoint reads at the underlying NetBox boundary, not HTTP pages;
cache hits are excluded. Nested dry-runs repeat stage names in execution order.
Started without finished identifies the active stage when the child is killed.
No object names, IDs, query values, credentials or payloads are included.
The progress channel is best effort and nonblocking; it must not stall execution.
The last 64 accepted phase entries survive timeout diagnostic sanitization.

Known performance correction: exact ID lookups now reuse already wrapped records
within the same plan (including the lower layer of nested simulations), avoiding
N+1 detail queries after bulk inventory. Unknown IDs still read remotely. A new
plan uses fresh evidence. Filtering compares only requested fields instead of
copying unrelated JSON snapshots for every candidate. No cross-run cache, writes,
ownership bypass or timeout increase was introduced.

Regression fixture: 279 VM lookups after one inventory read used 280 HTTP GETs
before the fix and one afterward. This does not measure full production runtime.
Validate ESXI-AM-QA2 by building a fresh plan, inspecting CHILD_PHASES or timeout
phases, then reviewing and applying normally. Confirm a subsequent no-change plan.
If still slow, retain the phase metadata before making further changes.


Manual apply now invokes the confirmed executor once after digest revalidation.
Its internal complete dry-run remains mandatory; before_write marks write_boundary.
Exceptions before that callback are FAILED_BEFORE_WRITE; afterward they remain
OUTCOME_UNCERTAIN. A killed child still retains conservative uncertainty: absence
of a best-effort progress marker is not proof that no writes occurred.
ESXi preflight uses a fresh invocation-local read facade, shared with its dry-run,
so bulk-read records can satisfy later ID lookups. Real writes use the original
guarded API, never the planning cache. Real ESXi stages emit apply_* timings.
Production evidence motivating this change: plan 73s, then repeated runtime
preflights of 77.7s and 79.4s plus dry-runs exhausted the 300s apply budget.
Historical uncertain runs still require object/journal reconciliation.
