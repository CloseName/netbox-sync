# Explicit network observations — implementation checkpoint

This implementation retains the explicitly approved **observation-only fallback**
and adds operator-selected existing VRFs for genuinely isolated networks. It never
infers isolation from labels or creates VRFs, prefixes or VLANs. Retirement remains
a separate incomplete task.

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
same projection; planner version is `web-5a-6`. Old confirmations must be rebuilt.
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

## Explicit VRF mapping

Admin can open Configuration → Source placement → IP network scopes after a fresh
Discovery. Add the exact provider host, network/bridge name and VLAN (empty means
no VLAN, not a wildcard), select an existing VRF, then review and confirm the whole
placement change. The catalog read token needs `ipam.view_vrf` for this optional
feature. No VRF write privilege is required or used. Operator/Viewer cannot change
these mappings; existing `source.configure` enforcement is unchanged.

The persisted `onboarding_mapping.network_scope_rules` is a bounded list (128) of
`host_id`, `bridge`, `vlan_id`, and a projected VRF with ID, name, RD,
`enforce_unique` and fingerprint. Selectors are exact, source-local and unique.
VRF names/IDs are never derived from the network name. Any interface without a rule
uses the global routing table. Physical host management IPs remain global; this
mapping currently applies only to guest VM/LXC interfaces.

Server catalog validation and each new plan/prepare/apply reread the selected VRF.
Deleted/changed VRF evidence blocks the plan (`NETWORK_SCOPE_REVIEW_REQUIRED`).
Mapping revision/generation/shared-lock checks and old-plan invalidation remain.
An older client omitting the rules cannot erase them. Explicit `[]` removes the
rules, not existing NetBox addresses. Credentials, Source ID, schedule and manual
NetBox data are untouched by mapping edits. Settings use existing backup/restore
storage; no new DB schema or external secret material is introduced.

IP lookup/creation keys include canonical CIDR plus selected VRF. Real routing
isolation permits the same IP on separate interfaces in separate selected VRFs.
Identical facts on one interface deduplicate; different masks or owners in one
scope do not. Existing foreign/unassigned IPs are never stolen. In observation
mode their conflict is preserved with NetBox IP ID and scope, while unrelated
inventory can sync. Strict mode still blocks ambiguous assignments.

Changing the scope of a previously owned interface never silently moves its IPs
or allocates a second binding. The old assignment is retained and conflicts are
recorded; an operator must review the real network/NetBox assignment separately.
No automatic cleanup is authorized by selecting a different VRF. Manual primary IPs
retain the existing protection. A coincident MAC still follows the existing MAC
ownership guard: VRF is an IP routing domain, not proof of unique MAC ownership.
Shared-address roles, arbitrary duplicate IPAM allocation, host-management VRF and
automatic migration of existing bindings are not implemented by this feature.

The controlled NetBox 4.7 image test `tests/netbox_model_scope_scenario.py` runs
against a dedicated database inside the isolated local test PostgreSQL network
namespace, with no external DB/server and no published ports. It runs real Django
migrations and model validation: same IP in two VRFs is valid; same address within
an enforced VRF is rejected with either equal or different masks. Test writes roll
back. It is an ORM/model test, distinct from the real SDK HTTP fixture and actual
Sync production-worker tests; it is not a live NetBox acceptance.

NetBox v4.7.0 checks duplicates by host address within a VRF, independently of mask;
its global/VRF uniqueness configuration determines rejection. The live configuration
was not inspected. Source: [official IPAddress implementation](https://github.com/netbox-community/netbox/blob/v4.7.0/netbox/ipam/models/ip.py#L981).

Controlled NetBox retirement remains a separate incomplete capability described in
[retirement-guard-proposal.md](retirement-guard-proposal.md). No live cleanup or
reconciliation of historical unknown operations is authorized by this checkpoint.

VRF contract: [official NetBox VRF documentation](https://netbox.readthedocs.io/en/stable/models/ipam/vrf/).
