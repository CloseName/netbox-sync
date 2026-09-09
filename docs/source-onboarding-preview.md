# Source host preview and NetBox placement

## Operator flow

Add Source now has three steps: connect and read host information; choose existing
NetBox placement and per-host device types; explicitly confirm registration.
The generated Source ID is editable under Advanced settings before registration.
It stays the durable identity independently of later name/address edits. Display
name starts with the reported host/cluster name and remains editable.
Registration stores protected source credentials and configuration with sync OFF.
It does not create NetBox infrastructure objects or start discovery/plan/apply.

The six searchable catalogs show names and distinguishing manufacturer/type/site
context. Suggestions require one exact name/slug match across the complete result
set; device types additionally require an exact reported manufacturer and model.
Generic models (including Super Server) and missing hardware data require explicit
selection. This is catalog selection, never name-based device/VM adoption.
Search uses 20-row pages, up to offset 10000. Refine the search beyond that bound.
Empty lists, no matches and access/transport errors are distinct states. Expand
Missing an object? to open the configured NetBox list or refresh. Prepare missing
objects separately with appropriately authorized NetBox access; Sync does not
create catalogs or request broader token privileges.

A selected cluster must already be scoped to the selected Site and use the chosen
Cluster type. Unscoped/group-scoped clusters are not supported by the current
runtime target contract. Standalone ESXi does not report a provider cluster: the
operator selects its intended existing NetBox cluster explicitly.

## Bounded reads and access boundaries

The existing isolated probe worker performs the preview, with the same authorized
session/destination/policy-revision fencing, DNS pinning, TLS verification, UID
separation and stdin-only credentials. No new API egress is introduced. The whole
child deadline remains 15 seconds, I/O deadline 5 seconds. HTTP/SOAP reads are
limited to 2 MiB per response, projected result to 24 KiB, host count to 16 and
ESXi traversal to 64 entities. Exceeding a bound fails rather than silently
registering a truncated cluster. No VM, guest, disk or interface enumeration is
performed for the preview. This is not proof of all full-discovery permissions.

ESXi HostAgent supplies host name, summary hardware vendor/model, UUID, version,
CPU and memory. vCenter is rejected. The stable host identity matches full ESXi
discovery; full discovery now also records manufacturer/model. Proxmox reads
version, cluster/status, nodes and each nodes/{node}/status. Those endpoints expose
CPU/memory/version and cluster identity, but not SMBIOS server manufacturer/model.
CPU vendor and disk model are not substituted. Each Proxmox node therefore needs
its own explicit device type, even when operators know the hardware is identical.

Catalog GETs use the existing bootstrap worker's protected READY read-token state.
The API only transports a fixed allowlisted catalog RPC over its Unix socket;
the browser and API never receive the NetBox token. A sanitized child runs as UID
10001, validates the configured NetBox destination, pins DNS, retains custom CA
verification and uses GET only without redirects. Remote pagination URLs are never
followed. Four cross-process catalog slots, 30-second total child deadline, 5-second
I/O and 2 MiB response limits bound the work. Catalog reads do not acquire or weaken
the shared apply lock. No grants, services, networks or published ports change;
broker remains network_mode: none, PostgreSQL and workers remain private.

## Registration and subsequent runtime

Authenticated source.register permission covers catalog reads and registration.
The server re-fetches every selected ID before consuming the receipt or writing
credentials/registry state, comparing fingerprints of the projected identity,
name/slug, manufacturer, cluster type and scope. Unrelated object fields such as
description are outside that fingerprint. Changed/deleted/unverifiable selections
fail closed; the operator refreshes and explicitly confirms again. Catalog errors
before mutation preserve the receipt. An uncertain registration result is never
retried automatically. Origin/CSRF checks supplement server authorization.

Server-checked IDs and per-host mappings are stored in existing JSONB source
settings (onboarding_mapping version 1); migration head remains 0006_auth_policy.
Runtime resolves the selected cluster by ID, avoiding same-name ambiguity, and
validates mappings before writes. Each host uses its own selected Device Type.
A newly discovered/unmapped host, changed known hardware, or changed/deleted target
blocks use of that mapping; it never inherits the first host's device type.
There is not yet an in-place web editor for adding mappings to an existing source:
cluster membership changes require an explicit supported configuration review
before sync can resume. Do not delete/re-register a source to bypass identity
reservation. Existing registered sources without onboarding_mapping retain their
previous configuration/runtime behavior. ESXi's existing managed-VM/adoption
contract is unchanged; this feature does not add automatic ESXi device creation.

Nonsecret form data survives catalog refresh, language changes and sign-in expiry
in memory in the current tab. Reloading/closing the tab clears that memory. Passwords,
tokens and registration receipts are not persisted in browser storage. After
session expiry the operator re-enters credentials and repeats the bounded check;
no write is repeated automatically. Changed connection values invalidate receipts;
a changed destination policy is fenced by the auth worker before registration.

## Upgrade and compatibility

Upgrade API, probe worker, bootstrap worker and frontend together using the existing
installer and selected deployment root. There are no new host packages, env values,
Docker mounts, DB migrations or grants. Existing source credentials, DB volume,
onboarding READY state and policies remain in their existing stores. Take and
verify the supported backup before activation; do not replace config or credentials.
New production registrations require a preview receipt and checked catalog choices;
old version-only API registration clients must adopt this contract. Existing sources
are not automatically remapped. No installation was activated during development.

## Official references and verification scope

- [Broadcom HostHardwareSummary](https://developer.broadcom.com/xapis/virtual-infrastructure-json-api/latest/data-structures/HostHardwareSummary/): vendor, model, UUID, CPU and memory of the VMOMI summary type (read here through SOAP/pyVmomi).
- [Proxmox official Nodes API implementation](https://github.com/proxmox/pve-manager/blob/master/PVE/API2/Nodes.pm): node status shape and Sys.Audit permission; no server SMBIOS manufacturer/model in this status response.
- [NetBox REST API](https://netbox.readthedocs.io/en/stable/integrations/rest-api/) and [filtering](https://github.com/netbox-community/netbox/blob/main/docs/reference/filtering.md): existing object lists, search and pagination.

Unit/UI fixtures cover precise, generic and missing ESXi models, multiple Proxmox
nodes with explicitly different device types, ambiguous/large/empty catalogs,
access/transport failures, selection changes, expired sessions and explicit retries.
Production Compose tests use controlled HTTPS/SOAP and NetBox endpoints with TLS
verification, real worker/socket boundaries, bundled and external PostgreSQL.
These are local disposable fixtures, not live ESXi/Proxmox/NetBox validation.
No VM, live hypervisor, production credential or sources/ material was accessed.

Detailed counts and skip inventory: [verification record](source-preview-verification.md).
