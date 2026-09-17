# ESXi PLAN provider investigation

Base: 0885e3e72dc9bbab3ddbfa8f7e5299f33a5b245b. No live access or apply.

## Evidence, not inferred live causality

The operator's sequential results are:
- ESXI-AM-QA2 / esxi-169610c2cd1c4abfac2c: event
  0a491ebc-0992-43fa-8a8d-54a8d6abb865, 120102 ms, provider started only.
- ESXI-PAM-QA / esxi-302fb3e24e1e40a8880e: event
  6f274062-f67a-4485-87a2-55ff061482eb, 120131 ms; provider 118049 ms,
  then NetBox started before the shared budget expired.
Both children were killed/reaped, returncode -9. Cleanup fix is confirmed by the
operator; provider latency is not yet attributed to network, host load or a
specific API operation. Historical ESXI-CM-QA uncertain writes remain unresolved.

Confirmed local inefficiency: pyVmomi managed-object attribute access invokes
InvokeAccessor -> InvokeMethod/Fetch; it is not an automatically cached field.
The mapper repeatedly read VM config for identity, annotation, disks, CPU and
memory, host config for each VM's portgroup/autostart and management interfaces,
and datastore properties. Adding annotation incurred another full config read.

## Narrow implementation

Each discovery owns an InventoryReads context on its private SDK session. It
caches successful accessor values by managed type/id/property, restores the stub
on exit and discards all values. Exceptions are never cached as empty results.
Host inventory is traversed once. VM name/config/guest/runtime/summary are read
using RetrievePropertiesEx in batches of at most 100 objects. All continuation
pages are consumed; missing objects/properties, missingSet faults, duplicates and
repeated continuation tokens fail the discovery. No partial fallback is returned.
Host/datastore extras are read before conversion and reused during conversion.
A malformed VM/NIC or absent VM config now fails the whole inventory rather than
silently omitting a VM. No objects are deleted or modified by this failure.
Descriptions retain the full config.annotation -> VM comments contract; no trim.
This is not an atomic ESXi transaction; concurrent infrastructure changes still
require the existing plan/prepare freshness checks. No cross-operation cache.

## Safe measurements

Within the outer provider stage:
- esxi_connect: SDK version negotiation, connection and authentication together;
- esxi_inventory: service content and host/VM reference enumeration;
- esxi_properties: batched VM properties and continuation pages;
- esxi_additional: remaining host/datastore properties;
- esxi_conversion: SDK data to discovery objects;
- esxi_disconnect: session cleanup (also measured if a preceding read failed).

Each emits started and finished/failed with bounded duration_ms. Inventory and
conversion report object counts; properties report VM count; additional reports
host count. requests counts SDK InvokeMethod calls within that stage, including
Fetch; it does not claim to count version-negotiation HTTP requests, packets or
SDK-internal transport activity. Successful conversion in the representative
fixture performs zero additional requests. No per-VM logging is added.

The existing metadata pipe carries only closed stage/state/integer fields, at
most 32 retained entries. No hostnames, VM names, comments, identifiers from
inventory, URLs, credentials, response bodies or stderr are included. Outer
DISCOVERY_TIMEOUT retains the latest started stage even when the child is killed.
Child errors also retain phase measurements in the correlated operation event.
Successful supervisor CHILD_PHASES records are enabled explicitly for this module
only, with source_instance/operation for sequential correlation; other SDK log
levels are not enabled. Their source identifier is control metadata, not inventory.

## Time policy

The shared discovery/PLAN deadline remains 120 s, including provider, NetBox and
planning. Cleanup remains bounded to the existing 2 s wait; apply, shared locks,
capabilities, scheduling, TLS and destination policy are unchanged.
ESXI_IO_TIMEOUT remains 15 s for SOAP connection/socket I/O. There is no new
application retry. connectionPoolTimeout is idle pool lifetime, not a total
request deadline. Inspection of the installed pyVmomi shows SmartConnect's
version-negotiation GET does not receive httpConnectionTimeout. Slow trickling
responses can also evade a per-socket inactivity timeout. These remain bounded by
the isolated worker's overall deadline; the esxi_connect/properties markers make
them distinguishable on the next test. No global socket default or TLS monkeypatch
was introduced into the product to conceal that SDK limitation.
No measured evidence supports increasing the total budget yet. Even batching
cannot guarantee completion against an overloaded or unreachable ESXi.

