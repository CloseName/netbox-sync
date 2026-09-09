# Preparing source access / Подготовка доступа к источникам

The Add Source form includes EN/RU instructions and copyable CLI commands under
**How to prepare access / Как подготовить доступ**. Expanding help or changing its
language preserves entered values. Field hints remain visible. The credentials
are cleared after a connection attempt, as before.

Use `netbox-sync` as the example service username on each independent source and
as the Proxmox token name. Existing names are supported. Identical names do not
mean shared passwords or token secrets. Issue and rotate each source's credentials
independently. Never paste secrets into commands, logs, tickets or screenshots.

## Permissions derived from adapter operations

Reviewed against the actual repository adapters and official references below.
These are a least-privilege mapping, **not a new live hypervisor certification**.
A successful Test Connection establishes version negotiation/login, not full
inventory permission coverage. Run Discovery and review coverage/warnings before
turning on synchronization. Narrower ACL scope intentionally limits inventory.

| Adapter operations | Read privileges / scope |
| --- | --- |
| Proxmox nodes, status, disks/list, network (`proxmox_discovery.py`) | `Sys.Audit` on nodes; `/` with propagation for cluster-wide discovery |
| QEMU/LXC lists and configuration | `VM.Audit` on the VM scope |
| Node storage summaries | `Datastore.Audit` on the storage scope |
| QEMU `agent/network-get-interfaces` | Current API: `VM.GuestAgent.Audit`; older API revisions require broader `VM.Monitor` |
| ESXi RetrieveContent and rootFolder/hostFolder/childEntity traversal; host hardware, config.network/storageDevice/autoStart properties; datastore and VM config/hardware/guest.net/runtime properties (`esxi_discovery.py`) | Built-in **Read-only**, assigned to Host with propagation to child objects (`System.Anonymous`, `System.View`, `System.Read`) |

The ESXi adapter does not change host configuration, power VMs, upload files,
execute guest commands or browse datastore file contents. Host.Config.* privileges
attached to configuration-changing methods are not needed just to read inventory
properties. A successful login can still return incomplete inventory if ACLs hide
objects. This product's documented compatibility baseline is standalone ESXi 6.7
build 20497097; 7/8 or other releases need separate acceptance. This is not a vendor
support-lifecycle statement and does not add vCenter support.

## Proxmox UI and CLI

1. An operator authorized to manage identities opens **Datacenter → Permissions →
   Users → Add**. Create `netbox-sync` in realm `pve`, yielding `netbox-sync@pve`.
   `pve` is the Proxmox authentication server; `pam` refers to a Linux account that
   must already exist. Existing users/realms work when explicitly authorized.
2. Under **Permissions → Roles**, create a dedicated `NetBoxSyncRead` role with
   `Sys.Audit VM.Audit Datastore.Audit`. Under Permissions, **Add → User Permission**:
   path `/`, this user/role, propagation enabled. This grants cluster-wide reading;
   choose narrower scope only when reduced discovery coverage is intended.
3. **API Tokens → Add**: select user `netbox-sync@pve`, token name `netbox-sync`,
   retain **Privilege Separation**, set expiration by policy. **Save the secret
   privately when issued; Proxmox displays it only once.**
4. **Add → API Token Permission** (some versions label this Token Permission):
   `netbox-sync@pve!netbox-sync`, same role/path/propagation. Effective permissions
   are the intersection of user and token permissions; one ACL alone is insufficient.
5. In NetBox Sync: **Token user** = `netbox-sync@pve`; **Token name** = `netbox-sync`
   (without user prefix); **Token secret** = the privately saved issued value,
   not the user's password.

Equivalent administrative CLI (review existing identities/role before running;
stop on errors; do not overwrite a role shared by other applications):

```sh
pveversion
pveum user add netbox-sync@pve
pveum role add NetBoxSyncRead --privs "Sys.Audit VM.Audit Datastore.Audit"
pveum acl modify / --users netbox-sync@pve --roles NetBoxSyncRead --propagate 1
```

