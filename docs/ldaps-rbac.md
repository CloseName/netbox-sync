# LDAPS and fixed roles

Local production Compose, upgrade, backup/restore and provider runtime gates passed;
see [the evidence](ldaps-rbac-progress.md). Microsoft AD and host acceptance remain
operator gates. No Microsoft AD or live systems were used.

## Identity and authorization

The existing auth-worker owns local and directory sessions and the server permission
matrix. The API asks it to authorize every business endpoint. Default is deny.
Origin/CSRF, TLS and onboarding are separate controls and never establish a role.
Browser permissions only decide which controls to present.

Directory identity is the configured stable directory ID attribute (`objectGUID`
for AD), scoped by a persistent generated directory identifier. A username is a
lookup key, not an authority or stable identity. Refresh rejects replacement accounts
with the same username but a different identity. Local emergency administrator
sessions remain separate and retain their existing enrollment/recovery procedure.

| Role | Permissions |
| --- | --- |
| Viewer | Read sources, discovery/plan results, schedules, runs and diagnostics. |
| Operator | Viewer plus Discovery, Build Plan and confirmed manual Sync. |
| Admin | Operator plus onboarding, source/credential/mapping management, schedules, destination policy, LDAP settings and group mappings. |

There are no custom roles or source-scoped grants. An account must be in at least
one explicitly mapped direct group. Multiple matches select Admin over Operator
over Viewer. Nested groups and AD primary-group membership are not expanded.
Use dedicated direct groups. Disabling referrals prevents silently extending the
trusted directory/search boundary; use search bases in the configured directory.

### Endpoint matrix

`netbox_sync/api/auth.py::ROUTES` is the executable authority. Tests enumerate every
OpenAPI route and reject any route without an explicit permission. Role state-machine
tests exercise every permission; direct HTTP tests exercise every forbidden route.
Public endpoints are health and the bounded login/enrollment exchanges only.

| Method and route under `/api/v1` | Viewer | Operator | Admin |
| --- | --- | --- | --- |
| GET auth/me; POST auth/logout | yes | yes | yes |
| GET sources, sources/{id}, /schedule, /operations, /lifecycle | yes | yes | yes |
| GET runs, runs/{id} | yes | yes | yes |
| GET system/health, version, diagnostics | yes | yes | yes |
| POST sources/{id}/discovery, /operations/discovery, /operations/plan, /sync-plan | no | yes | yes |
| POST sources/{id}/sync-confirmations, /sync | no | yes | yes |
| POST sources/test-connection, sources, sources/cancel-onboarding | no | no | yes |
| GET/PATCH sources/{id}/placement; PATCH /name, /schedule; POST /remove | no | no | yes |
| GET/POST catalog/{kind}; GET catalog-operations/{id} | no | no | yes |
| GET/POST policy | no | no | yes |
| GET/POST bootstrap and its helper routes | no | no | yes |
| GET settings/ldap, settings/roles; POST settings/ldap, /test, /revoke | no | no | yes |

### Operation admission

A stored plan never grants permission. API authorization rechecks directory state
for every mutating permission. Prepare and apply additionally recheck immediately
before dispatch to the worker. A role revoked after prepare prevents a subsequent
apply request. Confirmation capabilities bind the server principal ID as well as
the source, generation and digest. Runs record the admitted principal ID.

Admission is the successful final API authorization and dispatch, not worker finish.
An admitted operation can finish after logout, group change or directory outage;
there is no attempt to cancel an in-flight write, steal its lock or replay it.
A separate later request must pass authorization again. This intentionally preserves
machine-authorized workers and scheduler independence: they do not acquire an LDAP
bind secret or require an interactive user session. Unix peer restrictions, shared
apply lock, digest/generation revalidation and source isolation remain necessary.

## Directory parameters the operator must supply

- LDAPS hostname matching the certificate, port (normally 636), reachable from
  auth-worker only. No guessed organization addresses are shipped.
- Trusted issuer CA certificate(s) as PEM, without private keys. Blank uses system
  trust; it does not disable validation. The directory must present its intermediates.
- Bind account DN and its password. Use a dedicated read-only account, never a domain
  administrator. It needs LDAP bind and read/search of the selected users, mapped
  groups, stable identity and account-state attributes; no create/update/delete rights.
- User and group base DNs in the served directory, user lookup attribute and object
  class, group class and member attribute, stable identity and account-control
  attribute. AD defaults: sAMAccountName/user, group/member, objectGUID and
  userAccountControl. Use the account's login attribute value at sign-in.
- Exact direct group DNs and fixed roles. Confirm that the bind account can read
  these groups and user accountExpires, pwdLastSet and
  msDS-User-Account-Control-Computed attributes used for account checks.

The client checks disabled accounts and, when returned by the directory, lockout,
password expiration/must-change and account expiry. Actual AD attribute visibility,
policy and account-state behavior require the operator acceptance below. The local
OpenLDAP fixture models those attributes; it is not an AD domain controller.

The bounded LDAP subprocess receives credentials via stdin only. It uses verified
TLS, escaped filter values, no referrals, read-only connections, two-second socket
and search limits, and an eight-second overall deadline. Raw LDAP exception strings,
responses, passwords and authorization headers are never public diagnostics.

## Settings, storage and revocation

Sign in with a recent administrator session; open Settings → Authentication / LDAP.
Fill parameters, map groups, then Check configuration and Save settings. The check
verifies bind, search bases and mapped groups; it does not prove a user's login.
An exact configuration/secret proof expires after five minutes and is bound to the
administrator and current revision. A competing save requires reload and review.

