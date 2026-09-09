# Product onboarding verification and upgrade procedure

Date: 2026-09-09. Base commit: `6639c38b7b9fcf535624e06ecf91fa0ac7db3d6b`.
All execution was local, isolated testing. No push, deployment, live VM connection,
provider mutation or modification of unrelated containers/volumes was performed.

## Evidence

- Docker Desktop 4.89.0; Linux Engine 29.7.2; Compose 5.5.0.
- Full Linux backend with disposable PostgreSQL 16: **871 passed, 12 skipped**.
- Final combined production Docker smoke: **7 passed** (110.54 seconds).
- Separate marked legacy PostgreSQL naming migration: **1 passed**.
- Host Docker/Compose and bundled backup group: **47 passed, 4 Windows skips**;
  those four POSIX/permissions checks passed in the Linux suite.
- Fresh/naming and installer regressions after TCP readiness fix: **40 passed,
  3 Windows skips**, covered on Linux.
- Frontend unit **48 passed**; full Playwright **137 passed**. Latest setup styling
  was rechecked with **7 passed**; TypeScript and Vite build passed.
- Standalone and external Compose validation and `git diff --check` passed.

The twelve full-suite skips are execution-location decisions, not twelve unchecked
features: seven Docker smoke cases execute on the host (no Docker socket is mounted in
the Linux runner); three Compose CLI cases execute on the host; one naming migration
uses its own marked legacy cluster. Only the live ESXi test remains deliberately unrun:
no live credentials or VM access were authorized. No ordinary Linux lock/mode/Unix-peer
checks remain skipped. Test fixtures do not establish real NetBox object-level rights.

The seven opt-in Docker cases cover:

1. Standalone HTTPS through the production proxy, API and bootstrap worker.
2. Corporate TLS layout through those same production services.
3. External Unix ingress through those same services and an ephemeral test-only outer TLS proxy.
4. External production proxy with exact tmpfs/read-only/cap-drop/network configuration.
5. Old Compose-generated PostgreSQL name to explicit name: same volume, unchanged
   password file, authenticated TCP access, retained SQL marker, exactly one DB container.
6. Fresh production stack: all nine persistent services, installer-generated role-separated
   config, real roles/migrations/grants/http-init, FRESH Bootstrap, API health, no published
   backend/DB/worker ports, literal networkless broker, shared lock volume. A separately
   created foreign-owner container blocks name preflight and remains unchanged.
7. Bundled custom-format database dump/restore transport.

Application services in TLS smoke now use `compose.production.yml` plus the actual
external override when selected. Fixture overrides supply disposable Linux filesystems,
CA/certificate files, generated test configuration and loopback ephemeral frontend ports.
They do not replace tmpfs, users, capabilities, commands, read-only flags or network
isolation. The separately managed outer-ingress and mock NetBox are test fixtures only.

Real HTTP bootstrap smoke begins with no fields, reviews all 16, starts a confirmed
operation, rejects another caller while RUNNING, receives a lost POST response after a
partial write, restarts bootstrap, reconciles the durable field, then creates the remainder.
It checks confirmed token revocation in standalone/corporate and denied/unconfirmed
revocation in external mode, no setup secret in state/logs, independent validation and
Finish. Unit/transport tests additionally cover expired plans, incompatible fields,
provisioning, invalid authority, exact supplied-token identity, cancellation, stale
revisions, process transport and interrupted execution recovery.

## Defects found by runtime verification

- The new naming fixture initially omitted the required external ingress directory.
- Existing TLS smoke assumptions did not account for production `restart: unless-stopped`
  and the new explicit proxy name. Fixtures now check actual certificate rejection and
  unavailable health, and give the outer test proxy a separate name.
- PostgreSQL readiness could observe the temporary init Unix socket before the final TCP
  listener existed. Installer and Compose now check `127.0.0.1` explicitly. No new host
  port is published. The rename test exposed this race and now tests authenticated TCP.
- The retain-only AST guard previously prohibited even explicit setup-token revocation.
  Its exception now admits exactly one fixed executor call; independent tests reject
  mismatched identities and prove no synced-object or runtime-token deletion.

## Upgrade after architecture review and publication

This procedure targets the already installed product, with an existing managed `current`
symlink and protected configuration. It is not permission to execute it during development.
Container recreation entails an application interruption; use an operator maintenance window.
No naming migration is required for a canonical `netbox-sync` installation.

1. Inspect metadata before changing anything:

   ```sh
   ROOT=/netbox-sync-test
   readlink -f "$ROOT/current"
   git -C "$ROOT/repo" status --short
   git -C "$ROOT/repo" rev-parse HEAD
   docker ps -a --filter label=com.docker.compose.project=netbox-sync --format '{{.ID}} {{.Names}} {{.Status}}'
   systemctl is-active netbox-sync.timer
   systemctl is-enabled netbox-sync.timer
   ```

   Identify the PostgreSQL container by its Compose **project and service labels**,
   not by guessing its old name. Record its volume name at `/var/lib/postgresql/data`.
   Check protected config/password-file existence and permissions with `stat`; never
   print their contents. Stop if current/config/project ownership or the expected volume
   is ambiguous, credentials are missing, or an unrelated container owns a canonical name.
   The installer can generate missing password files; that is not a safe repair for an
   existing DB. Resolve missing-credential metadata before invoking it.

2. Produce and verify a backup using the existing [backup/restore procedure](backup-restore.md).
   Preserve existing bootstrap state, generated role credentials, custom NetBox CA and
   ingress directory ownership. Do not initialize another root or remove any volume.

3. Checkout the reviewed, published release in the existing repo. Set `RELEASE` to its
   exact approved commit and verify that the clean checkout HEAD equals it. Then run:

   ```sh
   sudo python3 "$ROOT/repo/deploy/install.py" --root "$ROOT" --ingress-mode external --check
   sudo python3 "$ROOT/repo/deploy/install.py" --root "$ROOT" --ingress-mode external --check-tls
   sudo python3 "$ROOT/repo/deploy/install.py" \
     --root "$ROOT" --source "$ROOT/repo" --release-id "$RELEASE" \
     --public-url https://netbox-sync-test.indeed-id.hq --ingress-mode external
   ```

   Do not use `--prepare-only`, `--no-start` or `--no-systemd` for this complete existing
   systemd-managed upgrade. The installer preserves existing credentials/config, stops
   the timer, acquires the shared apply lock, prepares the stack, activates current/config,
   starts services and enables the timer after success. Compose recreates the same services
   with new container names while retaining their project/network/volume identities.
   The external socket remains `$ROOT/ingress/upstream.sock`; outer ingress owns public TLS.

4. Verify nine running canonical containers, unchanged PostgreSQL volume and healthy API,
   new `current` release, timer enabled/active and HTTPS onboarding through shared ingress.
   Saved read/apply credentials should remain saved. Review/create missing fields with
   a separate short-lived setup token; verify its revocation status, revalidate and Finish.
   Source onboarding remains separate and starts with synchronization disabled.

Stop on any installer failure. Activation failure can restore current/config and quiesce
runtime; it does not prove the timer or all containers resumed. Inspect current/config,
container states, volume identity and timer metadata before a reviewed continuation.
Do not blindly re-run an immutable release ID or regenerate passwords. The component
upgrade was exercised with real Compose; live Debian systemd/reboot and real NetBox 4.7
acceptance remain operator steps, not claims made by these tests.
