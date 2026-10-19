# Infrastructure read API v1

The existing NetBox Guard plugin provides these authenticated, read-only endpoints:

* `GET /api/plugins/netbox-sync-guard/infrastructure/v1/{kind}/{pk}/`, where kind is `device`, `cluster`, `vm`, or `interface`.
* `GET /api/plugins/netbox-sync-guard/firewall/v1/{vm_id}/`.

Both use NetBox authentication and object view permissions. An inaccessible context returns 404. Related objects are independently permission-filtered. HTML panels use the same infrastructure projection; table labels and translations are not an API contract. No endpoint creates Prefixes, VRFs, reservations, or firewall rules.

## Infrastructure document

`schema` is `netbox-sync.infrastructure.v1`. `context` identifies the requested object. `nodes` have typed stable IDs (`device:30`, `vm:2632`, `interface:3191`, `ip:42`, `site:1`, `cluster:40`). Network observations use `pfsense:{vm_id}:{interface_key}:{CIDR}`. Display names are not identity keys. A changed CIDR represents a changed observed network.

`edges` contain `kind`, `source`, and `target`: `located_in`, `member_of`, `hosted_on`, `interface_of`, `assigned_to`, `connected_to`, and `network_on`. Host placement comes from native VM.device, reconciled only for the same managed source and cluster. A managed migration within that source is supported; foreign manual assignments block reconciliation.

Network links require the same source instance, host, bridge/port group and VLAN, or the exact matched pfSense NIC. An equal name, IP or MAC alone does not establish a link. This first version does not infer shared L2 connectivity between different hypervisors. Missing links mean insufficient evidence, not proof of isolation. A future topology consumer must preserve this distinction.

`updated_at` is NetBox object modification time, **not** the time of a successful provider poll. `collected_at` on network/firewall observations is the collector timestamp. `sources` contains stable source identities. Physical hardware is separate from VM allocations; neither is live utilization.

`networks` includes CIDR, interface addresses, bounds, source VM, binding validity, collection time, freshness, limitations and address ranges. The same network observations also appear in `nodes` without address evidence. An IP search may return several independent contexts; they are never silently merged.

Address states: `assigned`, `observed`, `reserved`, `gateway`, `dhcp`, `unusable`, `conflict`, `candidate`, `unknown`. A candidate means no known assignment in complete, sufficiently recent available evidence. It does not guarantee that an offline or undiscovered host cannot use the address. This API does not answer firewall allow/deny or application reachability.

Networks are projected directly from observed interface IP/mask. Native Prefix creation is unnecessary for this read-only workflow, so an empty IPAM cannot block first use. Existing explicit NetworkBinding/IPAM data and ranges remain respected. Incomplete permissions, stale MAC bindings, unknown host placement, malformed or excessive evidence prevent candidate results. Native Prefix/VRF objects are never merged or created by the view.

## Firewall document

`schema` is `netbox-sync.firewall.v1`. The response preserves all validated component tables, their original row order and collection states, without the former 100-row display cutoff. Missing/invalid snapshots return explicit `unavailable`/`invalid` state. Each runtime section distinguishes `ok`, `error`, and (for older snapshots) `not_collected`.

`runtime.routes4` / `routes6` preserve routing output. `runtime.pf_filter` / `pf_nat` preserve the top-level interpreted PF filter/NAT rules, including automatically generated rules at that level. The collector runs only fixed read commands `pfctl -sr` and `pfctl -sn`, with bounded time/output. A successful empty ruleset is distinct from collection failure. These commands follow [Netgate's ruleset documentation](https://docs.netgate.com/pfsense/en/latest/firewall/pf-ruleset.html).

Known gaps are explicit: nested anchors, dynamic table contents, VPN session state, additional routing FIBs and effective-policy evaluation. Arbitrary directives/secrets remain excluded from structured configuration tables. Runtime text is evidence for inspection, not a parsed policy or proof of connectivity. The existing 1 MiB per command and 8 MiB snapshot safety bounds reject oversized collection rather than silently claiming completeness.

## Upgrade and acceptance

Deploy Sync and the Guard image together on the test installation first. Run normal NetBox migrations so the post-migrate field reconciliation creates hidden `sync_disk_identity`. Re-run Sync prerequisite preparation (contract version 6). The Apply identity needs native VirtualDisk view/add/change permissions; the application does not expand token permissions automatically. Managed disks use provider disk keys; existing manual/foreign disks are preserved and name conflicts block the plan.

Rebuild plans after upgrade (`web-5a-12`). The normal synchronization populates VM.device and individual VirtualDisk rows; NetBox then calculates the native VM disk total. Removed source disks are retained, matching the existing retention policy.

Existing pfSense installations need the updated collector installed through the established supervised connection/update procedure before PF runtime sections become available. Merely rebuilding Guard does not update remote pfSense files. Older snapshots remain readable and explicitly say that these sections were not collected.

Production button behavior, actual weekly/monthly execution across service restart, and onboarding a host with missing catalog entries remain installation acceptance checks. No deployment or production acceptance is implied by local tests.
