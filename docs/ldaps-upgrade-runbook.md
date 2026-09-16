# Upgrade an existing authenticated installation for LDAPS/RBAC

This is an operator procedure after review/publication, not a deployment performed
by this task. The local rehearsal starts at `5acd4c12d62c62072049b22f98e22d19a980a5af`.
See [architecture and AD acceptance](ldaps-rbac.md) and [local evidence](ldaps-rbac-progress.md).

## Preconditions and backup

Keep a root-capable session and verified local administrator credentials available.
Do not enable LDAP until emergency login works. Review timer/current/container
metadata, without printing environment files or secret values. Stop on unexpected
state. Existing ingress mode, TLS files, selected root and PostgreSQL volume remain.
External PostgreSQL retains its explicit override and existing DSNs.

```sh
set -eu
ROOT=/netbox-sync-test
readlink -f "$ROOT/current"
sudo systemctl is-active netbox-sync.timer
sudo python3 "$ROOT/current/deploy/compose.py" --root "$ROOT" ps
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" preflight
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" create
: "${BUNDLE:?Set exact backup directory reported by create}"
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" verify "$BUNDLE"
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" inspect "$BUNDLE"
```

Use the installed backup tool before activation. A database-only manual dump is not
an equivalent recovery point. Preserve the verified bundle with credential-level
access restrictions and confirm the original service/timer state was restored.

## Select and install the reviewed release

Set RELEASE_COMMIT to the approved published full SHA. Stop on a dirty checkout,
wrong remote, unknown commit or failed ancestry check; do not reset or merge.

```sh
: "${RELEASE_COMMIT:?Set reviewed published full SHA}"
case "$RELEASE_COMMIT" in *[!0-9a-f]*|'') exit 1;; esac
test "${#RELEASE_COMMIT}" -eq 40
test -z "$(git -C "$ROOT/repo" status --porcelain)"
test "$(git -C "$ROOT/repo" remote get-url origin)" = https://github.com/CloseName/netbox-sync.git
git -C "$ROOT/repo" fetch origin
git -C "$ROOT/repo" merge-base --is-ancestor "$RELEASE_COMMIT" origin/main
git -C "$ROOT/repo" switch --detach "$RELEASE_COMMIT"
sudo python3 "$ROOT/repo/deploy/install.py" \
  --root "$ROOT" --source "$ROOT/repo" --release-id "$RELEASE_COMMIT"
```

For the real systemd host, do not add prepare-only, no-start or no-systemd.
Existing public URL/ingress/TLS selections are retained. No repeat enrollment
acknowledgment is needed for this already authenticated base. The installer uses
the existing shared apply lock and activates the prepared release normally.
If it fails, inspect current/config and service/timer metadata before continuing;
do not assume activation or timer recovery completed, and do not recreate volumes.

## Validate and configure

```sh
test "$(basename "$(readlink -f "$ROOT/current")")" = "$RELEASE_COMMIT"
sudo python3 "$ROOT/current/deploy/compose.py" --root "$ROOT" ps
sudo systemctl is-active netbox-sync.timer
sudo stat -c '%a %U:%G %n' "$ROOT/secrets/auth"
```

Expected auth directory: root:root 0700; broker-created bind files: root:root 0600.
Auth-worker reads this mount read-only; broker alone writes it, with network_mode
none. API/DB have neither the LDAP bridge nor bind-secret mount. No LDAP values
need to be inserted into env files. Existing onboarding, sources, schedules,
credentials, history, policies, local identity and DB volume must remain unchanged.

Open the existing HTTPS public URL, sign in locally, then Settings → Authentication
/ LDAP. Supply verified CA/DNs/groups from the directory administrator, check and
save, then test all three roles and the emergency local path. Follow the separate
Microsoft AD acceptance list; isolated OpenLDAP tests do not establish AD acceptance.
Run a reviewed manual sync and a scheduled cycle for each provider on the acceptance
installation only when separately authorized. A manual empty plan is refused;
scheduled no-op remains valid.

## Restore and rollback limits

Use the supported backup/restore procedure in [backup-restore.md](backup-restore.md),
with the new tools for a new LDAP-aware bundle. Restored settings/CA/bind references
survive, but all sessions and pending configuration-check proofs are invalidated.
Reauthenticate locally and test LDAP after restore. Missing active bind material
must fail verification. Old manifests remain supported.

Do not downgrade by merely changing current: older code does not implement the
LDAP role boundary. Rehearse restoring the pre-upgrade backup with compatible tools
before adopting rollback as a recovery plan. Systemd/reboot behavior still requires
the host acceptance rehearsal: local upgrade tests use a nonprivileged Debian
operator container and --no-systemd, not a running systemd host.
