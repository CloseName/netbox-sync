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

The user approved explicit observation-only fallback on 2026-09-22 and subsequently
required observations directly on NetBox interfaces. That branch is implemented;
see [network-observations.md](network-observations.md) for the supported path and
explicitly incomplete VRF/duplicate-IPAM requirements.

Local follow-up checks: 72 Linux Bootstrap/upgrade/HTTP/apply tests passed; 3 real
PostgreSQL placement-policy tests passed; 48 Bootstrap/placement and 29 Source Detail
Playwright tests passed; TypeScript/Vite and Dockerfile.web passed. Production
worker/browser/scheduler/upgrade gate with both providers and explicit observations:
1 passed in 178.05 seconds. The full sync browser rerun passed: 32 tests, including EN/RU light/dark
observation plans and explicit incomplete-IPAM results. A stale blocked-plan test expected a ready message; corrected that
fixture expectation without relaxing the product guard.

## Sequential acceptance after separate review/publication

1. Local Admin: remain signed in >15 minutes; attempt destination permission, confirm
   identity, verify draft preservation, then explicitly retry. Wrong password must not
   permit the change; expired/revoked sessions still require full login.
2. CM: open the existing source, perform read-only Discovery, inspect evidence. Verify
   old unknown run persists and apply/scheduler/removal remain blocked. No apply.
3. PAM then AM: PLAN only, inspect exact identities and address observations. Do not
   claim duplicates or mask choices resolved by this checkpoint.
4. Retirement: review-only until the guarded-delete decision and gates are complete.


## Follow-up: durable outcome and incomplete inventory visibility

A lost apply HTTP response is reconciled only against the exact client-assigned Run
ID and reviewed digest. A recorded RUNNING result remains in progress; a terminal
result replaces the transport uncertainty without another POST. Explicit server
OUTCOME_UNCERTAIN/PARTIALLY_APPLIED and mismatched runs/digests are not overwritten.
A successful observation-only result retains its incomplete-IPAM explanation.

Diagnostics now project the existing unsupported action count. A successful run with
such actions gives source/run inventory limitations rather than “None reported”.
This count also covers other report-only actions: it is deliberately not presented
as an IPAM-specific count or proof of applied objects. No history schema migration.

The add-source wizard now distinguishes connection, destination, placement review,
final registration and result reconciliation; each starts a fresh elapsed timer.
Placement review does not imply that registration or cluster creation has started.

Checks in this follow-up: 50 Linux tests (observations, inventory conflicts, conflict
safety, diagnostics); 73 frontend unit tests; complete sync browser suite 33 passed;
complete wizard browser suite 18 passed; TypeScript/Vite and diff check passed.
Browser routes are controlled fixtures; these new checks do not claim a reproduction
of the live outer-ingress timeout or cluster creation failure. Existing >500 kB Vite
bundle warning remains. Docker desktop-linux Engine 29.7.2, no network for Linux tests.
The earlier production worker observation gate is recorded above, not rerun or
relabelled as verification of these later UI changes.

### Remaining live audit findings

| Finding | Evidence / remaining work |
| --- | --- |
| New cluster final registration refused | Live root cause unconfirmed; need safe error code/event and controlled production reproduction. Wizard progress correction does not fix this refusal. |
| HTTP lost while run proceeds | Local browser regression now follows same durable run; cause of the reported ~120 s disconnection remains unconfirmed. |
| Manual PLAN 120 s, scheduler recovery succeeds | No root cause demonstrated; keep bounded limit and collect safe phase timings. |
| Successful run hides inventory limitations | Corrected using durable unsupported action totals; no false claim that IPAM is complete. |
| Scheduled BLOCKED shown unavailable | Backend projection regression passes; original UI evidence/refresh issue not reproduced or declared fixed. |
| Placement says registering | Corrected and covered by delayed browser response test. |
| Retirement / cluster remains Active | Executable guarded deletion remains incomplete; review-only proposal above. |
| Restore original source into filled cluster | Identity-based restore remains incomplete; matching address/name is insufficient. |
| Shared VM identifiers | Still blocked; no arbitrary merge or identity-schema substitution. Compatibility analysis and identity evidence required. |

No publication, deployment, live queries or writes were performed.
