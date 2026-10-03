# ESXi host network snapshot

## Operator-visible result

The device detail page has a full-width **Сеть хоста ESXi** panel below the main
cards. It contains separate readable tables for:

- Physical vmnic: MAC, link, speed in Mbit/s, duplex, driver, standard vSwitch membership.
- Standard vSwitch: MTU, physical uplinks and port-group names.
- Port groups: provider name, switch and VLAN ID, including VLAN 0.
- VMkernel: device, connection, MAC, IPv4/mask, IPv6, MTU and DHCP.

The snapshot is observed inventory, not an assignment of IPs to physical adapters.
No native dcim interfaces, MAC records, IP assignments or cables are created by
this feature. A VM's source bridge names its port group/network; it is not the
physical vmnic name. Guest interfaces already use that network name since 891b673.

The collector uses only allowlisted HostNetworkInfo properties. It does not copy
arbitrary provider configuration. Standard-switch uplinks are resolved through
physical-NIC keys. Distributed VMkernel connections retain their explicit switch
UUID and port/group keys; full distributed/opaque topology is not supported and
its presence is labeled in the panel. Missing network data is shown as unavailable,
not as a verified empty network. Link status is the state at the last applied
collection, not a live monitoring heartbeat.

Reference: https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.host.NetworkInfo.html

## Storage and synchronization

`esxi_host_network` is one JSON custom field on `dcim.device`. Its native raw
presentation can be hidden by `configure_sync_display --apply`; the Guard plugin
renders the readable panel independently. JSON remains available through the API.
The schema is version 1; prerequisite contract is version 3, planner `web-5a-9`.

New hosts receive the snapshot at creation. Already managed hosts without a newer
onboarding mapping also receive it, via a field-only update preserving their name,
placement, existing custom fields and hardware. Unmanaged/adoption candidates are
not claimed. Snapshot lists are sorted for deterministic plans; repeat plans with
unchanged provider state have no writes. Changed link/network facts update the
snapshot on the next reviewed or scheduled synchronization.

Before writing, ESXi synchronization checks the new field's type, model and status.
An absent, conflicting or provisioning field produces `HOST_NETWORK_FIELD_REQUIRED`
in the Web plan. No partial synchronization is used to install the field.

## Rollout (no backup operation in this procedure)

1. Use the established two-image deployment procedure, with automatic scheduling
   stopped and active writes allowed to complete. Update Sync and both NetBox
   services' Guard image, retaining the current NetBox version and mounted config.
2. In Sync's NetBox settings, open **Подготовка NetBox / Prepare NetBox** and review
   the preparation plan. For the current version-2 installation, only
   `esxi_host_network` should be missing. Create the missing field with the normal
   temporary setup token workflow; prior fields/read/apply tokens stay intact.
3. After field preparation, hide its raw rendering alongside the existing fields:

```bash
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py configure_sync_display
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py configure_sync_display --apply
```

4. Build a new plan for one ESXi source and review/apply it. Open that source's
   **Device** in NetBox (not the Cluster). Verify the new network panel. Rebuild
   the plan and check that unchanged inventory produces no changes.
5. Repeat new-plan/apply for Infra 1, DevBA and other sources whose VM interfaces
   still have old provider labels, then restore the desired schedule. Installing
   images or running discovery alone does not update persisted interface names.

If a newly applied plan still leaves `Network adapter` despite a known source
bridge, inspect that run and the interface's identity; do not bulk-rename based on
labels or hide a blocked/unmanaged object. The code already covers owned guest NIC
renames across ESXi, Proxmox VM and LXC without changing IP/MAC references.

## Validation and limits

133 Python tests passed, 14 PostgreSQL-backed prerequisite tests skipped because
no database fixture was configured. Four focused frontend tests passed and
TypeScript typecheck passed. Tests cover new/legacy hosts, unchanged replanning,
single-field network updates, missing/incompatible/provisioning prerequisites,
version-1/2 preparation upgrades, stable ordering, absent data, VLAN 0, explicit
distributed references, IPv6 and HTML escaping. Prior guest-interface/identity
regressions also pass.

Full NetBox/PostgreSQL/browser integration and remote deployment were not executed
in this work session. The earlier readable metadata deployment was reported
accepted by the operator; this additional host network panel is a separate rollout.
