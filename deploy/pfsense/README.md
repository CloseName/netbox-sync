# pfSense network snapshot, stage 1

`network-v1.php` is a standalone read-only collector for testing on pfSense CE.
It is not yet wired into the Sync service or NetBox writes. Compatibility must
be checked on each target version; the first target is CE 2.7.2.

Run `php -l network-v1.php` and `php test-network-v1.php` before activation.
The tests use synthetic XML and do not read the appliance configuration.
No PHP runtime was available on the development host for this initial release.

Install as root-owned 0644 `/conf/netbox-sync/network-v1.php`, in a root-owned
0755 directory. The account needs read access to configuration and execution of
PHP and ifconfig; no sudo or administrator membership is needed.
Never make the collector or its parent directory writable by the SSH account.

Replace the existing dedicated public key entry in pfSense User Manager with
`restrict,from="<collector IP>",command="/usr/local/bin/php -f /conf/netbox-sync/network-v1.php"`
followed by the public key. Keep the Shell account access privilege. Invoke with
SSH command `netbox-sync-network-v1`. Other commands, including an empty command,
are rejected when SSH_ORIGINAL_COMMAND is present. Direct local execution is
permitted for diagnostics. Keep strict host-key verification on the client.

The key restriction does not restrict password logins, other keys, or the Unix
account globally. Do not distribute the account password or grant extra keys.
pfSense's configuration can be readable by shell accounts and contains secrets.
The collector exports only named interface and VLAN fields, never entire XML,
passwords, certificates, VPN configuration, firewall rules or exception details.
The configuration and runtime reads are sequential, not an atomic snapshot.
Configuration MTU may be empty; actual MTU is in runtime ifconfig. DHCP strings
are modes rather than addresses. Additional runtime addresses must be preserved.
Runtime also contains service and loopback interfaces; these are not automatically
mapped to VM NICs. No inference about physical speed should be made from a
virtual interface's reported media.

`/conf` persistence and key restrictions must be rechecked after upgrades or
configuration restoration; custom files are not necessarily included in a
standard pfSense configuration backup. Rollback: restore the previous forced
`/usr/bin/id` key entry. This collector changes no network configuration.

## Stage 2: operator preview

`netbox_sync/pfsense_preview.py` parses the snapshot using only Python's standard
library. `netbox_preview(path, vm_id)` runs in NetBox's Django shell and reads the
explicit VM and its primary interface MAC addresses inside a read-only database
transaction. It performs no SSH, token lookup, NetBox writes, or service restarts.
This is an operator preview, not yet a web UI feature or a scheduled integration.

Matching uses MAC only within the selected VM. Duplicate MACs on either side,
missing interfaces or missing MACs are explicit blocking issues. Names and IPs
are never identity fallbacks. Additional WAN addresses remain separate; link-local
IPv6 is retained as an observation and excluded from IPAM candidates. Candidates
are observations only, not an approved IPAM write plan: VRF, ownership, freshness,
and existing assignments still need checking before any future apply operation.
The snapshot does not authenticate VM identity by itself. The operator selects
the SSH target with a verified host key and explicitly selects the NetBox VM.
The reader rejects malformed snapshots and non-contiguous netmasks.

Example inside `manage.py shell` after copying script and snapshot to /tmp:

```python
import runpy
preview = runpy.run_path('/tmp/pfsense_preview.py')
preview['netbox_preview']('/tmp/pfsense-snapshot.json', 2609)
```

A successful match does not create or rename interfaces or assign IP addresses.
Use the actual fresh SSH output file, not a terminal copy with wrapped JSON lines.

## Stage 3: VM snapshot field and panel

The Guard image includes the shared parser and `import_pfsense_network` management
command. By default the command previews; `--apply` creates the VM-only JSON
custom field `pfsense_network` when absent and saves only that key on the locked VM.
Incompatible existing field types/scopes fail closed. Missing or ambiguous NICs,
unmatched NetBox interfaces, timestamps more than 15 minutes old or 2 minutes in
the future prevent a new write. Replaying the exact stored value is a no-op;
older/conflicting data cannot overwrite a newer snapshot. Existing custom fields,
interface names, IP assignments and VM primary IPs are preserved.

