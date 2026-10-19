# Physical server identity

Hardware evidence is collected for every configured host, without rules tied to host
names, NetBox IDs or account 29916. Only the test deployment acceptance script names
the two protected test Devices. The collector never changes Device.serial, management
IPs, guest placement, interface assignments, NAT references or provider network links
as a result of collecting hardware identity.

## Supported sources

* ESXi: `hardware.systemInfo.serialNumber`, system UUID (including the summary
  fallback), and `otherIdentifyingInfo` entries `SerialNumberTag` / `ServiceTag`.
  Asset tags and enclosure serial numbers are not system serial numbers.
* Selectel: explicit top-level `serial`, `service_tag`, `system_uuid` in the already
  collected resource, resource details and hardware configuration responses. The
  normalized inventory now retains these fields. A fresh collection and reviewed
  inventory import is needed if a previous import discarded them. This does not
  guarantee that Selectel returns them for a particular server or API credential.
* Proxmox: the stock node API exposes PCI/USB hardware, but no system DMI endpoint.
  With API-only access the status is `unsupported_api`. No SSH, agent, privilege
  expansion, guest SMBIOS, subscription server ID or speculative endpoint is used.
  Supporting DMI in future requires a separately authorized source adapter.

The Selectel `hw_uuid` identifies provider hardware; it is **not** a demonstrated
SMBIOS UUID. Resource UUIDs, MACs, disk serials, motherboard/chassis IDs, matching
names and shared public IPs do not become physical-server identity evidence.

## Matching and protection

The hidden JSON field `hardware_identity` stores typed identifiers, their source
field paths, status and observation time. This is machine evidence, not a new raw
JSON panel. Existing `Device.serial` remains available as system-serial evidence;
it is never overwritten by this collector.

Compare like types only: system serial to system serial, service tag to service tag,
system UUID to system UUID. Trim and case normalization preserve serial punctuation.
Placeholders, zero / all-ones UUIDs, conflicting observations and snapshots older
than 48 hours are excluded. Future timestamps beyond five minutes are excluded.
Literal `default` and sample serials `123456789` / `0123456789` are placeholders,
not hardware identity. Filtering also applies when reading existing snapshots and
native serial fields, without rewriting stored inventory or existing bindings.
An exact common identifier with a different value in another common type is a
conflict. Duplicate identities across provider resources or native candidates block
adoption. Existing bindings remain unchanged. Unresolved name/IP candidates remain
blocked even when another target has a matching identifier.

The normal Guard reconciliation plan consumes this evidence automatically. Applying
that plan still uses the existing fingerprint, transaction and nonce contract; the
collector update itself does not apply new bindings or create server cards. A
dedicated server with no existing candidate still needs a valid system serial and
placement for card creation. Missing evidence never justifies a guessed binding.

## Coverage and rollout

ESXi statuses distinguish `collected`, `not_reported`, `access_denied`, `read_error`
and `conflict`. Proxmox reports `unsupported_api`. Selectel evidence includes source
section coverage: an empty identifier set with denied/failed sections is not proof
that the physical server has no identifier. Retained sections are not fresh evidence.
Each new poll refreshes the observation timestamp and may therefore update host
metadata even when identifier values stay unchanged.
The desired observation time is represented symbolically in the canonical sync
plan so independent reads at review, prepare and apply do not invalidate it.
The actual fresh time is still written by the executor. Stored before values,
identifiers, status, source and all other fields remain part of stale-plan checks.

1. On the test host run `deploy/update-hardware-identity-test.sh`. It updates Guard
   and the test collector and checks protected network facts before/after.
2. Run fresh ESXi / Proxmox discovery and apply their normal reviewed plans.
3. Run the read-only `check.sh` printed by the update script to compare network facts.
4. Run `provider_hardware_check --account ACCOUNT --actor ACTOR` through NetBox's
   management entry point. It reports host coverage and pending dedicated decisions
   under a read-only transaction, without applying changes.
5. Run `deploy/collect-selectel-test.sh ACCOUNT`, review its report, and apply the
   generated inventory import. Then repeat the hardware check and the existing
   `provider_reconcile` plan. An inventory refresh may legitimately advance binding
   revisions, so the baseline from step 1 is intended for the update / hypervisor
   synchronization checks, before that provider import.

API references:
* https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.host.SystemInfo.html
* https://developer.broadcom.com/xapis/virtual-infrastructure-json-api/latest/data-structures/HostSystemIdentificationInfoIdentifier_enum/
* https://github.com/proxmox/pve-manager/blob/master/PVE/API2/Hardware.pm