Blank password retains the existing secret. Changing hostname, port, bind DN or CA
requires re-entering it, so an old credential is not silently sent to a new authority.
Saving enabled settings requires a successful exact check. Local admin can disable
an existing configuration while the directory or bind file is unavailable; this
retains its previous configuration rather than saving unchecked draft changes.

Bind files use existing SecretBrokerStore immutable file operations (0600 files,
0700 root-owned directory). Only a reference enters auth_state; settings return a
boolean presence indicator. Installer creates `<root>/secrets/auth` with mode 0700.
The auth-worker mounts this directory read-only; only the networkless broker has a
writable mount. A dedicated root-peer Unix socket accepts only create requests and
returns an immutable generated reference. It cannot read/delete source credentials.
API, PostgreSQL and sync workers receive neither this socket nor the bind files.
Broker remains literal `network_mode: none`.

Only auth-worker joins `netbox-sync-ldap-egress`. Application connections are limited
to the administrator-configured LDAPS host/port with verified TLS, bounded timeouts
and referrals disabled. The Docker bridge itself is not a destination firewall:
operators requiring network-enforced restrictions must allow only their directory
addresses/ports at the host/network boundary. Auth-worker still needs its existing
private database connection (external-PostgreSQL mode preserves that network).
No API/DB published ports, Docker socket, or LDAP access is added to sync workers.

Replaced and unreferenced immutable bind files are retained, including in backups.
There is no automatic garbage collection: removing files by guessed age can break
an older recovery point. Protect backup archives as credentials, not ordinary logs.

Sessions: eight-hour absolute / 30-minute idle lifetime. Read authorization can use
cached directory membership for at most 30 seconds; writes force revalidation.
Revalidation failure revokes the session and fails closed. Settings/group mapping
save and explicit directory-session revoke clear all directory sessions immediately.
Local sessions survive directory configuration changes and directory outages.
Sensitive settings/policy changes require a login within the preceding 15 minutes.
Twenty failed corporate logins in five minutes throttle directory login; the local
emergency login has its existing independent budget. Successful logins do not consume
the corporate failure budget. Authentication changes/role changes/revocations and
permission checks enter auth_audit without secrets.

## Upgrade, backup and recovery

Existing auth_state JSONB can hold directory settings without widening DB grants.
Local sessions and directory sessions occupy separate maps, so the previous local-only
release cannot interpret a corporate handle as an administrator session. This does not make downgrades supported: old releases do not implement LDAP role
authorization or this secret writer boundary. Use a supported backup recovery point
and its matching tools, rather than switching `current` backwards.

The normal installer retains the selected root and generates
`NETBOX_SYNC_AUTH_SECRET_DIR=<root>/secrets/auth`. Existing local identity, source
credentials, onboarding and PostgreSQL volume are retained. No re-enrollment or new
DB is required. The auth state remains in its existing table and grants are unchanged.

Backup includes auth state and protected bind files. The optional manifest
`ldap_secret_reference` binds the database's active reference to an archived file;
a missing referenced file fails verification. Older manifests remain readable.
Use the new backup tool to read new manifests; older tools may reject new fields.
Restore rewrites host-local mounts from the target root, never from a manifest path.
It revokes local/LDAP sessions and transient LDAP check proofs/attempts, while retaining
settings, CA, group mappings and secret references. Log in again after restore.

Host-side local administrator recovery remains the existing documented procedure.
Never resolve directory outages by disabling TLS, assigning everyone Admin or
removing API authorization. Verify local emergency credentials before enabling LDAP.

## Operator acceptance after repository runtime gates pass

Use [the upgrade runbook](ldaps-upgrade-runbook.md) for an existing installation.

1. Verify local administrator login and recovery access; take a supported backup.
2. Supply actual LDAPS/CA/DN/group parameters and verify the saved configuration.
3. Test a real AD Viewer, Operator and Admin; unmapped/unknown and wrong-password
   users must fail. Confirm direct/nested/primary-group limitations explicitly.
4. Verify CA/hostname rejection, account disable/lock/expiry and group revocation;
   read cutoff ≤30 seconds, next write denied, local admin still usable during outage.
5. Verify Settings restart persistence and concurrent revision conflict; secrets must
   not appear in responses/logs. Check backup/restore revocation and emergency recovery.
6. Run manual and scheduled synchronization acceptance separately, preserving no-op
   and reviewed-plan behavior. Finish clean deployment rehearsal before v1 readiness.

## Official references

- [ldap3 TLS verification](https://ldap3.readthedocs.io/en/latest/ssltls.html)
- [ldap3 connection/referral/read-only options](https://ldap3.readthedocs.io/en/latest/connection.html)
- [ldap3 bind](https://ldap3.readthedocs.io/en/latest/bind.html)
- [Microsoft userAccountControl flags](https://learn.microsoft.com/en-us/troubleshoot/windows-server/active-directory/useraccountcontrol-manipulate-account-properties)
- [Microsoft LDAP matching rules](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-adts/4e638665-f466-4597-93c4-12f2ebfabab5)


## Unified login after live acceptance

The server reserves the existing local administrator name (including case variants)
for local verification; all other names use enabled LDAP. No fallback or identity
merging occurs. Legacy provider hints cannot override routing. See the
[UX follow-up and compatibility contract](ldaps-ux-acceptance.md), including explicit
recovery form access and temporary-error behavior.
