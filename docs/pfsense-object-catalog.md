# pfSense object catalog

The NetBox plugin menu has a pfSense overview and a separate configuration search.
Each accepted pfSense VM has an appliance page: overview, interfaces/networks,
rules, NAT, aliases, routes, VPN, services and observations/packages. The VM links
to this page instead of repeating the entire inventory. Existing network/IPAM
panels and native assignments are preserved.
The interface tab includes observed VLAN configuration; these observations do not
invent native VLAN/interface assignments. The appliance header links to the existing
confirmed networks/IPAM view. Runtime observations and installed packages remain
available under their own tab.

## Storage and identity

FirewallAppliance is scoped to one existing VirtualMachine. FirewallObject holds
one allowlisted configuration row with UUID, component/table, order, enabled flag,
observation timestamps and collection state. FirewallReference links configuration
objects inside that appliance. Native interface links require the same VM, interface
ID and MAC; prefix links use existing operator-confirmed NetworkBinding records.
Address mentions in rules/aliases/NAT never create IPAddress or Prefix objects.
Equal IP literals on different firewalls are independent observations.

Rules use the source tracker; named objects use their source name/identifier.
Reordering preserves UUIDs. Anonymous objects use a content fingerprint: changing
their configuration creates a new object and retains the old one as removed.
Duplicate source identifiers are marked ambiguous and use content identity.
Do not interpret these identities as a guarantee that arbitrary NAT edits retain
their UUID. User custom fields are supported as supplementary metadata and are
preserved on updates; configuration lives in typed object fields and allowlisted
data, not in user custom fields. This release exposes read-only configuration UI
and API; a write-back constructor is not implemented.

## Collection and permissions

Projection is in the same database transaction as an accepted inventory import.
Successful absence marks previously observed rows removed; a component collection
error retains previous rows with a visible retained state. Older observations do
not replace newer ones. Repeated identical imports preserve IDs. Upgrade backfills
valid saved snapshots without connecting to firewalls or enabling schedules;
incompatible snapshots are counted in a warning and left untouched.
Catalog rows are dependent on their VM. Existing guarded lifecycle rules still
refuse unknown dependencies rather than silently deleting the new inventory;
no cleanup bypass or permission expansion is added in this release.

Catalog access inherits native VM view permissions including object restrictions.
All pages, search and API enforce the same scope. Native interface/prefix links
also respect their own view restrictions. No secrets or unfiltered configuration
exports are added; the existing collector allowlist remains authoritative.

## Search and Map contract

Global NetBox results retain their ordering and contents. Users with visible
pfSense appliances get one link that carries the query into pfSense search.
The global search does not scan every rule or index configuration IP mentions.

Dedicated search filters by appliance, site, category, collection state and enabled
state. Results are paginated (50) and explain direct/alias matches. Exact IPs match
CIDRs and ranges; CIDR queries match containing networks. Text searches match names
and descriptions; port searches include ranges. Recursive aliases are resolved only
inside the same appliance, with cycle/depth bounds. Negated references are still
searchable and shown as configuration mentions, not effective traffic permissions.
Dynamic URL alias contents and effective policy evaluation are not collected.

Read-only API:

- `GET /api/plugins/netbox-sync-guard/firewall/catalog/v1/`
- `GET /api/plugins/netbox-sync-guard/firewall/catalog/v1/<uuid>/`

List accepts the same filters and `page`. Each record includes UUID, appliance/VM,
category, source order, enabled/state, allowlisted data, referenced object UUIDs,
and confirmed native interface/prefix links. Consumers must preserve appliance
scope and collection state, and must not infer cables or IP ownership from rule
references. This is the graph foundation for Map, not traffic simulation.

## Acceptance

After the test update, open NetBox Sync > pfSense. Existing valid saved snapshots
should appear without reconnecting. Check one firewall and all tabs, open an alias,
follow its incoming rule links, then search an IP in its CIDR. Confirm the same IP
on another firewall stays in a separate scope. Global search should show its usual
IPAM/device results plus one pfSense link. Check a user restricted to one VM cannot
open another firewall by direct URL or API. Collect twice: stable objects keep
their URLs. Physical/native IP assignments and schedules must remain unchanged.

Automated native coverage is in `tests/netbox_pfsense_catalog_scenario.py`; pure
identity and search tests are in `tests/test_pfsense_catalog.py`. Live appliance
collection remains an operator acceptance check.
