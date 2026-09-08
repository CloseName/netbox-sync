# Bootstrap / first-run onboarding

Use this with [deployment](deployment.md) and [backup/restore](backup-restore.md).
The historical test installation is not an input to this procedure. Production and
historical-server changes require a separate explicit operation. This implementation
does not include LDAPS/RBAC, TLS automation, or automatic infrastructure creation.

## Clean installation

Follow the exact [DNS/TLS clean-install runbook](clean-install-tls-runbook.md).
Use `deploy/install.py --init-tls-layout`, copy operator certificates and optional
NetBox CA, validate with `--check-tls --public-url https://your.fqdn`, then run the
normal installer with the same public URL and reviewed release ID. For an
operator-managed shared ingress, choose `--ingress-mode external`; only optional
NetBox CA is supplied locally, while outer ingress owns the public certificate. No manual env
fabrication or legacy naming migration is part of a fresh installation.

The existing installer transaction prepares `/opt/netbox-sync/releases/<release-id>`,
generates protected role-specific config and infrastructure passwords, builds the Web
image, starts bundled PostgreSQL, provisions roles, migrates through
`0005_source_tombstones`, applies grants and activates `/opt/netbox-sync/current`.
It starts nginx, API, broker, lifecycle, bootstrap, discovery, apply and schedule workers,
then enables the canonical systemd timer. No legacy naming migration is needed.
No NetBox token or provider configuration is required to start these processes.
A registry-all scheduler tick with zero sources performs no provider/NetBox work.

Open the configured HTTPS public URL. nginx is the supported TLS boundary;
production API uses a private Unix socket with no TCP publication. See
[TLS trust and external NetBox prerequisites](tls.md). First-run browser operations
need no env editing. This remains a pre-RBAC interface for a trusted operator network.

## Browser flow

1. Any application route enters Welcome while setup is incomplete. `/setup` is also
   a direct production SPA route. Unavailable state never unlocks the normal UI.
2. Enter the NetBox HTTPS origin (no userinfo, path, query, or fragment) and two
   distinct tokens. Save connection clears both password inputs. The checkbox makes
   replacement of existing credentials deliberate.
3. Test connection and prerequisites. Errors distinguish DNS/network, TLS, rejected
   token, missing permissions, incompatible response and missing custom fields.
4. Correct tokens or the listed NetBox fields, then validate again. No automatic
   prerequisite writes occur; a partial set of fields remains incomplete.
5. Review the destination and Finish within five minutes of successful validation.
   Finish is idempotent. It changes readiness only; it performs no synchronization.
6. Normal Overview/Sources shows zero sources. Add Source remains the sole source
   onboarding flow, with per-source Proxmox or ESXi credentials and sync initially off.

Use **NetBox connection** in navigation to revisit `/setup`. Replacing tokens blocks
new source writes and worker credential resolution until validation and Finish succeed.
After the first Finish the NetBox URL is immutable in this UI: pointing existing source
identities and review contexts at another NetBox requires a separately reviewed transition.

## NetBox rights and prerequisite evidence

The read token must have token writes disabled and view access for managed/reference
objects. The apply token needs view/add/change for the managed object scope, with no
delete permission. Both must belong to appropriate NetBox accounts/permission groups;
using two strings does not establish that account-level privileges are narrow.

The probe performs only GET and OPTIONS on devices, physical interfaces, clusters,
virtual machines, VM interfaces and IP addresses, plus GET on custom fields. It checks
list-response shape and POST metadata for read/apply separation. This is bounded
read-only evidence, **not proof of every object-specific change permission or of the
absence of account-level delete rights**. The operator must review permissions; actual
planning/apply retain their existing target, scope and stale-plan guards.

The exact managed custom-field contract is `bootstrap_probe.FIELDS`, audited against
`netbox_metadata`, `netbox_vm_metadata`, `netbox_lxc_metadata` and
`netbox_vm_interface_metadata`:

| Fields | NetBox type | Object types |
| --- | --- | --- |
| sync_identities, sync_original_names | JSON | Device, Interface, Virtual Machine, VM Interface |
| hypervisor_version, cpu_model, cpu_vendor | Text | Device |
| cpu_sockets, cpu_cores, cpu_threads, memory_mb | Integer | Device |
| physical_disks | JSON | Device |
| guest_kind, guest_architecture, guest_os_type | Text | Virtual Machine |
| swap_mb | Integer | Virtual Machine |
| source_bridge | Text | VM Interface |
| source_vlan_id | Integer | VM Interface |

Create missing fields in NetBox's Custom Fields UI with exactly these internal names,
types and assignments. Review incompatible existing fields rather than blindly changing
them. The screen reports each required field. Existing Site, Cluster, device roles/types,
platforms and source target choices remain operator responsibilities; there are no
historical IDs. VLANs/Prefixes and other infrastructure are never fabricated.

Validation trusts the explicitly entered NetBox hostname only, checks all DNS answers
against hard exclusions (loopback/link-local/metadata/multicast/reserved), pins the
approved IPv4 address, preserves TLS certificate hostname checking and rejects redirects.
Public NetBox HTTPS hosts are permitted by that explicit destination choice. IPv6-only
NetBox endpoints are not supported by the current egress policy. Proxy environment
variables are ignored. Provider Test Connection keeps its existing independent policy.
The child has a 45-second wall budget, per-request timeouts, and a 2 MiB response limit.

## Durable truth and recovery

There is no new DB migration or DB role. A single atomic root-owned 0600 document,
`/opt/netbox-sync/secrets/netbox/bootstrap.json`, holds format/revision/state, URL,
separate tokens and safe prerequisite evidence. Its directory is root-owned 0700.
An advisory lock, exclusive temporary file, file fsync, atomic replace and directory
fsync prevent partial writes. The public projection never contains either token.