The following command emits a one-time secret: save it privately immediately;
do not capture its output in logs or a report.

```sh
pveum user token add netbox-sync@pve netbox-sync --privsep 1
pveum acl modify / --tokens 'netbox-sync@pve!netbox-sync' --roles NetBoxSyncRead --propagate 1
pveum user token permissions netbox-sync@pve netbox-sync
```

For guest IP discovery, inspect the **installed version's** API permissions for
`/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces`. If `VM.GuestAgent.Audit`
is supported, add it to the dedicated role used by both ACLs:

```sh
pveum role modify NetBoxSyncRead --privs "Sys.Audit VM.Audit Datastore.Audit VM.GuestAgent.Audit"
```

This replaces the role privilege list. Do not issue it against a shared role.
Do not substitute broad `VM.Monitor` automatically on older versions. Obtain an
explicit policy decision; without approved guest-agent access guest IP information
may be incomplete. A running/enabled guest agent is also required. The UI explains
this limitation and does not claim the three base privileges cover guest IPs.

## ESXi Host Client

1. Sign in as an operator authorized to manage local users and permissions.
   **Manage → Security & users → Users → Add user**: create local `netbox-sync`
   with a unique strong password, according to host policy.
2. Right-click **Host → Permissions → Add user**: select that account,
   **Read-only**, **Propagate to all children**. Do not assign Administrator/root.
3. NetBox Sync **Username** is the local account name, e.g. `netbox-sync`;
   **Password** is its password on this host. No Proxmox realm suffix or vCenter
   credentials. UI wording can vary by Host Client version.
4. If lockdown blocks direct API access, the security administrator must decide
   whether this Read-only account may be an **Exception User**. An exception does
   not grant inventory privileges by itself. Do not disable lockdown or SSH/DCUI
   protection to complete setup. If exceptions are prohibited, direct-host
   integration is unavailable under that policy.

## Official sources

All instructions are paraphrased; the operation-to-permission mapping above is
our inference from adapter reads and documented method permissions, not a claim
that the vendor certified NetBox Sync.

- [Proxmox user, realm, role and separated token semantics](https://github.com/proxmox/pve-docs/blob/master/pveum.adoc).
- [Official pveum CLI syntax and options](https://github.com/proxmox/pve-docs/blob/master/generated/pveum.1-synopsis.adoc).
- [Proxmox API viewer](https://pve.proxmox.com/pve-docs/api-viewer/), use the API viewer shipped with the installed release for version-specific privileges.
- [Node APIs](https://github.com/proxmox/pve-manager/blob/master/PVE/API2/Nodes.pm), [disk reads](https://github.com/proxmox/pve-storage/blob/master/src/PVE/API2/Disks.pm), [storage visibility checks](https://github.com/proxmox/pve-storage/blob/master/src/PVE/API2/Storage/Status.pm).
- [Current QEMU guest-agent method permissions](https://github.com/proxmox/qemu-server/blob/master/src/PVE/API2/Qemu/Agent.pm) and [official granular permission change](https://lore.proxmox.com/pve-devel/20250717133711.84715-5-f.ebner%40proxmox.com/T/).
- [Broadcom Host Client local-user and permission navigation](https://knowledge.broadcom.com/external/article/304569). This article illustrates an Administrator account; we use its navigation only and deliberately select Read-only for this adapter.
- [Broadcom Read-only role's system privileges](https://knowledge.broadcom.com/external/article/438487/vcenter-preversion-9-license-not-shown-i.html); its license-management workaround is not required by our discovery.
- [SessionManager](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.SessionManager.html), [PropertyCollector](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vmodl.query.PropertyCollector.html), [HostSystem properties versus modifying methods](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.HostSystem.html).
- [Broadcom lockdown exception administration](https://knowledge.broadcom.com/external/article/425190).
