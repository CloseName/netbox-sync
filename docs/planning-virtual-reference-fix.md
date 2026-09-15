# Planned references at the NetBox HTTP boundary

## Report and reproduction

Base: 08e536a8ed5cc52f0ffe77215fec276e19952167. Operator event
cd23ee08-f169-4900-a607-c8c92e6d56c8 reports PLANNER_FAILED during planning
following successful Proxmox discovery. No live systems were contacted.

The controlled HTTP regression reproduced this stack before the fix:
`build_runtime_plan -> apply_full_sync -> _run_stage -> apply_hosts ->
_load_existing_interfaces -> PlanningEndpoint.filter -> PlanningEndpoint.filter`.
A newly planned host had ID -1, and the real pynetbox client sent
`GET /api/dcim/interfaces/?device_id=-1&limit=0`.
The stricter fixture rejects that request with a deliberately selected 400.
The actual live NetBox response/status is unknown; this test does not establish it.
Before the product fix: real-pynetbox first-sync tests **1 failed (Proxmox),
1 passed (ESXi)**. This reproduces the reported reference leak and call chain,
not every possible reason for PLANNER_FAILED.

## Resolution

- get/filter resolve virtual IDs through every nested plan. Only the final
  real-API boundary excludes virtual ID queries; mixed ID lists still query
  persisted IDs. No NetBox exception is caught and converted into an empty result.
- Local created records and working copies overlay lower-layer results without
  dropping planned interfaces/parent links. Ambiguous get remains an error,
  including a persisted record conflicting with a planned record.
- Endpoint ID allocation is shared through nested layers, preventing a new inner
  object from shadowing an outer object. IDs remain in-memory, endpoint-scoped.
- Saved local changes remain considered when matching queries. Public API
  privileges, Compose networks, credentials, shared locks and apply fencing are unchanged.

## Why previous checks missed it

Both the in-memory fake and the original HTTP fixture returned an empty result
for negative device_id instead of rejecting the invalid reference. The production
worker harness used that same permissive HTTP fixture. Real SDKs and production
processes alone did not make its API input validation realistic. The fixture now
records actual request paths and rejects negative detail/reference IDs; a separate
test proves its rejection. Production scenarios also assert zero virtual requests.

## Verification

Linux affected backend suite: **120 passed**, 7.51 s, no skips. Includes:
- real pynetbox new Proxmox host/interfaces + QEMU/LXC networks, confirmed apply
  and replan without CREATE/UPDATE;
- mixed existing host/interfaces with new QEMU/LXC, plus ESXi first sync;
- nested parent/interface lookups, distinct virtual IDs, mixed persisted/virtual
  ID filters, isolated renamed working copies and positional/keyword get;
- explicit HTTP rejection regression, propagated real request errors and
  persisted/planned ambiguity refusal;
- full apply safety, conflict checks, discovery/apply workers, plan and shared lock.

Dockerfile.web built successfully. Runtime image:
`sha256:7b83d4bdef949c9f076de796a1c070f91fb7f379e2f70a1bbd3903c4b4c6040c`.
Docker Engine 29.7.2 Linux, Compose 5.5.0.

The first production run passed both providers' full worker sequences in both DB
variants, but the bundled variant failed its later upgrade assertion comparing
raw JSON Mounts array strings. Source rows, protected files and DB container ID
had already matched. The harness now compares all mount attributes, sorted by
Destination, so an actual volume/mount change still fails. Final full rerun: **2 passed**, 211.06 s. Both bundled/external PostgreSQL
execute ESXi and Proxmox discovery -> nonempty plan -> prepare/apply -> object
counts -> replan without CREATE/UPDATE, using real workers/SDKs and strict HTTPS
fixture on provider port 8443 and NetBox port 9443. Proxmox includes host
interfaces, QEMU and LXC networks. Both assert zero virtual HTTP requests.
Mapping validation/CAS/stale-plan checks also pass. Bundled populated installer
upgrade preserves complete source rows, configuration/credential hashes, READY,
policy, the same PostgreSQL container and every mount attribute. In this rerun
raw mount serialization also matched; the earlier difference was not retained,
so its precise cause cannot be established retrospectively.

`git diff --check` passed. The harness cleanup is restricted to its unique project
labels. No push, deployment or live connections. No changes to product Compose,
networkless broker, private PostgreSQL, worker boundaries or credentials. 
The controlled peers
are protocol fixtures, not live NetBox or hypervisors. Do not infer the HTTP status
or full health of the operator installation from these checks. After an approved
upgrade, generate a fresh plan; do not reuse a pre-fix confirmation.
