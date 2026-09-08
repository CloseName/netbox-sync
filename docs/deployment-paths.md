# Operator-selected deployment roots and TLS directories

Test example: `--root /netbox-sync-test` is a supported clean-install root, including systemd,
scheduler, backup/restore and both ingress modes. It is an operator choice, never a
universal product name. The [runbook](clean-install-tls-runbook.md) explicitly sets:

```sh
ROOT=/netbox-sync-test
TLS_DIR=/etc/netbox-sync-test/cert
```

All releases/current/config/secrets/backups/state/ingress paths derive from `ROOT`.
The external upstream becomes `$ROOT/ingress/upstream.sock`, with its existing
10001:10001 0750 parent directory and bounded Unix-peer trust. Runtime container paths
are stable mount destinations, not host deployment-root assumptions.

## Root validation, upgrade and globals

Roots must be dedicated absolute paths. POSIX components permit letters, digits,
underscore, dot and hyphen, with no whitespace, shell/systemd metacharacters, `..` or
symlink traversal. Shared system directories such as `/`, `/etc`, `/run` and `/opt`
are rejected as the deployment root itself. `/netbox-sync-test` and nested dedicated
roots are supported. This validation lets systemd paths be rendered without unsafe
shell substitution. No existing directory tree is moved or renamed by installation.

The checkout fallback default `/opt/netbox-sync` is retained as the generic product default;
explicit root use has no dependency on it. Installed installer/Compose/backup tools
infer their root from the physical `<root>/releases/<id>` layout when `--root` is
omitted. For upgrades from a new checkout always pass `--root "$ROOT"` explicitly.
An existing systemd unit belonging to a different root blocks installation instead
of being silently overwritten. Changing a deployed root is a separately planned
move/restore, not an implicit upgrade.

One active NetBox Sync deployment per host remains the supported contract. These
product-scoped resources intentionally remain global:

- `/run/netbox-sync/apply.lock`: the same lock for installer, backup, scheduler,
  manual apply and lifecycle/bootstrap coordination, for every selected root.
- `/etc/systemd/system/netbox-sync.service` and `netbox-sync.timer`: rendered with
  the selected root, preserved service names, 60-second timer, single host flock.
- Compose project `netbox-sync`, its private networks, socket volumes and bundled
  PostgreSQL volume/database/schema names. Root selection does not create a second
  independent scheduler or database namespace.

The rendered unit sets WorkingDirectory, ExecStart and NETBOX_SYNC_ROOT to the
selected root. `/run/netbox-sync` is recreated by the wrapper after reboot; the
persistent ingress directory remains below ROOT and nginx recreates its socket.
Containers still have no systemd or Docker control. Historical naming conversion
keeps its explicit old-to-new name mapping and is not run for a clean installation.
The historical full-sync script now requires an explicit legacy checkout path;
it has no implicit `/opt` checkout or role in the canonical installer.

## Public TLS ownership

Fresh standalone CLI installs default to `$ROOT/secrets/tls` with `fullchain.pem`
and `privkey.pem`. Explicit `--tls-dir <absolute-path>` selects the optional
`ssl.crt`, `ssl.key`, `dhparam.pem` contract. No DNS-based path inference occurs.
The following corporate paths are test examples only:

```text
/etc/netbox-sync-test/cert/ssl.crt
/etc/netbox-sync-test/cert/ssl.key
/etc/netbox-sync-test/cert/dhparam.pem
```

Directory: root:10001 0750. All three files: root:10001 0640, regular, single-link,
no symlinks. `ssl.crt` is the leaf-first complete chain, `ssl.key` its unencrypted
matching key. `dhparam.pem` contains valid PEM DH parameters accepted by the platform
security policy (use at least 2048 bits). The operator supplies all material; the
installer generates neither certificates nor DH parameters. nginx mounts only this
directory read-only, at `/run/netbox-sync-tls`. The corporate template references
these exact filenames. Preflight checks key match, hostname, expiry, DH validity,
file metadata and optional NetBox CA before DB preparation.

`--init-tls-layout --root "$ROOT" --tls-dir "$TLS_DIR" --ingress-mode standalone`
creates directories only. External mode creates only application-local layout/CA
directories and never requires or mounts duplicate public TLS material. Its outer
ingress owns the public certificates and `/etc` configuration outside this product.
NetBox's `/netbox-test` and `/etc/netbox-test/cert` likewise remain entirely external.

Existing installations retain their saved TLS directory/layout when flags are
omitted. Older `secrets/tls/fullchain.pem` + `privkey.pem` installations continue using
the legacy template without a DH-file requirement. Explicit `--tls-dir` selects the
corporate filename contract; supply all three files before that deliberate transition.
Unknown layouts fail closed. Certificate files are never overwritten by the installer.

NetBox's additional CA remains `$ROOT/secrets/ca/netbox-ca.pem`, root:root 0644,
mounted read-only only into existing outbound clients. Its strict verification,
absence/invalid-file behavior and source isolation are unchanged.

## Backup and restore

Application state is backed up from the selected ROOT; fresh restore validates the
bounded target current/release layout and preserves target-local config/mount paths.
External corporate certificates under `/etc` are operator-owned and excluded from
application backup. Back them up separately under the organization's key policy.
Before standalone restore prepare and validate the target TLS directory; restore
verifies those files and never writes a key to `/etc` or replaces them from a bundle.
External-ingress restore needs no public key. Target TLS selection/ingress mode are
preserved while restored NetBox CA is validated. Legacy in-root TLS bundles remain
supported by the existing format. No source/tombstone/history semantics change.

The product lock and systemd maintenance rules apply equally to non-default roots;
there is no alternate `$ROOT/run/apply.lock`. Global service names mean restoring a
second active deployment alongside an existing one is unsupported.

## Deployment identity and restore target

Test and production use the same application release with different deployment configuration.
Generic checkout default: `/opt/netbox-sync`. Operator choices include `/srv/example-sync`;
no corporate hostname, NetBox URL or certificate directory is a runtime default.

New v1 manifests contain validated `deployment_identity`: source root, public URL,
ingress mode, TLS directory and filename layout. Older v1 manifests remain readable.
Recorded paths are descriptive metadata, never destinations to create or commands to run.
Restore always requires an explicit `--root`, including `--check` and installed entrypoints:

```sh
sudo python3 deploy/backup.py --root "$ROOT" restore "$BUNDLE" --check
sudo python3 deploy/backup.py --root "$ROOT" restore "$BUNDLE"
```

An explicitly selected different root is supported for relocation into a prepared empty
target. Target mount paths and target ingress/TLS settings win; public URL mismatch
still fails. No automatic fallback from a custom-root backup to the generic root exists.