`activate-test-panel.sh FULL_COMMIT` is specific to the operator-confirmed test
server layout: /netbox-test with docker-compose.yml and docker-compose.override.yml,
VM 2609, SSH target 10.24.0.1:2233 and the existing dedicated key. It verifies web
and worker image identity, layers onto that exact current image, and changes their
image references in the existing override while retaining all other YAML values.
YAML comments/formatting are not retained. It waits for the shared Sync apply lock
before restarting web/worker, leaves the timer stopped, then collects a fresh
snapshot, previews, applies, and repeats the same apply to verify no-op behavior.
No Sync container update or NetBox version upgrade is required. On rollout failure,
the script stops; inspect the error before repeating. The previous image remains
available, but a failure after activation may leave the new image configured.

The panel shows observations with collection time, not current live connectivity.
No periodic SSH collection or UI apply workflow is introduced by this step.
A NetBox ORM integration run and Docker build require the target server; local
coverage tests parsing, snapshot policy, and presentation separately.

## Stage 4: read-only IPAM plan

Run `netbox_sync/pfsense_ipam_preview.py` with `runpy.run_path` in the NetBox shell,
then call `netbox_ipam_preview(snapshot_path, vm_id)`. No image update is required.
The installed Guard supplies the network parser. The report reads all same-host
IP records across VRFs (including different masks), their assignments/status/role,
and covering prefixes in one repeatable-read, read-only database transaction.

Without an explicit interface-ID-to-VRF mapping, every candidate requires scope
selection. `{'3169': None}` explicitly selects Global for interface 3169; a positive
integer selects an existing VRF. Covering prefixes do not choose a routing domain.
Foreign assignments, unassigned existing records requiring adoption review,
duplicate records, duplicate observations and prefix-length conflicts are shown
separately. IPv6 link-local addresses are excluded. This is evidence only: no apply
operation is provided, and future apply must recheck freshness, ownership, scope,
and concurrent changes. IPAM candidates are not evidence that a public address
is safe to contact. No network probes are performed by this module.

## Deferred automation requirements (operator agreed)

Keep collection/import manual while validating the full data set. A future Sync
panel should manage explicit appliance-to-VM binding, access preparation, dedicated
keys, known-host fingerprint verification, collector installation/version and
scheduled collection. Neither VM names nor the string 'pfSense' identify an
appliance. Use the selected source-scoped VM identity and verify MAC correspondence;
duplicate/changed identities require review. Existing arbitrary VM names must be
preserved. Do not infer authorization to configure all discovered VMs automatically.

## Stage 5: reviewed manual Global IPv4 import

`pfsense_ipam_apply.py` is intentionally scoped to VM 2609 and the six reviewed
interface IDs/MACs and seven exact IPv4/prefix bindings in TEST_BINDINGS. Any changed
binding requires a new review. It calls the neighboring `pfsense_ipam_preview.py`
for conflict classification; copy both scripts into the same protected directory.
Inside NetBox's shell, use `runpy.run_path(...)["import_test"](snapshot_path)` for
preview, then pass `apply=True` for the operator-authorized import.

New writes require a fresh snapshot (15 minutes, future tolerance 2 minutes).
Apply uses one database transaction, locks the IP address table against concurrent
writers (including when Global uniqueness is disabled), and locks the target VM,
interfaces and MAC records. Lock wait timeout is five seconds. It validates all
seven addresses before any writes and calls model full_clean before each create.
Any error rolls back all creates. Exact existing assignments are no-ops; existing
unassigned, foreign, duplicate or different-mask records stop the entire operation.
No existing address is adopted, deleted, moved, or edited. IPv6, prefixes, VM primary
addresses and interface names are untouched. Created records receive active status
and a manual-observation description. No scheduler or continuing ownership/deletion
policy is implied by this one-off import. The manual path has not been integrated
with Sync's durable apply receipts; repeat execution verifies exact assignments.

For deployment, pause the Sync timer and hold its shared apply lock around preview,
apply and replay. Leave the timer stopped until the remaining manual tests finish.
No Docker rebuild is required. Unit tests cover binding drift/freshness and planner
conflicts; ORM transaction behavior must be verified on the actual NetBox server.

## Stage 6: optional component inventory

