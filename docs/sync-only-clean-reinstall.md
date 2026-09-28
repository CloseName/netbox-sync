# Disposable test VM: reinstall Sync only

**Local isolated reinstall gate passed on 28 September 2026.** See
[executed evidence and limits](product-lifecycle-20260927-progress.md). No live
operations have been performed. Host execution remains a separate operator action. This disposable test task explicitly forbids backups, dumps and
restore-test containers. That exception does not change production backup policy.

Keep the external NetBox installation, `/netbox-test`, its PostgreSQL, Redis,
`netbox-worker`, volumes and configuration intact. Keep `/etc/netbox-test` and
`/etc/netbox-sync-test`, operator certificates, shared ingress and its port 80/443
ownership intact. Never use `docker system prune`, wildcard deletion or a list
of all Docker containers as a removal target.

## Before any shutdown

Use a reviewed exact release from a checkout **outside** the application root;
`/netbox-sync-test/repo` will not survive a complete root reset. Set:

```sh
ROOT=/netbox-sync-test
CHECKOUT=/root/netbox-sync-reinstall
RELEASE=<reviewed-full-commit-SHA>
```

Fetch/checkout that exact reviewed commit in CHECKOUT before continuing. Do not
copy previous env files or credentials into a clean installation. Run only the
read-only inventory first:

```sh
sudo python3 "$CHECKOUT/deploy/reinstall_inventory.py" --root "$ROOT"
sudo readlink -f "$ROOT/current"
sudo systemctl show netbox-sync.service netbox-sync.timer \
  --property=Id,FragmentPath,ActiveState,SubState,UnitFileState
sudo systemctl cat netbox-sync.service netbox-sync.timer
```

The helper reports exact container IDs, project labels, volume names, network
names and mount paths, never environment values or secret contents. Any blocker
is a stop condition. Inspect systemd locally: it must refer to this ROOT and the
canonical scheduled wrapper; do not publish custom unit contents if an operator
has embedded secrets. Check every bind source. Paths outside ROOT are retained
unless individually proved disposable and exclusively Sync-owned. The global
`/run/netbox-sync` is the product shared lock directory, not persistent data;
no second Sync installation or foreign container may use it.

The bundled DB is `netbox-sync-postgres` (Compose service `postgres`). The external
NetBox DB is `netbox-postgres`: never remove or stop it. A separately configured
external Sync PostgreSQL requires a separately reviewed database reset; this
bundled-only procedure refuses it.

Historical stopped `netbox-guard-check-*`, `netbox-guard-physical-*`,
`netbox-guard-restore-*` and `netbox-guard-plugin-check-*` names are **not ownership
proof**. Inventory them individually; leave them untouched if exact task labels,
mounts and current consumers cannot establish safe disposal. They are not product
components and not required for the new installation.

## External NetBox compatibility is a prerequisite

A clean Sync DB does not remove any NetBox infrastructure. Before proceeding,
review retained objects and creation ownership using the current supported UI.
Do not silently adopt a cluster by name or clear ownership tags. If unproved or
shared dependencies block retirement, stop that source's onboarding and show the
specific ownership conflict. A new installation namespace cannot inherit old
sources merely because DNS/UUID/name matches.

This release requires Guard capabilities `source_namespace_state` and
`idempotent_creation`. Its deployment
is a **separate NetBox operator change**, outside this task. Existing Guard identity,
external audit and closed-source seals must remain. See
[once-only integration permissions](guard-installation-permissions.md). Do not
reset GuardIdentity, disable verification, grant superuser, or edit receipts.

## Controlled Sync reset (operator action, not executed here)

1. Disable/stop only `netbox-sync.timer`. Wait for `netbox-sync.service` to become
   inactive and for current Sync operations to reach a definite terminal result.
   An uncertain application result is a stop condition, not permission to erase
   its evidence. Do not force-stop an in-flight NetBox write to accelerate reset.
2. Re-run the metadata inventory after stopping scheduling. Require the same
   project, ownership and mount boundaries; any newly discovered consumer stops
   reset. Verify no source operation is running.
3. Use the old root's supported Compose wrapper to stop/remove its own services
   and project-owned volumes, including optional legacy workers:

   ```sh
   sudo systemctl disable --now netbox-sync.timer
   sudo python3 "$ROOT/current/deploy/compose.py" --root "$ROOT" \
     --profile legacy-workers down --volumes
   ```

   This command is authorized only after inventory proves every listed volume
   and network has no non-Sync consumers. Do not add `--remove-orphans` or remove
   external volumes by name. Stop on failure; inspect exact remaining resources.