## Sequential operator acceptance (not executed)

After separate publication/update approval, verify the reviewed commit and
unchanged worker isolation. Do not change schedules or retry any old operation.
1. Record UTC start time. Open ESXI-AM-QA2 and request a **new PLAN only**. Wait
   for its terminal state. Do not press prepare/confirm/sync/apply.
2. Record the new operation/event ID and status. On failure collect the matching
   safe JSON event from discovery-worker logs: code, event_id, source_instance,
   operation_kind, duration_ms, phases, exception_class, cleanup_error,
   child_reaped, returncode and safe HTTP metadata. On success collect CHILD_PHASES
   for this source and the same time window. Do not export env, tokens or payloads.
3. Only when the first PLAN ends, repeat for ESXI-PAM-QA. If the first child is not
   reaped, stop instead of launching the next test.
4. Compare connect/inventory/properties/additional/conversion/disconnect durations
   and request counts. A remaining timeout with properties started is different
   from connect started or completed provider followed by NetBox timeout. Report
   those facts; do not label them automatically as permissions or network faults.
5. Review counts and representative VM comments for completeness. No apply, no
   ESXI-CM-QA replay, no claimed resolution of previous uncertain writes.

Operator log source: `docker logs --since <recorded-UTC-time> netbox-sync-discovery-worker`.
Use verified installed container name if different. Extract only the JSON fields
above and the two exact source IDs; never include unrestricted debug output.

Official API/SDK references:
- https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vmodl.query.PropertyCollector.html
- https://github.com/vmware/pyvmomi/blob/master/pyVmomi/StubAdapterAccessorImpl.py
- https://github.com/vmware/pyvmomi/blob/master/pyVim/connect.py

These sources establish SDK/API behavior, not the installed ESXi version or live
cause. On-host acceptance remains necessary for both named sources.

## Final local evidence

- tests/test_esxi_property_inventory.py uses real pyVmomi against a controlled
  HTTPS/SOAP server with trusted fixture CA and 147 VMs. Uncached mapper baseline:
  **1494 SOAP requests; snapshot/batch path: 10**, of which two property batches.
  Full dataclass results are equal, including 480-character multiline comments,
  VM/NIC/IP data. A second collection performs fresh reads and returns the same
  result. Counts include service-content calls, not just property requests.
  An intermediate measurement was 1641 because the newly added completeness check
  itself reread config; that additional read was removed before final validation.
- The same suite verifies all continuation pages, failure on missing objects or
  property faults, a slow HTTPS request with a .2 s **test-only** socket deadline
  and no repeat, and zero requests in the conversion stage.
- Actual DiscoverySupervisor and unmodified production --child entrypoint run
  under UID10001 in a read-only networkless Linux container with only production
  CHOWN/SETUID/SETGID/KILL and no-new-privileges. One fixture completes PLAN and
  produces CREATE items; NetBox write count remains zero. Another hangs in
  RetrievePropertiesEx: a shortened **test-only** parent deadline produces
  DISCOVERY_TIMEOUT, last stage esxi_properties started, child_reaped=true/-9.
- Combined ESXi/discovery/safe-diagnostic suite: **76 passed, 11.34 s**.
- Separate existing discovery cleanup and exit-race/lock tests: **2 passed with
  KILL (2.10 s), 2 without KILL (5.57 s)**. Apply cases were deselected.
- Previous in-memory SimpleNamespace inventories did not model remote attribute
  access; the earlier small SOAP fixture did not assert request counts. Therefore
  output-correctness tests missed amplification. New request-count and equality
  assertions cover that gap without relying on a wall-clock speed threshold.

No apply, live endpoint, schedule, privilege, network or TLS configuration change.
No claim of reproducing or fixing the exact live provider delay. System acceptance
for ESXI-AM-QA2 and ESXI-PAM-QA is still required; diagnostics are evidence to obtain
that cause, not by themselves proof of performance recovery.

Final transport/safe-diagnostic follow-up after defensive DTO handling: 32 passed,
1.10 s. git diff --check passed.
