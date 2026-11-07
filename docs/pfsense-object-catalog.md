# pfSense object catalog

The NetBox plugin menu has one pfSense overview: Host, pfSense, VM in NetBox,
Site, Last collection and State. Host links to the VM's explicitly assigned Device,
subject to Device permissions; no cluster-based inference is made. The VM link has
the fixed label `VM в NetBox`. Counts are omitted.

Each appliance has System, Interfaces, Firewall, Services, VPN, Status,
Diagnostics and Help sections, with URL-addressable child tabs and local search.
System includes General Setup, Certificates, User Manager, Routing and packages.
The first child opens by default; old `tab=` links remain compatible. Rules and
DHCP pages group records by interface. IPsec Phase 2, WireGuard peers, HAProxy
backend servers, schedule ranges and CRL entries appear below their explicit
parent object. The VM links to the catalogue instead of duplicating it.
Existing network/IPAM panels and native assignments are preserved. Unsupported
sections such as Advanced explicitly say they are not collected; no live control
or fictitious empty configuration is presented. Help provides snapshot/version
information and the official documentation link.

## System collection

`system-v1.php` extends the same bounded allowlist collector, not a second endpoint.
General Setup collects hostname/domain, DNS servers with hostname/gateway,
DNS override/local mode, timezone, time servers, language and GUI presentation
settings. User Manager collects local users, groups/membership/privileges,
expiry/disabled flags, certificate references, nonsecret LDAP/RADIUS connection
settings and authentication/session settings. External directory users are not
enumerated. Missing fields keep their unset state; appliance defaults are not guessed.

Certificates collects Authorities, Certificates and CRLs with source refids,
CA links, public X509 metadata, SHA256 fingerprints, validity dates, public-key
algorithm/size, CSR/private-key presence flags and internal revocations. Imported
public CRLs are envelope-checked on pfSense and decoded into metadata/revocation
objects in NetBox. Parse errors remain explicit. Validity means date validity at
collection time, not revocation status, trust or live certificate acceptance.
Renewal changing a certificate with the same refid preserves its object URL.
Explicit GUI, VPN, authentication-server, user and CA references form graph edges.

Passwords, password hashes, LDAP bind passwords, RADIUS secrets, private keys,
SSH authorized-key bodies and arbitrary configuration subtrees are excluded at
collection. Public CRL bodies are not displayed or retained in catalog objects.
The algorithm name `pwhash` is a setting, not a password hash.

Old snapshots/collectors remain readable. Missing new components are marked
`not_collected`, never empty or successfully collected; previous known rows are
retained. After updating NetBox, use **Connect and collect** once for the existing
pfSense binding to install the new collector with its existing managed key.
Ordinary collection does not upload collector files. Account deletion is unnecessary.

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
their configuration creates a new object and drops the superseded row.
Duplicate source identifiers are marked ambiguous and use content identity.
Do not interpret these identities as a guarantee that arbitrary NAT edits retain
their UUID. User custom fields are supported as supplementary metadata and are
preserved on updates; configuration lives in typed object fields and allowlisted
data, not in user custom fields. This release exposes read-only configuration UI
and API; a write-back constructor is not implemented.

## Collection and permissions

Projection is in the same database transaction as an accepted inventory import.
Confirmed absence in a successfully collected component deletes the corresponding catalog rows. A component collection
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

Global NetBox results retain their ordering and contents. There is no standalone
pfSense search page or global-search shortcut. Global search does not scan rules
or index their IP mentions.

Search inside an appliance covers its selected tab/interface or the whole firewall,
with an enabled/disabled filter. Current UI pages omit confirmed removals. The read-only API retains explicit historical state queries. A supplied appliance ID cannot escape that scope. Results are paginated (50). Exact matches precede a collapsed group of covering networks and ranges. Rules are numbered within each interface (Floating has its own sequence), before filtering and pagination. Configuration order and stable graph IDs remain in the API. Alias references link to the rule and its interface path. Exact IPs match
CIDRs and ranges; CIDR queries match containing networks. Text searches match names
and descriptions; port searches include ranges. Recursive aliases are resolved only
inside the same appliance, with cycle/depth bounds. Negated references are still
searchable and shown as configuration mentions, not effective traffic permissions.
Dynamic URL alias contents and effective policy evaluation are not collected.

Read-only API:

- `GET /api/plugins/netbox-sync-guard/firewall/catalog/v1/`
- `GET /api/plugins/netbox-sync-guard/firewall/catalog/v1/<uuid>/`

The read-only Map API retains appliance/site/category/state/enabled filters and `page`. Each record includes UUID, appliance/VM,
category, source order, enabled/state, allowlisted data, referenced object UUIDs,
and confirmed native interface/prefix links. Consumers must preserve appliance
scope and collection state, and must not infer cables or IP ownership from rule
references. This is the graph foundation for Map, not traffic simulation.

A full host IP additionally looks up address evidence on this appliance. The search reports native IPAM assignments in the explicitly bound prefix/VRF, local interface addresses, VIPs, static DHCP mappings, enabled pools and observed ISC leases. Unbound networks can show visible VM assignments with confirmed host, bridge, VLAN and source. Only a fresh, complete, unambiguous IPv4 context with a confirmed prefix can report a static candidate. Unavailable leases, partial evidence, overlapping networks and retained observations are distinguished. Lease expiry is checked by the collector but not stored. No reservations or writes occur during lookup.

## Acceptance

On an appliance, each configuration list uses columns specific to its pfSense tab.
Rules show local order, action, protocol, endpoints and ports. Gateway, queue
and schedule columns appear when used on that interface. NAT shows translation
or its exception. Alias lists preview two members and link to the full list.
The IP, port and URL alias filters apply inside the selected firewall. User,
certificate, VPN, routing and service pages show their own key fields. Open a
row by number for the full public configuration, related objects and nested
records. A search result carries its query into the detail view and offers a
return link to its original list, filters and page. Existing snapshots work
immediately. Queue details and NAT rule associations need a snapshot from the
updated pfSense collector when these settings exist on the appliance.

After the test update, open NetBox Sync > pfSense. Existing valid saved snapshots
should appear without reconnecting. Check one firewall and all tabs, open an alias,
follow its incoming rule links, then search an IP in its CIDR. Confirm the same IP
on another firewall stays in a separate scope. Global search should show its usual
IPAM/device results without any pfSense shortcut or rule results. Check a user restricted to one VM cannot
open another firewall by direct URL or API. Collect twice: stable objects keep
their URLs. Physical/native IP assignments and schedules must remain unchanged.

Automated native coverage is in `tests/netbox_pfsense_catalog_scenario.py`; pure
identity and search tests are in `tests/test_pfsense_catalog.py`; System contracts are in
`tests/test_pfsense_system.py` and `deploy/pfsense/test-system-v1.php`. Live appliance
collection remains an operator acceptance check.
