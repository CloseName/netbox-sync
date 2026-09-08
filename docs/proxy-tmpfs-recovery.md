# Proxy tmpfs deployment failure: evidence and conditional recovery

Base release: `a65fa3a640da43ed5589bb078ee9ae42f3bc8d50`.
This is a reviewed repository procedure, not evidence about the live VM. No server
inventory or recovery was performed. Company paths below are test examples only.

## Cause and regression coverage

The flow sequence `tmpfs: [/tmp:size=64m,mode=1777]` parses as two mounts:
`/tmp:size=64m` and `mode=1777`. Compose config accepted this representation; the
Docker Engine rejected container creation because the second target is relative.
Both standalone and external merged models reproduced the defect. The production
external Compose smoke reproduced the exact Engine error before the fix.

A quoted block-list item now preserves one `/tmp:size=64m,mode=1777` mount.
All six tracked Compose files were audited; no other comma-split tmpfs occurred.
The existing x-app block item is valid YAML, and legacy Web mounts have no options.
No tmpfs size/mode, read-only filesystem, capabilities, network or credential
boundary changed.

Previous TLS smokes assembled containers with `docker run --tmpfs /tmp`; they
exercised nginx/Unix/TLS behavior but bypassed the production Compose tmpfs field.
Existing merged-model tests checked ports/networks, not tmpfs. New assertions check
both models and every service's tmpfs target. The new opt-in test uses production
Compose and the real external override. Its only fixture is an isolated named
volume for the operator ingress directory; it does not override any service field.
It verifies Engine tmpfs settings, mode 1777, read-only/cap-drop/network isolation,
the real nginx health endpoint and upstream socket. This proxy-startup smoke is
not a full application/database/onboarding rehearsal.

## What failure handling actually does

`prepare_layout` copies the immutable release and merges configuration into a
`state/prepare-*/config` directory. `ensure_secret` reuses existing password files;
it generates a new password if a file is missing. This is why missing credentials
on an already initialized database are a stop condition, not a reason to retry.

`prepare_stack` validates Compose, builds, starts PostgreSQL, bootstraps roles,
runs migrations and grants before activation. None of these DB changes are rolled
back by an activation failure. Role provisioning reapplies passwords from existing
files and grants; it is not a no-op, even when values remain unchanged.

`activate_prepared` publishes config, switches current, writes systemd units,
then starts http-init and runtime. On failure after runtime was attempted:

- It best-effort stops API, apply, schedule, lifecycle and bootstrap workers.
  This does not guarantee all containers stopped; proxy, discovery and broker are
  not in that stop list, and stopping itself can fail.
- It restores the previous current link, or removes it for a fresh installation.
- It restores pre-activation canonical config bytes. Files absent before the first
  attempt are removed. It does not preserve newly generated config as active config.
- The outer finally removes staged preparation config. Release code, infrastructure
  password files, PostgreSQL container/volume and applied migrations remain.
- Written systemd units are not rolled back. Timer enable/start is after successful
  activation and was not reached in this reported failure. A pre-existing timer's
  state cannot be inferred: main only stops it when current existed at entry.

Abrupt interruption or a failure during rollback may leave a different state.
Do not infer current/config/timer state from the final error message alone.

## Required metadata inventory before authorizing retry

Collect only the following through a separately authorized server step. Do not
print env contents, full docker inspect, command environments, secrets, private
keys, DB DSNs, password hashes or unrestricted logs.

1. Checkout `/netbox-sync-test/repo`: branch, commit and git status; ensure it is
   the intended source, not current or an immutable release directory.
2. Root/repo/releases/current/config/state/ingress path existence, type, owner,
   mode and symlink destinations. List release IDs and preparation-directory names.
   Report whether current is absent or points to a valid managed release.
3. Canonical config filenames, types/owners/modes/sizes only (all seven expected),
   plus whether any operator custom configuration existed before the failed attempt.
   Do not assume absent config can reconstruct previously supplied custom values.
