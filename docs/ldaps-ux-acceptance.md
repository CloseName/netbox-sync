# LDAPS live-acceptance UX follow-up

Base: `9730860cbbc86c8c442cce9fdb91edce4d70e2f0`. Scope is the live feedback,
not the unrelated post-production backlog. No push/deployment/live connection.

## Login and compatibility

The server reserves the existing emergency local administrator username, including
case variants, for the local backend only. The local username remains exact-case
at password verification, preserving existing semantics. Other usernames go only
to LDAP when its saved configuration is enabled; otherwise login is refused.
The password is never tried sequentially against both providers and identities
are never joined by username. Older clients may still send local/ldap provider
hints, but those hints cannot override the server rule. A directory account with
the reserved name cannot use that short name to log in. Choose a distinct directory
login, or use the supported root recovery procedure to deliberately rename the
local administrator. Existing identities are not automatically renamed or linked.

GET /api/v1/auth/status exposes only enrollment_available, not username, LDAP
configuration or invitation. After enrollment, the ordinary login has no invitation
link. Root recovery still issues a protected invitation using the documented CLI;
open the normal HTTPS URL with `?recovery=1` to display the invitation form. The flag
is not a credential or permission: server invitation verification remains mandatory.
Never put the invitation itself into the URL. The server can refuse the form.

The normal login retains username on failure, clears password, and offers an
accessible show/hide control. No password is written to browser storage.

## Temporary failure and LDAP settings

Locally confirmed: the previous global AUTH_UNAVAILABLE handler removed principal
and unmounted the form. It now preserves the screen and warns that authorization
is temporarily unavailable. AUTH_REQUIRED still returns to login; AUTH_DENIED does
not impersonate logout. Server authorization remains fail-closed on every request;
a retained browser principal does not authorize writes. No failed write is retried.
This reproduces a local mechanism, not the unsaved HTTP response from the old live
incident. The operator reported the prior AUTH_INVALID was unsaved LDAP configuration,
not failed AD authentication; that interpretation is preserved.

Timeout budget: LDAP subprocess remains 8 seconds, individual network calls 2 seconds.
Auth RPC now allows 25 seconds for serialized checks/DB contention; frontend auth
requests allow 60 seconds for authorization plus handler RPC. Timeouts remain
unconfirmed outcomes, not proof of logout or a successful configuration save.

The compact form groups connection/search and schema fields. It validates empty
mapping rows and PEM framing before sending; authoritative PEM/TLS checks remain
server-side. API_VALIDATION_FAILED stays a validation error. Neither validation
responses nor UI messages include submitted passwords, values or raw payloads.
Results distinguish checked/not saved from saved/enabled or saved/disabled. Reload
shows progress and requires explicit discard confirmation for dirty fields.

Non-secret drafts are held in this tab's memory, keyed by server principal UUID.
They survive temporary errors and same-identity reauthentication within the SPA;
another identity cannot receive them. Passwords are excluded. Closing/reloading
the document discards memory drafts; this is not persistent browser storage.

## Navigation and operation evidence

Language/theme and sign-out move to the top-right user disclosure; Settings appears
there only with identity.manage. Login retains language/theme. Roles use human
summaries; exact permission identifiers remain in technical docs/tests. Session
revocation controls are removed from UI, not from automatic server enforcement.

Completed NetBox onboarding is gated by persisted completed, not transient READY.
Connection maintenance is under Settings at /settings/netbox; /setup redirects there
for a completed installation. Existing validation, explicit credential replacement
and field-preparation protections are retained. An ordinary connection failure does
not reset installation state.

SourceOperations.read persists RESULT_EXPIRED after 24 hours: it clears result and
marks PLAN STALE / DISCOVERY FAILED, retaining timestamps and history. This explains
why browser refresh cannot clear that state. The UI now renders this expiry neutrally
with result time and permission-aware guidance. Earlier planning failures preceding
a newer run are labelled historical. Plan lifetimes, shared apply lock, confirmation
and worker revalidation remain unchanged; opening a page sends no automatic writes.

## Verification

Results from local execution on this change:

- Affected backend, real LDAP protocol and apply/revalidation regressions: **114 passed**.
  The Linux test container had no external network; protocol fixtures ran locally.
- Frontend unit suite: **67 passed**. TypeScript and Vite production build passed.
  Vite retains its existing bundle-size warning; four Python dependency deprecation
  warnings did not fail the backend checks.
- Full browser suite: **249 passed**. After the final edge refinements (unknown
  initial bootstrap state, historical discovery label and login copy), the complete
  affected auth/settings/bootstrap/expired-results/sync-workflow/durable-lifecycle
  selection was repeated: **94 passed**, with the last-run record reporting passed
  and no failed tests. This final selection includes the new bootstrap outage test.
- Actual production Compose auth/LDAP runtime gates: **2 passed**, bundled and
  external PostgreSQL. After the final image rebuild, the external PostgreSQL gate
  was repeated: **1 passed, 1 deselected** (103.43 seconds). The deselection was the
  already exercised bundled case, not an unavailable test.
- Dockerfile.web production image build and `git diff --check` passed.

The Compose gates use controlled LDAPS and HTTPS/SOAP fixtures, no live servers.
They exercised unified real browser login, anonymous API refusal, role enforcement,
CA/hostname rejection, LDAP group removal/account disable, concurrent configuration
save, emergency local access during directory outage, session expiry/revocation,
worker restart and protected-state retention. The bundled gate also exercised host
backup/restore, retaining directory settings, secret and CA material, identities and
DB volume. Runtime inspection verified read-only secret mounts, networkless broker
and unchanged API/DB isolation. The temporary operator test container used the
previously authorized Docker socket; product containers did not receive it.

Browser regressions include 401/403/422/503 and simulated transport timeout (not a
60-second wall-clock timeout test), empty mappings/invalid PEM, checked vs saved,
non-secret draft isolation, enrollment visibility and role-aware expired results.
Visual fixtures cover EN/RU, light/dark and 1440/390px widths. Screenshots are local
artifacts under `frontend/test-results/`: `unified-login-*`, `ldap-saved-*`,
`ldap-roles-*`, and `expired-results-{viewer,operator,admin}.png`. They contain no
entered passwords. Final visual review included the desktop settings and expired
Viewer result, plus Russian dark narrow login/settings.

This UX task did not rerun the independent full provider plan/apply and scheduled
sync runtime suites. Their existing behavior was reported accepted on the live
installation; the current changes do not modify provider/planner/scheduler code.

The user's previous real Microsoft AD login, Viewer/Operator behavior and group
removal acceptance are reported facts, not tests repeated by this task. Remaining
live acceptance is limited to the changed unified-name rule, revised form/menu,
recovery visibility and expired-evidence presentation. This does not claim new AD
lock/expiry or host reboot validation.