`FRESH -> CONFIGURED -> VALIDATING -> VALIDATED -> READY` is the successful path.
Validation failure or an abandoned validation becomes `ATTENTION`. Saving replacement
credentials increments revision and returns to CONFIGURED. Every mutating request carries
an expected revision. Concurrent/stale saves fail without overwriting the winning save;
there is no automatic POST retry. Duplicate Finish returns the same READY state.
Each validation has an attempt ID: an older result cannot complete a later attempt even
at the same configuration revision. Malformed/partial success evidence fails closed.

Closing a browser or restarting the API does not discard accepted work. Reload reads
server truth. If validation loses its process, a status read after 60 seconds marks it
interrupted and permits a new explicit test. A network-lost save/Finish acknowledgement
must be resolved by Reload before another operator action. READY survives ordinary
restart; it records setup validation, not continuous NetBox availability. The health
endpoint reports configuration readiness separately from live connectivity evidence.

## Privilege boundary

| Process | Authority and mounts | Network |
| --- | --- | --- |
| API, UID 10001 | Existing read/registration roles; control sockets read-only; no NetBox/source secret files | Existing DB/Web bridges |
| Secret broker, UID 0 | Local source-file create/rollback and owned-file cleanup; no DSN or apply-lock mount | Literal `network_mode: none` |
| Lifecycle worker, UID 0 | Existing lifecycle_writer only; source gates/tombstones; broker socket and shared apply lock; no provider/NetBox files | Internal DB bridge only by default |
| Bootstrap worker, UID 0 | Only NetBox state, its own socket and shared apply lock; no DB roles or provider files | Egress bridge for validation |
| Validation child, UID 10001 | Explicit stdin payload, no inherited DSNs; no root-file access | Bounded GET/OPTIONS probe |
| Discovery/apply supervisors | Existing privileges; read selected bootstrap token immediately before child execution | Existing DB/egress bridges |

No service gains Docker socket, systemd control or API migration ownership. Socket
parents are root-protected; SO_PEERCRED admits only the API UID to control operations.
Broker `remove_owned` admits only the lifecycle root peer; the API cannot call it.
The lifecycle worker selects keys only after DB source/reference/operation checks.
Filesystem proof remains in the broker (root owner, restrictive mode, inode/xattrs).
Absent files are idempotent success; every remaining file still requires proof.
Source removal retains tombstones, source identity, Run History and NetBox objects.
Shared or ambiguous credentials remain retained. No provider tokens are revoked.

`broker.env` is retained as the existing protected configuration filename to avoid
rewriting deployment/backup manifests; only the lifecycle worker consumes it now.
The broker consumes no env_file. Bundled production lifecycle has only the internal DB
network. Explicit external-PostgreSQL overlay needs DB reachability on its egress bridge;
that exception never applies to the broker. Development Compose uses its named external
DB network and is not evidence of production network containment.

## Backup and restore

Backup Format v1 already includes the protected `secrets/netbox` directory; bootstrap
truth and credentials therefore travel together with verified file metadata. Backup
quiescence includes both new control services. Restore preserves saved READY truth and
clears interrupted UI-6 plan/operation context under the existing policy. Revalidate the
restored NetBox connection before operator use; a restored VALIDATING state becomes
interrupted on its next expired status read. Browser/server caches are not state.
Older bundles are extended only in validated staging with the new control socket and
runtime state-file settings; without bootstrap.json they enter FRESH and require browser
configuration. No existing token/env value is treated as proof of readiness.

## Disposable clean-VM acceptance (pending manual execution)

Record release/HEAD and evidence for each item. This checklist authorizes no VM wipe,
production action or provider write during repository development.

1. Confirm a clean supported Debian VM and host prerequisites.
2. Install the reviewed current release with the canonical installer.
3. Verify canonical releases/current/config/secrets/backups/state/runtime paths and modes.
4. Verify bundled PostgreSQL health and no published DB port.
5. Verify migration head `0005_source_tombstones`.
6. Verify database/schema `netbox_sync` and canonical separated roles/grants.
7. Verify service/timer units and zero-source scheduler success.
8. Open a direct application URL in two browsers; both show first-run.
9. Exercise unreachable NetBox, invalid TLS and wrong token; no READY or leaked secrets.
10. Validate the intended NetBox with reviewed read/apply token privileges.
11. Inspect GET/error/history/log/storage surfaces for token leakage; review file modes.
12. Check missing/incompatible/partially prepared custom fields and retry safely.
13. Finish twice; verify one durable READY outcome.
14. Verify zero-source Overview and Sources with no fabricated history/health evidence.
15. Restart API/workers and reboot; verify configured and READY states persist.
16. Add one Proxmox source through Add Source with sync initially off.
17. Add one ESXi source through Add Source with sync initially off.
18. Verify distinct source credential references and isolation.
19. Build a Plan; verify durable operation identity and current generation.
20. Repeat Discovery while active; verify deduplication.
21. Observe the same operation from two browser contexts.
22. Close the originating tab; reopen and recover operation evidence.
23. On an explicitly authorized test scope, verify stale/single-use confirmation and
    shared-lock Apply behavior before any test write.
24. Verify Remove Source blocks active/uncertain work and requires exact identity.
25. Verify tombstone persistence and rejection of re-registration of that Source ID.
26. Verify Run History and NetBox objects remain; review exclusive/shared local cleanup.
27. Create a backup on this NEW canonical deployment using the backup runbook.
28. Verify backup checksums, metadata, credential coverage and PostgreSQL tooling.
29. Rehearse restore only into another empty disposable target; verify Bootstrap,
    retained history, invalidated plans and explicit revalidation readiness.
