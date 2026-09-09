# Local administrator and source destination policy

Implementation based on approved [authorization proposal](web-source-authorization-proposal.md).
This is the single-administrator stage. Operator/viewer, source scopes, LDAP/LDAPS,
OIDC and MFA are not implemented. The release gate and measured evidence are in
[the review record](local-admin-policy-review.md). Do not treat the pending upgrade
rehearsal as passed.

## Identity and sessions

The server assigns one principal UUID. Username is not an authority and no role
assertion/header from a client is accepted. All active principals in this stage
are administrators with the explicit permissions below; unknown permissions fail
closed. Enrollment is not granted to the first visitor or by Bootstrap READY.

Root uses `deploy/auth.py --root ROOT --invitation-file ABSOLUTE_FILE invite`.
The invitation is 32 random bytes, single-use, valid for 15 minutes. Only its SHA-256
digest is stored. The new file is opened exclusively/no-follow, mode 0600, under
a root-owned private directory. A pre-existing file is refused before the worker
call. The token is not in URL, argv, env or daemon output. Host control captures
the root worker reply and writes the file; it never prints the invitation.
A failure can leave an empty file: use a fresh filename, and issue a new invitation.

Passwords are 15–256 characters at enrollment and stored as salted Argon2id hashes:
19 MiB, two iterations, parallelism one, following the current
[OWASP password guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
The local Docker measurement under a 192 MiB limit was 0.053 s for hash+verify,
65,924 KiB peak RSS for the measured Python process. This is not a VM performance
claim. The worker is serialized; failed attempts persist across restarts. Five
attempts per five minutes is a global limit for this one-account stage; it can
cause a shared login delay under abuse. No password reaches browser storage.

Sessions are opaque 32-byte random handles, hashed server-side, with an eight-hour
absolute and 30-minute idle timeout; at most 32 active sessions. Login issues a
new handle. Cookie: `__Host-netbox-sync-session`, Secure, HttpOnly, SameSite=Lax,
Path=/, no Domain. See [OWASP sessions](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
Policy changes additionally require a login within 15 minutes. Sign in again if
required; no policy request or other write is automatically repeated.

`logout` revokes that session. Root `revoke` revokes all sessions and pending probe
receipts. Root `recover` disables the principal immediately, revokes sessions and
receipts, and issues a fresh one-time invitation; enrollment preserves the UUID.
There is no recovery HTTP endpoint. A failed auth worker makes protected requests
fail with a safe 503, never anonymous access. Root access to the host is the
explicit recovery trust boundary.

## Processes and grants

`netbox-sync-auth-worker` is a separate root process with two Unix endpoints:

- `/run/netbox-sync-auth/worker.sock`: API UID 10001 and probe worker UID 0;
  both still need an actual user session. No root action is accepted here.
- `/run/netbox-sync-auth-admin/worker.sock`: UID 0 only, in a private 0700 tmpfs
  not mounted into API or probe. Only the operator's host Docker control executes
  the administrative client. No app container gets Docker or systemd access.

The shared API/probe socket is read-only mounted into those clients. The worker
has read-only rootfs, cap_drop ALL plus CHOWN for its Unix socket, bounded memory
192 MiB/pids 32, and no provider/NetBox credential mounts or network RPC endpoints.
Bundled mode uses only the internal PostgreSQL network. External PostgreSQL uses
an explicit Compose network override for database reachability, matching the
existing external-DB topology. This Docker network is not an IP firewall: operators
must restrict external DB egress at their network boundary. The worker protocol
cannot request provider/network probes; application code connects only to its
configured PostgreSQL DSN. Provider traffic remains in the dedicated probe worker.
Broker remains literal `network_mode: none`; no API/DB ports are published.

Migration `0006_auth_policy` adds a singleton `auth_state` JSONB row and append-only
`auth_audit` events. A DB row lock serializes enrollment, login counters, session
changes, policy CAS and receipts, including across the root/public processes.
This intentionally uses one principal/state aggregate rather than the proposal's
future multi-user table decomposition. DB transaction failure grants no access.
`netbox_sync_auth_writer` can SELECT auth_state, UPDATE only its value, INSERT
into auth_audit, and use its sequence. It cannot read source/run tables, delete
state, update audit or create schemas. Existing API/runtime roles cannot read/write
auth state. Root/backup owner access remains the existing host DB trust boundary.

## Protected route map

`netbox_sync/api/auth.py::ROUTES` is the executable map. A regression enumerates
all OpenAPI operations and rejects unmapped business routes. New routes are denied
until mapped. Every unsafe HTTP request still requires exact Origin and CSRF;
valid Origin, ingress headers or READY do not confer permissions.

| HTTP /api/v1 route family | Server permission |
|---|---|
| GET health | Public minimal `{status: healthy}` only |
| POST auth/login, auth/enroll | Public entry with Origin/CSRF, rate limit and credential/invitation checks |
| GET auth/me; POST auth/logout | Active session (`source.read` in this admin-only stage) |
| GET policy | policy.read |
| POST policy | policy.write; worker independently rechecks session and recent login |
| GET system/health, version, diagnostics | diagnostics.read |
| GET runs, runs/{id} | run.read |
| GET sources, source detail/schedule/operations/lifecycle | source.read |
| POST sources/test-connection | source.probe |
| POST sources; sources/cancel-onboarding | source.register plus owned receipt |
| PATCH sources/{id}/schedule | source.schedule |
| POST discovery, operations/discovery, operations/plan, sync-plan | source.plan |
| POST sync, sync-confirmations | source.apply |
| POST remove | source.remove |
| GET/POST bootstrap and its subroutes | bootstrap.manage |

`source.configure` and `identity.manage` are reserved permission names without
new HTTP write routes. No user-management or future-role toggles are exposed.
Static SPA files are public; they contain no operational data. Unknown API paths
do not fall back to SPA. Machine scheduler/worker/CLI contracts do not use browser
cookies. Post-restore diagnostics runs the read-only local service directly,
without an anonymous HTTP exception.

## Policy and standard public-source flow

Upgrade defaults to legacy env semantics. Root explicitly selects one ceiling:

```
python3 ROOT/current/deploy/auth.py --root ROOT --ceiling existing managed
python3 ROOT/current/deploy/auth.py --root ROOT --ceiling public-ipv4 managed
```

Choose one, not both. `existing` preserves the exact env ceiling and does not
permit web expansion. `public-ipv4` deliberately authorizes point exceptions
through the panel. Baseline DENIED_CIDRS and immutable protected-address rules
still win; existing CIDR/hostname/suffix allows are preserved. Private defaults
are retained when no CIDRs were configured. The transition is audited and
invalidates pending receipts. It does not rewrite env or restart containers.

After the public ceiling is selected once: sign in → Add source → enter a bare
hostname/IPv4 and source-specific credentials → Test Connection. Ordinary allowed
sources need no extra action. If denied, the form offers a separate explicit
“Allow destination” action for exactly that host. Reload/review on revision
conflict, then repeat the connection test and register with automatic sync OFF.
No per-source host commands or file edits are needed. `/policy` lists web-added
hosts and lets an administrator revoke them. Revocation cannot remove an inherited
allow rule; the effective baseline remains visible in details.

Policy changes require expected_revision plus an idempotency key. Successful
requests retain actor, canonical operation and resulting revision; the same
request is replay-safe, a changed request/key conflict is rejected. Audit stores
actor UUID, server time, host, old/new revision and request ID, never credentials.
At most 256 exact web hosts/8 KiB of host text and the latest 4096 change keys are
supported in this stage, with a 24 KiB response safety guard. Older idempotency keys are evicted; a replay with an old revision then gets a
conflict without a new write. Revocation remains possible when that window is full.
Audit has no automatic purge. Exceeding a host/response bound is a safe refusal;
larger fleets and audit retention management need a separate implementation.

Before connecting, the probe worker obtains the current revision and policy from
auth/policy using the session, not an API-provided allowlist. All DNS answers are
checked and the selected IPv4 is pinned while TLS verifies the hostname. Existing
fixed provider ports, protected-address deny rules and whole-process timeout remain.
An already authorized, bounded probe may finish after a policy change; its old
receipt cannot register. Receipts bind principal, provider, exact submitted
destination, revision and ten-minute expiry, and are consumed once. Cancellation
checks ownership. Credential material stays only in existing short-lived API
memory and broker storage after registration, never in policy state/audit.

These are registration/probe rules, **not a firewall for subsequent Discovery or
Apply**. Revoking a web rule does not stop existing sources. IPv6 outbound transport,
general URL fetches, arbitrary ports and provider certificate bypass are not added.
The API destination restrictions and lifecycle/shared apply lock are not replaced.

## Backup and restore

Standard backup captures identities, hash, policy, audit and existing sources,
history, credentials, onboarding and metadata. These are protected backups.
Restore keeps the target root, Compose identity, ingress/TLS layout and target
host policy baseline. It refuses an already-enrolled target. Old manifests without
auth.env remain supported through the existing isolated optional libpq preparation
path. Migration creates the missing auth state on old archives.

Restore clears sessions, invitations, receipts and login attempts, preserves
identity/rules/audit, and returns policy to legacy mode until root explicitly
reapproves a ceiling. This avoids importing active source-host capabilities from
another deployment. Old passwords remain usable for a new login; disabled accounts
still require root recovery. Runtime is checked after restore; timer stays stopped
per the existing restore contract. No operator-owned TLS key is overwritten.
