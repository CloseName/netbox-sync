# Live-audit follow-up, 2026-09-22 — checkpoint

Base `0754e5759353aa379ed3374a692ad66ceb2efa0f`, canonical main in
`E:/Codex/Project/netbox-sync`, initially clean. No live connections, push or deploy.
This is not acceptance of the full PAM/AM/CM lifecycle.

## Confirmed local fixes

A still-valid local/LDAP session older than 15 minutes received AUTH_REQUIRED from
`recent()`. The frontend treated that as logout and unmounted the source wizard.
The new regression failed before the change with AUTH_REQUIRED rather than
AUTH_REAUTH_REQUIRED. This is a demonstrated local cause; the original live Allow
Destination HTTP response was not captured, so its exact cause remains unproven.

Recent-proof expiry now returns 403 AUTH_REAUTH_REQUIRED across the closed Unix RPC
vocabulary. A separate password-only endpoint confirms the **current** identity.
It cannot select another account/provider/role, extend the absolute session lifetime,
revive an expired/revoked session, or mutate destination policy. Local/LDAP rate limits,
CSRF, role checks, directory membership checks and policy revision fences remain.
Passwords are cleared from the form and are absent from state/audit. An explicit
second action is required; no policy/probe write is retried automatically.

Both DestinationPermission buttons now have type=button. They can be rendered inside
the connection form; the browser regression proves they do not implicitly submit it.
The outdated test heading was updated to the already-existing Source settings screen.

Read-only Discovery is available while a historical outcome is unknown. It uses the
existing discovery-worker/read NetBox token. The UI still blocks PLAN/prepare/apply,
server prepare/apply/scheduler guards remain, removal remains blocked, and no old run
status is reset. A successful read is NOT proof that the previous write completed.

## Local evidence

- 132 affected tests passed in network-none Linux, including real Unix peer-credential
  auth transport. Windows run: 129 passed, 22 skipped (19 PostgreSQL and 3 Linux Unix
  gates); these gates were then executed separately.
- 24 real PostgreSQL tests passed, including unknown/partial history after successful
  read-only Discovery. The initial new fixture omitted required Discovery DTO fields;
  it correctly failed validation, then passed after fixing the fixture.
- 25 Playwright tests passed together (EN/RU, narrow, themes, auth/policy, source evidence).
- TypeScript/Vite and Dockerfile.web build passed; existing bundle-size warning remains.
- Production bundled/external Compose auth: 2 passed, including HTTP -> auth-worker
  confirmation expiry/reconfirmation, retained policy, normal login, upgrade/backup.
- Full production worker/browser gate: 1 passed in 163.93 seconds. Both providers
  exercised plan/apply/replan and scheduled execution against isolated fixtures,
  plus populated upgrade and the read-only unknown-outcome browser path. The first
  run used an old Discovery generation in a later placement assertion; corrected
  the fixture to use the fresh generation and reran the complete gate.
- Retirement review/journal: 15 isolated Linux tests passed; no deletion test is claimed.

Docker context desktop-linux, Engine29.7.2. Engine was initially unavailable and later
became available. Initial old resources lacked enough ownership/obsolescence evidence
for safe deletion, so they were retained. No global prune/volume cleanup/VHD manipulation.
Only uniquely labelled resources of this task are cleaned by their test fixtures.

## Current live facts and unresolved work

The acceptance coordinator reports NetBox 4.7.0-Docker-5.1.0. PAM and AM were
registered normally into their old empty clusters with **new** source IDs; no duplicate
cluster appeared. The old tombstones remain. CM is still an existing active source
with an unknown run, and a new-source wizard refuses its occupied cluster. Do not
bypass this by generating another identity or treating 116 retained VMs as completion.

Safe restoration of the original source identity and a server-authorized reconciliation
transition are NOT implemented in this checkpoint. Read-only Discovery enables
investigation, not resolution. Legacy sources without durable server identity anchors
cannot be recovered from a matching address/name alone.

The later requirement for controlled NetBox deletion replaces comment-only retirement.
Its independently implemented non-executable review/journal and precise remaining
execution decision are in [retirement-guard-proposal.md](retirement-guard-proposal.md).

## Repeated addresses: observation versus IPAM assignment

Exact repeated NIC+CIDR facts are already deduplicated; distinct VM identities are
never merged by address/name. Different masks of one NIC are retained as separate
observations in Discovery and conflict details. They are not automatically assigned
as two IPAM objects, nor is one mask guessed. Under the current policy those conflicts
still block the plan: no partial successful synchronization is claimed.

Checked official NetBox **v4.7.0** source: IPAddress.get_duplicates compares host IP
without mask within a VRF; clean enforces ENFORCE_GLOBAL_UNIQUE/VRF uniqueness, with
special-role exceptions that Sync must not invent. Live uniqueness configuration was
not inspected. See [v4.7.0 IPAddress implementation](https://github.com/netbox-community/netbox/blob/v4.7.0/netbox/ipam/models/ip.py#L981).

The user explicitly approved option (2) on 2026-09-22; implementation is pending.
Options reviewed: (1) retain full-plan blocking pending an explicit IPAM mapping;
(2) explicitly allow syncing other inventory while recording all ambiguous addresses
as observations, with no disputed IPAM assignments and visible incompleteness;
(3) a separate explicit network-area/VRF design. No global uniqueness change, invented
VRF, automatic shared-address role, or new namespace policy was implemented.

## Sequential acceptance after separate review/publication

1. Local Admin: remain signed in >15 minutes; attempt destination permission, confirm
   identity, verify draft preservation, then explicitly retry. Wrong password must not
   permit the change; expired/revoked sessions still require full login.
2. CM: open the existing source, perform read-only Discovery, inspect evidence. Verify
   old unknown run persists and apply/scheduler/removal remain blocked. No apply.
3. PAM then AM: PLAN only, inspect exact identities and address observations. Do not
   claim duplicates or mask choices resolved by this checkpoint.
4. Retirement: review-only until the guarded-delete decision and gates are complete.
