# Upgrade /netbox-sync-test to local administrator access

**Review candidate. Do not execute on a VM until the pending pre-auth upgrade
rehearsal in [the evidence record](local-admin-policy-review.md) is accepted.**
This task performed no push, deployment or VM connection. Commands below describe
an operator-executed future upgrade, not authorization to perform one.

Scope: existing bundled PostgreSQL, canonical external/shared ingress,
`https://netbox-sync-test.indeed-id.hq`, application root `/netbox-sync-test`.
NetBox remains separately managed at `https://netbox-test.indeed-id.hq`.
No naming migration, old env recreation, volume replacement or TLS bypass.
External PostgreSQL keeps its existing explicit override and operator-owned DSNs;
this bundled-installer runbook is not an external-DB provisioning recipe.

## 1. Identify, back up, and retain root access

Use a trusted root-capable administrative session and keep it open through enrollment.
Before upgrade, confirm current link, service/timer metadata and protected-file
existence without printing env, credential, cookie or invitation values.

```sh
set -eu
ROOT=/netbox-sync-test
readlink -f "$ROOT/current"
sudo systemctl is-active netbox-sync.timer
sudo python3 "$ROOT/current/deploy/compose.py" --root "$ROOT" ps
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" preflight
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" create
```

Use the **installed** backup utility before activation; accepted pre-auth 897de2a
already contains the clean-Debian host dependency fix. Older releases must first
follow their documented backup preparation, not a manual database-only copy.
Set BUNDLE to the exact directory reported by create (never its secret contents):

```sh
: "${BUNDLE:?Set the exact backup directory returned by create}"
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" verify "$BUNDLE"
sudo python3 "$ROOT/current/deploy/backup.py" --root "$ROOT" inspect "$BUNDLE"
```

Expected: verified archive; original current, database volume, credentials and
initial service/timer state retained. Stop on any failure or unexpected metadata.
Do not proceed without a verified backup and working root recovery access.

## 2. Select reviewed immutable code

The implementation is not pushed by this task. Use the final approved, published
commit supplied after the release gate; do not substitute an arbitrary latest main.

```sh
: "${RELEASE_COMMIT:?Set the reviewed full 40-character commit}"
case "$RELEASE_COMMIT" in *[!0-9a-f]*|'') exit 1;; esac
test "${#RELEASE_COMMIT}" -eq 40
test -z "$(git -C "$ROOT/repo" status --porcelain)"
test "$(git -C "$ROOT/repo" remote get-url origin)" = https://github.com/CloseName/netbox-sync.git
git -C "$ROOT/repo" fetch origin
git -C "$ROOT/repo" cat-file -e "$RELEASE_COMMIT^{commit}"
git -C "$ROOT/repo" merge-base --is-ancestor "$RELEASE_COMMIT" origin/main
git -C "$ROOT/repo" switch --detach "$RELEASE_COMMIT"
test "$(git -C "$ROOT/repo" rev-parse HEAD)" = "$RELEASE_COMMIT"
```

Stop if checkout is dirty, provenance differs or any check fails. No reset, force,
merge/rebase or secret-bearing config edits are part of this sequence.

## 3. Upgrade with explicit enrollment acknowledgment

```sh
sudo python3 "$ROOT/repo/deploy/install.py" \
  --root "$ROOT" --source "$ROOT/repo" \
  --release-id "$RELEASE_COMMIT" \
  --public-url https://netbox-sync-test.indeed-id.hq \
  --ingress-mode external --acknowledge-admin-enrollment
```

Use the normal installer, not prepare-only/no-start/no-systemd for the real host.
The new acknowledgment is required when an existing installation has no auth.env;
it records operator intent to enroll after activation, **not** a password or a
permission granted to HTTP users. Missing acknowledgment refuses before stopping
the timer or preparing/migrating the release. Existing authenticated upgrades do
not require enrollment again. No root invitation is generated implicitly.

Expected: the existing root, DB volume, credentials, READY, sources, history and
schedules remain; migration reaches `0006_auth_policy`; auth.env contains only the
new DB role and preserved policy baseline. Auth worker readiness is checked in
addition to API/proxy health. New component: `netbox-sync-auth-worker`; broker is
still networkless. API and DB remain unpublished; upstream remains
`/netbox-sync-test/ingress/upstream.sock`. Outer ingress still owns public TLS.

Stop on installer failure. Do not blindly rerun or activate the old release:
preparation may already have migrated the DB; old releases permit anonymous Web
access. Inspect only current link, container service/status/health, migration
revision, file metadata and timer state. Keep the failed deployment quiescent
until the failure phase is understood. The immutable release ID cannot be reused
for different content.

## 4. Enroll the administrator

```sh
sudo install -d -o root -g root -m 0700 "$ROOT/state/admin"
sudo python3 "$ROOT/current/deploy/auth.py" --root "$ROOT" \
  --invitation-file "$ROOT/state/admin/enrollment.invitation" invite
```

Expected: success without printing the invitation; root-owned file 0600, TTL 15
minutes. Transfer its value through the operator's approved private channel to the
HTTPS enrollment form. Do not use shell substitution, env, URL/query, screenshots
or journal output for the invitation. Choose a unique local admin password of at
least 15 characters. First visitor/onboarding READY do not gain any permissions.
Root access stays available if the browser or enrollment fails.

Open `https://netbox-sync-test.indeed-id.hq`, choose “I have an administrator
invitation”, enter invitation/username/password. Verify that existing READY and
sources appear. A correct Origin with no session must still return 401. A public
health response can be checked without credentials:

```sh
curl --fail --silent --show-error https://netbox-sync-test.indeed-id.hq/api/v1/health
sudo python3 "$ROOT/current/deploy/compose.py" --root "$ROOT" ps
sudo systemctl is-active netbox-sync.timer
```

Do not disable TLS verification. With an internal CA, supply the operator's CA via
curl `--cacert` or system trust. Do not print browser cookies in terminal tests.

## 5. One-time policy transition

Choose the intended ceiling explicitly. For the requested admin-only public-source
workflow, this command permits future exact public IPv4/hostname exceptions:

```sh
sudo python3 "$ROOT/current/deploy/auth.py" --root "$ROOT" \
  --ceiling public-ipv4 managed
```

Use `--ceiling existing` instead only when retaining a host ceiling that cannot be
expanded in the panel. Neither command adds a specific source. Existing deny rules
remain authoritative. Sign in again if the last login is older than 15 minutes.
Then Add source → test → separate exact destination permission if denied → repeat
test → review/register. Each subsequent source is handled in the panel without
files, server commands or container restart. Normal already-allowed sources need
no additional permission step. No discovery or automatic sync is enabled by
registration. Verify existing schedules and retained history separately.

## Recovery and restored backups

To revoke all active sessions without changing the password:

```sh
sudo python3 "$ROOT/current/deploy/auth.py" --root "$ROOT" revoke
```

If local admin access is lost, keep root access and issue a fresh recovery file:

```sh
sudo python3 "$ROOT/current/deploy/auth.py" --root "$ROOT" \
  --invitation-file "$ROOT/state/admin/recovery.invitation" recover
```

Recovery disables the old account immediately and preserves its UUID on new
enrollment. Use a new filename if one exists; never overwrite an invitation file.
This is audited root control, not an anonymous endpoint. After restore, old
sessions/invitations cannot be reused, and policy remains legacy until explicit
root reapproval. The timer remains stopped under the restore contract; do not
implicitly enable it while reviewing restored source state.