4. Every infrastructure password filename expected by `deploy.install.PASSWORD_NAMES`,
   existence, regular-file/non-symlink status, numeric owner/mode and nonzero size.
   Require the original files, root-owned 0600. Never regenerate missing files.
5. Product container names, image IDs, Compose project/service labels, running/exit/
   health status and restart counts. For PostgreSQL, only mounted volume name and
   destination, and password-file mount source path. Confirm the existing volume
   is the intended `netbox-sync-postgres-data`, not a new/empty replacement.
6. Database connectivity via the approved admin path; database/schema names,
   migration revision (expected `0005_source_tombstones`) and aggregate source,
   run, operation/tombstone counts. No row contents. Unexpected activity or loss
   of authentication requires investigation before another provisioning attempt.
7. Systemd unit existence and only root-bearing WorkingDirectory/ExecStart fields;
   service/timer active, enabled and substate. Check for an active scheduled/manual
   operation and shared-lock ownership without killing a lock holder.

Proceed only after confirming preserved credentials/volume, coherent root/config,
no uncertain or active write operation, and an inactive timer. If residual workers
are running, plan a separately authorized quiescence using the verified deployment
identity before retrying. Do not improvise Compose commands when current/config is
absent. Ambiguous rollback, incomplete secrets/config, unexpected data, another
root's unit, or a busy lock are stop conditions.

## Conditional continuation with the corrected release

After inventory approval and separate publication/transfer of the focused fix:

- Preserve the existing root, secrets, database volume and old release. No cleanup,
  naming migration, restore, credential rotation or manual env fabrication is needed.
- Update the reviewed checkout at `/netbox-sync-test/repo` to the exact new commit
  without discarding local work. Verify a clean checkout and exact commit.
- Use a NEW release ID equal to the corrected full commit. The installer rejects
  different content under the old ID; never edit the packaged old release in place.
- If original active config was present, the installer merges its operator settings.
  If this was a fresh default installation and rollback removed all generated config,
  it regenerates it from preserved password files and the explicit parameters below.
  Nondefault configuration lost by rollback must be recovered/reviewed first.

Only after those gates, the supported command is:

```sh
ROOT=/netbox-sync-test
: "${FIXED_COMMIT:?Set the reviewed and available full corrected commit}"
cd "$ROOT/repo"
test "$(git rev-parse HEAD)" = "$FIXED_COMMIT"
test -z "$(git status --porcelain)"
sudo python3 deploy/install.py --root "$ROOT" --source "$ROOT/repo" \
  --release-id "$FIXED_COMMIT" \
  --public-url https://netbox-sync-test.indeed-id.hq --ingress-mode external
```

Use normal installation: `--prepare-only` does not fix activation; `--no-start`
would leave runtime untested; `--no-systemd` bypasses the intended host lifecycle.
The normal path reacquires the shared apply lock, uses the same project/volume and
password files, reapplies roles/migrations/grants, publishes corrected config/current,
starts runtime and enables the timer only after readiness. No public TLS duplicate
is required. The same-root systemd unit can be rewritten safely by this path.

Afterwards verify current points at the corrected release, runtime/API/proxy health,
external socket, no published Sync ports, unchanged database volume identity and
expected timer state. Any failure is another stop-and-inventory event, not permission
to loop retries. This procedure remains conditional until the live metadata has
been reviewed; this repository change alone cannot certify safe server recovery.

## Local verification result

Docker Engine 29.7.2 / Compose 5.5.0 reproduced the same reported creation error
(the live report used Compose 5.3.1). After correction, the production external
proxy smoke passed. Affected regressions: 69 passed, 5 platform/integration skips;
plus the passing Engine smoke. Both merged-model assertions ran on the host.
The fresh activation failure/retry tests exercise real local file/config operations
with runtime/systemd calls intercepted, for both absent and existing original config.
They confirm rollback, retained password bytes, retained old release, same volume
selection and successful new-ID activation. They do not prove live DB credentials
or runtime state, which remain inventory gates. Git whitespace checks passed.
