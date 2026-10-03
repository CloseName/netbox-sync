# Bridge names and readable NetBox metadata

## Result

Guest VM and LXC interfaces use the discovered bridge/port-group name. Provider
labels and ownership identities remain unchanged in discovery and JSON metadata.
Existing managed interfaces are renamed by ID; IP/MAC references are retained.
No physical ESXi networking or pfSense discovery is introduced.

- Unique bridge within a guest: `LAN OA`, `VM Network`, `vmbr0`.
- Multiple NICs on the same bridge: `VM Network / 4000`, `VM Network / 4001`.
  The suffix is the stable NIC key (a digest when that key is longer than 16 characters).
- Missing bridge: retain the provider interface name.
- NetBox VMInterface names have a 64-character limit. Overlong names keep a
  bounded prefix plus the NIC suffix; the full bridge remains in `source_bridge`.
- Occupied names, including rename cycles, block the network preflight before
  interface writes. Unmanaged old provider-name candidates remain blockers too.
  No name-based adoption, deletion, temporary renaming or identity replacement.
- Planner version is now `web-5a-8`; rebuild plans after upgrading.

The optional NetBox Guard plugin adds a read-only panel to Devices, Interfaces,
VMs and VM Interfaces. It formats `sync_original_names`, `physical_disks`,
`sync_network_observations` and `sync_identities`. Identities are in a collapsed
technical section. Existing JSON values and API responses are unchanged. No
new custom fields, duplicated display values or inventory migration are needed.
Unknown nested observation keys remain available as labeled rows. HTML is escaped.
Unrelated operator JSON fields are not modified or exposed by the panel.

## Deployment sequence

This change requires BOTH a new Sync release and a new NetBox Guard image.
Do not use an old saved plan to test it. During the ongoing capacity measurement,
record the deployment time; rollout/restarts are not steady-state samples.

1. Use the existing backup/update procedure. Stop automatic scheduling and let
   active writes finish. Preserve the prior timer state, release and both NetBox
   image references. Keep the mounted LDAP/configuration files unchanged.
2. Build the Guard image with `deploy/Dockerfile.netbox-guard`, explicitly using
   the currently installed operator image as `NETBOX_BASE_IMAGE`. Do not combine
   this change with a NetBox version upgrade. Update **both** NetBox and worker
   Compose services to the same new image using the existing operator procedure.
3. In the updated NetBox container, check that the plugin and template load:

```bash
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py check
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py configure_sync_display
```

4. Open one VM, VM interface and physical host. Confirm the new panel works and
   shows original names, disks, VLAN/bridge and observations. At this point the
   old raw JSON fields are still visible. Then hide only those four native fields:

```bash
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py configure_sync_display --apply
```

The command changes only `ui_visible`. It validates field types and model scopes
before updating, in one transaction. It does not alter values, permissions,
field types or ownership. If the fields are created later, rerun this command.

5. Install the new Sync release using the existing deployment procedure. Build a
   fresh plan for one source. Expected changes are managed interface names, not
   recreated interfaces, IPs or MACs. Review and apply. Rebuild: expect no changes
   unless provider inventory changed. Restore automatic scheduling afterward.

To restore the standard raw-field display before rolling back the Guard image:

```bash
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py configure_sync_display --raw --apply
```

This sets visibility to `always`; it does not restore any prior `if-set` preference.
Rolling back Sync does not itself rename anything, but the next old-version apply
will propose the former provider interface names. Rebuild/review that plan.

## Validation

103 tests passed: interface display, Django HTML rendering/escaping, first sync,
ESXi bootstrap/runtime, comments, network scopes, source identity, interface
migration, sync plans and IP observations. Existing-name migration and subsequent
bridge changes preserve interface IDs, IP/MAC assignments and raw original names
for ESXi, Proxmox VM and LXC. Duplicate bridges, unmanaged collisions and rename
cycles are covered. The large ESXi fixture now has distinct instance/BIOS UUIDs,
matching its intended independent-VM inventory.

NetBox 4.7.0 source confirms VMInterface name length, plugin template-extension
hooks and `ui_visible` choices. Full NetBox/PostgreSQL/browser integration was
not executed here because the local Docker engine is unavailable. The visibility
command must first be previewed and the panel checked in the updated NetBox.
No remote deployment or remote data change was performed.