Install network-v1.php and inventory-v1.php together after running both PHP tests.
The existing forced SSH command and key stay unchanged; the dispatcher now accepts
exactly `netbox-sync-network-v1` and `netbox-sync-inventory-v1`. The original network
schema remains compatible. No sudo, rc scripts, service control, pfctl mutation,
VPN control sockets, generated configuration files or arbitrary command arguments
are used. Fixed bounded commands collect ifconfig, default-FIB IPv4/IPv6 routes,
pfSense package names/versions and process names (never process arguments).

Inventory components are Firewall rules, NAT (forward/outbound/1:1), aliases,
schedules, gateways/groups/static routes, OpenVPN, IPsec, WireGuard, HAProxy,
DHCP, DNS Resolver and DNS Forwarder. Installation comes from the pkg database,
not a leftover configuration node. Package lookup failure is unknown, not absent.
Firewall and core services are built-in. An empty VPN section is not configured,
not an error. Component extraction failures carry unknown configuration and an
explicit error, while other sections continue. Process presence is a separate
observation and never a health or tunnel-up claim. Arbitrary installed packages
are listed with versions but do not receive guessed service-specific adapters.

This first inventory adapter deliberately does not claim complete effective
policy or all package settings. It excludes credential fields, certificate/key
contents, URL alias contents, advanced/custom directives and HAProxy ACL expressions.
It does not yet query VPN sessions, IPsec SAs, WireGuard handshakes, live firewall
rules/states/counters, service health or extra FIBs. Tables preserve XML order and
raw allowlisted values; an empty string in a presence flag differs from an absent
field. Size/shape violations fail that section rather than silently truncating it.
The whole snapshot is bounded to 8 MiB. Additional pfSense/package versions require
validation on real targets before compatibility is asserted.

`import_pfsense_inventory --vm ID --snapshot PATH [--apply]` validates the schema,
freshness and core NIC-to-VM binding, and saves only `pfsense_inventory`. The network
snapshot and IPAM assignments remain unchanged. A new NetBox template shows distinct
presence, configuration, collection and process observations, then detailed tables,
packages and routing output. Rendering limits are explicitly labeled; the stored
bounded JSON retains all collected rows. Missing optional services remain visible.

`activate-test-inventory.sh FULL_COMMIT` uses the same reviewed Compose deployment
as stage 3. Install the collector on pfSense first. It builds on the current NetBox
image, updates web and worker, holds the shared Sync apply lock, collects a fresh
inventory and runs preview/apply/replay. It leaves the timer stopped and does not
upgrade Sync. The test pfSense still needs no new SSH privileges or key changes.

PHP fixture tests were executed locally using PHP 8.5; Python tests cover the cross-
language empty fixture, statuses, failure isolation, schema rejection, freshness,
row-order/render bounds and HTML escaping. The actual FreeBSD subprocesses and
NetBox ORM import must be checked on the test server. PHP tests run again before
collector installation on the target PHP version.


## NAT runtime snapshots (8 October 2026)

The GUI provisioning flow now installs `pf-runtime-v1.php` beside the two collectors
in the root-owned `/conf/netbox-sync-web/<account>` directory. A persistent pfSense
cron entry runs its fixed PHP path as root every minute; provisioning also runs it
once immediately. Repeat **Connect and collect** to update an existing installation.
The SSH account remains restricted and receives neither sudo nor `/dev/pf` access.

The producer executes only the fixed `pfctl -sn` command with bounded
output and runtime. It atomically publishes a root-owned read-only snapshot under
`/var/run/netbox-sync-pf/<account>.json`. Readers reject snapshots older than 150
seconds, future timestamps, failed sections and invalid data. Empty successful
output remains distinct from a read error. The volatile cache is recreated by cron
after reboot. Anchors and dynamic table contents remain outside this collection.
Manual legacy installations must migrate through the provisioning flow for this
mechanism; copying only network-v1.php does not install its producer.

Validate with `php test-pf-runtime-v1.php` in addition to the existing network and
inventory tests. Acceptance on pfSense: collect immediately, collect after two
minutes, then repeat after reboot; NAT must report a successful read.
To retire this remote collector, an administrator should remove its exact cron
entry before removing its root-owned scripts. Disconnecting Sync does not remove
remote accounts or configuration automatically.

Actual PF filter rules are no longer collected. Repeat Connect and collect after this upgrade to replace the remote producer and collector; ordinary collection does not install new scripts. Old snapshots containing pf_filter remain readable, but that field is discarded.
