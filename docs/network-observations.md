# Explicit network observations — implementation checkpoint

This checkpoint implements the explicitly approved **observation-only fallback**.
It does not implement automatic VRF inference or duplicate IPAddress allocation.
Those additional scenarios remain pending; this is not acceptance of the entire
network-scope or retirement task.

## Operator path

1. In NetBox connection settings, inspect the prerequisite plan. Bootstrap contract
   v2 adds only `sync_network_observations` (JSON, `virtualization.vminterface`),
   labelled Network observations requiring review. Review and create the missing
   field using the existing temporary preparation token workflow. Existing 16
   definitions, credentials, completed onboarding and field values are retained.
   A missing/incompatible field blocks the observation plan before writes.
2. Run read-only Discovery for the source. In Configuration → Source placement,
   select **Save ambiguous IPs as NetBox observations** and review/confirm the save.
   This uses existing `source.configure` authorization, current Discovery evidence,
   revision fencing and the shared apply lock. An uncertain historical write still
   prevents this configuration change. Existing sources remain strict by default.
3. Build a fresh plan. The warning and expandable interface/address list identify
   incomplete IPAM assignments. VM identity conflicts still block the entire plan.
   Confirmation does not silently remove conflicting VMs or select one mask.
4. Only after normal plan review/confirmation does apply save the observations on
   NetBox interfaces. The result states that disputed IPAM assignments remain
   incomplete. Existing assignments, including foreign assignments, are retained.

The custom field is a JSON object keyed by source instance. Each entry has version 1,
status (`REVIEW_REQUIRED` or `NO_DISPUTED_ADDRESSES`), all disputed CIDRs, bridge/VLAN
context and `ipam_complete`. Another source's entries and unrelated custom fields
are preserved. Bridge/VLAN labels do **not** establish an IP namespace. An empty
current observation list does not delete any historical IPAddress assignment.
Discovery itself is unchanged and continues to retain all provider facts.

The full reviewed plan persists the exact VM/interface participants and binds this
policy/evidence to its digest. Manual prepare/apply and scheduled execution use the
same projection; planner version is `web-5a-5`. Old confirmations must be rebuilt.
There is no automatic apply, role widening, token exposure or network change.

## Proven locally

- HTTP-backed real pynetbox plan/apply/replan for ESXi and Proxmox VM/LXC: complete
  disputed masks saved on NetBox interfaces, foreign IP assignment and manual text
  retained, zero CREATE/UPDATE on the repeat plan. Missing field blocks before writes.
- Exact duplicate facts are deduplicated. Distinct VM identities stay separate;
  conflicting VM identity remains blocked. Invalid policy fails closed.
- Real PostgreSQL: policy persists, stale revision refuses change, old-client omission
  preserves the selected policy, invalid values refuse the transaction.
- Bootstrap upgrade regression: completed v1 setup creates exactly one new field,
  retains old definitions, connection credentials and completed state.
- Production Compose with real workers and controlled HTTPS/SOAP: both providers
  first block in strict mode, then persist interface observations after explicit API
  opt-in and apply; repeat plans do not duplicate objects. This gate also exercises
  scheduler, browser and populated upgrade. No live infrastructure was contacted.

## Remaining expanded requirements

Explicit, validated VRF mappings and separate IPAddress records where current NetBox
uniqueness rules permit them are **not yet implemented**. No artificial VRF or shared
address role is created and no uniqueness setting is modified. Repeated addresses
currently use observations even if a particular NetBox would permit duplicate rows.
Additional runtime tests are needed for those future branches. Observations are not
proof that a real network conflict has been resolved.

NetBox v4.7.0 checks duplicates by host address within a VRF, independently of mask;
its global/VRF uniqueness configuration determines rejection. The live configuration
was not inspected. Source: [official IPAddress implementation](https://github.com/netbox-community/netbox/blob/v4.7.0/netbox/ipam/models/ip.py#L981).

Controlled NetBox retirement remains a separate incomplete capability described in
[retirement-guard-proposal.md](retirement-guard-proposal.md). No live cleanup or
reconciliation of historical unknown operations is authorized by this checkpoint.
