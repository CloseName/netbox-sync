# Onboarding prerequisite contract

The versioned source of truth is `netbox_sync/prerequisites.py` (version 1).
Probe, reviewed plan, create executor and UI consume this contract. Existing technical
keys and provider mappings are unchanged. No geography, tenant, VLAN, Prefix, Platform
or other infrastructure dictionary is created by preparation.

| Key | Models | Value source and reason for custom storage |
| --- | --- | --- |
| sync_identities | Device, Interface, VM, VMInterface | Source-scoped stable provider IDs; NetBox IDs and display names do not encode provider ownership. |
| sync_original_names | Device, Interface, VM, VMInterface | Provider names retained separately from operator-facing names. |
| hypervisor_version | Device | Observed hypervisor version; device type and Platform do not store this inventory value. |
| cpu_model | Device | Observed physical CPU model; not VM vCPU allocation. |
| cpu_vendor | Device | Observed CPU vendor; not device manufacturer. |
| cpu_sockets | Device | Observed physical socket count. |
| cpu_cores | Device | Observed physical core count. |
| cpu_threads | Device | Observed physical thread count. |
| memory_mb | Device | Physical host RAM; VM memory continues to use the standard field. |
| physical_disks | Device | Observed disk path/model/serial/type/size/health inventory, without adopting managed storage objects. |
| guest_kind | VM | Provider LXC classification, distinct from display name. |
| guest_architecture | VM | Observed LXC architecture. |
| guest_os_type | VM | Raw LXC OS hint; does not create or assign an operator-managed Platform. |
| swap_mb | VM | LXC swap allocation, distinct from VM memory. |
| source_bridge | VMInterface | Observed provider bridge, without fabricating a NetBox bridge object. |
| source_vlan_id | VMInterface | Observed tag, without creating or adopting a VLAN. |

Standard VM CPU, memory and disk remain standard NetBox fields. Physical host metadata
is not duplicated VM capacity. Platform remains an operator-managed dictionary.

## Preparation and evidence

Connection, access check, preparation, review/finish are separate steps. Saved read/apply
credentials are server-side and require explicit replacement. DNS/network, TLS, read
and apply authentication, preliminary permissions and prerequisites have independent
status. GET/OPTIONS cannot establish every object-level PATCH right or absence of delete
rights. Operator permission review is still required.

Only missing fixed fields can be POSTed. Existing labels/groups and compatible additional
model bindings are preserved. Type, required/unique constraints and validation conflicts
stop creation; provisioning is pending, not ready. Older responses without a lifecycle
status are treated as active for compatibility. NetBox 4.7 status choice objects are parsed.
The plan expires after five minutes and is bound to configuration revision, public NetBox
URL, reconciliation and exact create definitions. The worker refreshes evidence before
writes and rechecks each field before its POST. No field update or rollback delete exists.

Immediately before each POST, the executor re-reads the specific field. A compatible
active field is reconciled without writing it. A conflict stops the operation with
`CONFLICT` and expected/actual property evidence. A provisioning field stops it with
`WAITING`. Neither case sends that POST or any subsequent POST. A known pre-dispatch
read/validation failure returns `RECHECK_REQUIRED`; its current uncertain marker is
cleared because the isolated child confirmed it did not dispatch. Unknown child outcomes,
crashes and lost responses still preserve the uncertain marker. Existing definitions and
previously created fields are never modified or deleted. After operator correction or
NetBox provisioning completion, refresh and explicitly confirm a new fenced plan.

The UI displays the full shared contract with ready/create/conflict counts, collapsible
non-blocking groups and always-visible conflict explanations. Technical keys remain in
field details. EN/RU screenshots and browser fixtures are generated from the production
Python contract, not a separate list. Older saved plans without detailed evidence require
refresh; additional evidence changes the digest and cannot silently reuse old confirmation.

An uncertain POST is journaled before dispatch and is never blindly retried. Refreshing
the plan resolves it only after the field is observed. If it remains absent, an operator
must investigate NetBox; there is deliberately no force-retry switch. Existing created
fields remain after failure or cancellation. Finish requires a fresh independent validation.

## Temporary setup credential

Supply a separate short-lived setup token with custom-field view/add permissions; a
short-lived administrator token is acceptable. Read/apply credentials are rejected as
setup credentials (including matching v2 public keys). Setup credentials travel over the
existing protected same-origin API and Unix control socket, then stdin to a bounded,
dropped-privilege subprocess. They are never written to state, backups, env or browser
storage. Only non-secret progress and revocation status are persisted. In-memory references
are released after completion/failure; this is not a claim of cryptographic memory erasure.
Closing the browser does not cancel an in-flight server request. Cancellation is between
attempts. A restarted attempt needs a new explicitly supplied credential and reconciliation.

Version 1 uses Token authorization; v2 `nbt_<key>.<secret>` uses Bearer. After immediate
successful preparation, a v2 token may be identified by an exact public-key/version query,
then its detail identity is rechecked before DELETE of that single token ID. This requires
view/delete token permission. No token list-all, plaintext-token query or read/apply token
revocation is performed. A v1 token, unavailable identity/permission, lost delete response,
partial creation or asynchronous provisioning requires manual revocation in NetBox.
Remote revocation and local retention are reported separately. A missing local credential
never proves remote revocation. Do not reuse the temporary credential after the attempt.

The secret broker remains literal `network_mode: none`, without database or NetBox access.
Only the bootstrap worker invokes these fixed HTTP actions. API DB privileges, shared
apply lock, lifecycle coordination and runtime token permissions are unchanged.

Official NetBox 4.7 implementation references:
- [Authentication](https://github.com/netbox-community/netbox/blob/v4.7.0/netbox/netbox/api/authentication.py)
- [Token filters](https://github.com/netbox-community/netbox/blob/v4.7.0/netbox/users/filtersets.py)
- [Custom field serializer](https://github.com/netbox-community/netbox/blob/v4.7.0/netbox/extras/api/serializers_/customfields.py)

## Container names and deployment boundary

The default project keeps its existing service, network and volume identities. Its nine
persistent container names are `netbox-sync-` plus postgres, proxy, api, secret-broker,
bootstrap-worker, lifecycle-worker, discovery-worker, apply-worker and schedule-worker.
Tools and scheduler invocations keep transient Compose-generated names. This remains one
product installation per host; isolated tests select a distinct Compose project explicitly.

Installer preflight checks any existing canonical name against Compose project/service
labels before stack build/start. A foreign name blocks installation; it is not adopted or
removed. A legitimate existing auto-named container is recreated by Compose for the same
service. The PostgreSQL named volume identity must remain unchanged.

Before a live upgrade, verify current release/config paths, Compose project and service
labels, existing volume identity and health using metadata only. Preserve all credential
files and the existing selected deployment root. Do not remove volumes or run a fresh
bootstrap with regenerated passwords. Follow the supported installer upgrade path after
reviewing its release/config preflight. Disposable production Compose rename and DB
preservation checks passed; see [verification and upgrade procedure](onboarding-verification.md).
This is repository evidence, not evidence of a live deployment or Debian reboot rehearsal.