4. Remove the old application root only after checking its resolved absolute path
   is exactly `/netbox-sync-test`, is not a symlink/mountpoint, has no nested mounts,
   and no remaining container references it. Keep CHECKOUT outside that root.
   Use an explicit operator-reviewed filesystem command for that exact directory;
   this runbook does not provide a reusable broad recursive-delete shortcut.
   Do not remove `/etc` certificates or `/netbox-test`. Old product systemd unit
   files can remain inactive: the installer verifies their root and replaces them.
5. Confirm the old Sync DB volume and source/config/state/credential files are
   absent. External NetBox container IDs, volume IDs and health must be unchanged.
   Metadata comparison is sufficient; do not create a DB dump.

## New installation

For this shared-ingress rehearsal, the outer operator ingress retains TLS files
under `/etc/netbox-sync-test/cert/`; Sync requires no duplicate public certificate.
Use the verified external Guard installation UUID, obtained through the reviewed
integration setup; it is an identity, not a secret. Never guess it.

Prepare the installer-owned layout first. If NetBox uses a corporate issuer,
set NETBOX_CA_SOURCE to the operator-provided public PEM CA bundle (not a server
private key). A clean root intentionally does not retain the old application CA
file; provide trust explicitly again. Do not disable certificate verification.

```sh
sudo python3 "$CHECKOUT/deploy/install.py" --root "$ROOT" \
  --init-tls-layout --ingress-mode external
if [ -n "${NETBOX_CA_SOURCE:-}" ]; then
  sudo install -o 0 -g 0 -m 0644 -- "$NETBOX_CA_SOURCE" "$ROOT/secrets/ca/netbox-ca.pem"
fi
sudo python3 "$CHECKOUT/deploy/install.py" --root "$ROOT" \
  --check-tls --ingress-mode external \
  --public-url https://netbox-sync-test.indeed-id.hq
```

Stop if layout/CA validation fails. Then use the complete installer path, without
prepare-only/no-start/no-systemd; the host timer and runtime must be installed.

```sh
sudo python3 "$CHECKOUT/deploy/install.py" \
  --root "$ROOT" --source "$CHECKOUT" --release-id "$RELEASE" \
  --public-url https://netbox-sync-test.indeed-id.hq \
  --ingress-mode external --netbox-guard-instance "$GUARD_INSTANCE"
```

The installer generates credentials/configuration and a new installation
namespace. It owns canonical layout `releases/current/config/secrets/backups/state/
ingress` under ROOT. An empty backups directory is layout only; no backup is run.
Private upstream is `$ROOT/ingress/upstream.sock`; confirm the existing outer
ingress can access the new socket through its intended group boundary. Do not
publish Uvicorn or DB ports. `/run/netbox-sync` remains the single global product
lock across manual and scheduled writes.

Expected permanent containers: proxy, API, auth, probe, secret broker, lifecycle,
schedule, bundled PostgreSQL, supervised sync bundle (`apply-worker`), supervised
NetBox bundle (`bootstrap-worker`): **10**. Discovery and retirement are supervised
processes inside their corresponding existing trust boundaries, with private
sockets and bounded shutdown. Legacy service profiles are upgrade compatibility,
not additional permanent containers. Broker is literal `network_mode: none`.

Use `deploy/guard_permissions.py --root "$ROOT"` once to obtain the exact native
NetBox permission definitions for this installation. Preserve ordinary scoped
model permissions. Complete local Admin enrollment and NetBox setup using the
existing clean-install documentation; never place tokens in CLI arguments or logs.
Set NetBox URL to `https://netbox-test.indeed-id.hq`, preserving certificate
verification and the optional operator CA bundle. Open onboarding at
`https://netbox-sync-test.indeed-id.hq`.

## Sequential acceptance

- Zero sources and no stale registration attempts; local emergency Admin works.
- Add one ESXi using its real provider identity; cluster creation and registration
  complete automatically; schedule starts disabled. No per-source permission edit.
- Review/apply a nonempty plan; inspect ownership, inventory and visible network
  observations. Repeat plan has no duplicate creates or updates for unchanged data.
- Enable a schedule and verify one definite run, then disable it before removal.
- Confirm removal once. Close/reopen the page; verify automatic progress and final
  disappearance of source/history/reservations/exclusive credentials. Confirm
  foreign/shared objects and external NetBox audit remain.
- Re-add the same physical server as a new source and verify no old blockers.
- Repeat with Proxmox VM and LXC. Verify the supplied AM duplicate-IP facts remain
  explicit observations where assignments are ambiguous, not silent data loss.
- Test lost responses/restarts only in isolated local fixtures, not by interrupting
  an uncertain live write. No claim of live acceptance until the operator reports it.
