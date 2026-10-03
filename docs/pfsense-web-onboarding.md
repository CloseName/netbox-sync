# pfSense web onboarding (test rollout)

Sources expands to ESXi, Proxmox and pfSense, including zero counts. Hypervisor counts are registered sources; pfSense counts are NetBox VMs whose names contain `pfsense` case-insensitively. Counts show unavailable rather than zero on fetch errors. NetBox custom fields and other object types are not candidates. VM ID, cluster and site disambiguate equal names. Names discover candidates only: configured interfaces must match by MAC before snapshots are saved.

The initial automated setup supports CE 2.7.2-RELEASE only. SSH must already be enabled. The operator enters the pfSense HTTPS endpoint and an administrative LDAP or local account accepted by its webConfigurator. Authentication follows that appliance's configured authentication backend; Sync does not bypass LDAP or impersonate users. Diagnostics: Command permission is required. Other versions stop before provisioning.

The administrative password is forwarded in memory to a bounded unprivileged child and is not persisted. The worker stores a per-VM Ed25519 private key in the root-only NetBox secret directory under `pfsense/<vm-id>.json`; include this directory in protected backups. API responses expose only safe status fields. TLS verification defaults on and uses source CA trust; explicit disabling is per connection. The SSH host key is obtained through this administrative HTTPS session and subsequently pinned. HTTP redirects are not followed. Destination policy and authenticated permissions are enforced for setup and subsequent collection.

The service account is `nb-sync-<vm-id>`, separate from the existing manual `netbox-sync` account. It receives only `user-shell-access`, a random undisclosed password and a restricted forced-command public key. It is not an administrator. The bundled collectors are installed root-owned under `/conf/netbox-sync-web/<account>/`. No package download occurs on pfSense. Other accounts are not changed. A same-name account without our per-VM ownership marker is refused. Retrying setup reuses the persisted key, including after an uncertain result; never delete the protected key state to resolve an error.

Setup verifies MAC identity before provisioning, then verifies SSH collection and imports both network and inventory snapshots through a narrow Guard API. Guard revalidates current VM interfaces under a transaction. It does not create IPs, prefixes, rename interfaces or change Firewall/VPN/service configuration. `Collect now` reuses the key without administrator credentials. Existing manual IPAM assignments remain intact. Periodic scheduling is not enabled by this rollout.

A failed operation may have created the account before collection/import failed. The UI reports attention, not success; retry setup with the same endpoint/key to reconcile. A worker interruption can leave RUNNING temporarily; after 130 seconds status becomes outcome unknown. Existing snapshots remain intact on rejected imports. Provisioning is not a distributed rollback transaction: never automatically delete an account after a network timeout.

Local validation covers GUI response parsing, pre-write version/MAC checks, key-change refusal, credential redaction, candidate projection, route permissions and browser interaction using mocked APIs. Actual LDAP login, pfSense account creation and Guard database writes require the test-server run. Do not claim successful live onboarding until the server reports Connected and the NetBox snapshot timestamp advances.

## Test deployment

Run `deploy/pfsense/activate-test-onboarding.sh <full commit>` on netbox-test. It updates Guard with the existing tested deployment flow, then upgrades Sync using its standard installer with `--no-systemd`. The timer remains stopped.

Open Sources > pfSense, choose VM 2609 in PVE-INFRA-TEST, address 10.24.0.1 and the actual HTTPS port. Enter an administrator accepted by pfSense; check certificate trust or explicitly choose the test connection's TLS setting. Press Set up and collect. Verify Connected, then Collect now and the fresh NetBox timestamp. Keep the old manual account until this succeeds. A recreation test should remove only the new `nb-sync-2609` account via pfSense after successful verification, preserve Sync's key state, and rerun setup. This test has not been performed locally.

Implementation references: pfSense RELENG_2_7_2 `src/usr/local/www/diag_command.php`, `system_usermanager.php` and `src/etc/inc/auth.inc` in the official pfsense/pfsense repository.
