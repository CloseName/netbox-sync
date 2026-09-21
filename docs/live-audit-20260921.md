# Live-audit follow-up: directory users and operational evidence

Baseline: `f3f149bae60c69998d8b473062eeee90d8f2133d`, existing `main` checkout.
No push, deployment, live AD/NetBox/hypervisor connections or changes to CM-QA.

## Delivered behavior

- Settings uses one Group DN for admission. Users is Admin-only and populated by
  directory synchronization before first login. Individual roles default to Viewer.
  Operator can register sources and manage schedules; removal/restoration, teams,
  destination policy, LDAP settings and user-role administration remain Admin-only.
- Stable user keys combine the retained directory namespace and immutable directory
  identity (AD objectGUID). Renames retain roles; a replacement identity does not.
  Changing host/port/user base/identity attribute rotates the namespace and clears
  old users, rather than transferring privileges to another authority.
- Direct membership only. Nested and primary-group expansion remain unsupported.
  Server search uses memberOf, paging by 200, at most 5000 returned users, 40 pages,
  2 MiB subprocess output and an 8-second total deadline. Incomplete results,
  duplicate IDs, repeated paging cookies and errors preserve the previous snapshot.
  Up to 10000 current/former users are retained; exceeding bounds fails closed.
- Automatic membership refresh runs every 300 seconds, checked by auth-worker every
  30 seconds. Manual synchronization and role changes require recent Admin login.
  Removed/disabled accounts are inactive, not deleted. Role changes are audited and
  revoke that user's sessions. Role writes use revision fencing.
- Directory outage never becomes an empty successful membership snapshot. New
  login requires AD; existing read authorization caches membership for at most
  30 seconds; every mutating permission rechecks it. Revalidation failure revokes
  the session. Previously admitted writes can finish; no blind cancellation/retry.
  The separate local emergency administrator stays available.
- Users search/pagination returns 10 rows per page, including before login. This
  fits the existing 32 KiB Unix transport even at maximum Unicode name lengths.
- Source diagnostics now reads bounded plan/outcome metadata through the existing
  lifecycle worker. API DB grants are unchanged. Blocked plans remain visible
  without Runs, participate in Attention and link to the plan. Plan time and latest
  successful sync are distinct. Missing evidence is not reported as health.
- Discovery preserves allowlisted CPU/RAM/disk/interface/IP facts through worker,
  DTO and UI; unavailable values remain hidden. Names/IPs are searchable, technical
  IDs are expandable, and preliminary classification does not promise creation.
- Old uncertain/partial outcomes disable unsafe source actions in UI. Prepare and
  apply check history, with apply rechecking under the shared lock before child
  dispatch. Scheduled execution also checks history before any provider call under
  the existing scheduler lock; it records BLOCKED instead of bypassing the guard. Used confirmations remain consumed. History is never reset or hidden.
- Conflict explanations are compact; UUIDs are in details. Discovery progress/result
  is adjacent to its action. The shared UI clock could lag a fresh operation by up
  to 10 seconds: rendering now uses current wall time. If a recorded start still
  lies ahead of the browser clock, show its absolute timestamp instead of describing
  an already started operation as future. Actual host/browser clock skew is unverified.

## Migration and recovery contract

There is no new Alembic revision: head remains `0006_auth_policy`. AuthPolicy
transactionally migrates the existing auth_state JSON to `user_model=2` on first
access. A single legacy mapping becomes Group DN; multiple mappings disable LDAP
until local Admin explicitly chooses, tests and saves a Group DN. No group-role
privileges are carried over. Old LDAP sessions/proofs are revoked; synchronized
users start as Viewer. The local emergency identity and its sessions are retained.
Verify that local login works **before** upgrading. Local Admin cannot be edited
through Users, so directory role edits cannot remove the last emergency access path.

Normal installer/backup paths are unchanged. Backups include auth_state users/roles,
CA and protected immutable bind files. Restore preserves individual roles while
invalidating sessions and transient proofs. Do not downgrade by switching current
backwards; use the matching supported backup/restore recovery point. Existing
root, credentials, onboarding and PostgreSQL volume must be retained.

Broker remains `network_mode: none`; only auth-worker has the existing LDAP egress
and read-only bind-secret mount. API/DB/sync workers gain neither. No new capabilities,
ports, Docker sockets, TLS changes or DB grants. Directory migration changes
permissions deliberately and was explicitly confirmed by the user.

## Verification record

- Linux suite: **1101 passed, 121 skipped**; Jinja2-dependent presentation file was
  excluded from that runner and separately passed **2 tests** in a test venv.
- PostgreSQL: **37 passed** (lifecycle, auth migration/audit/restart, source operations)
  against a unique network-isolated tmpfs PostgreSQL 16 instance.
- LDAP protocol: **6 passed**, real verified TLS/OpenLDAP with 209 users over multiple pages,
  immutable-ID rename, disabled account, membership changes and denied logins.
  This is not Microsoft AD.
- Frontend: **71 passed**; TypeScript and Vite passed (existing bundle-size warning).
  Combined browser suite **93 passed**; targeted follow-up **6 passed**, including
  a running PLAN whose server timestamp is five seconds ahead of the browser.
  EN/RU, light/dark, narrow viewport, keyboard focus, search, pagination, errors,
  blocked source without runs, rich Discovery and uncertain-outcome UI.
- Production Compose: **2 passed**, bundled and external PostgreSQL paths exercised with actual
  services, LDAP protocol, browser→API→auth-worker, enrollment, role enforcement,
  automatic sync before login, CA rejection, read-only secret mount and network
  boundaries. Bundled path also runs supported host backup create/verify/inspect,
  restore, upgrade and runtime reauthentication; individual roles are asserted retained.
- Scheduler/orchestrator targeted suite: **38 passed**, including refusal before
  provider dispatch when an earlier outcome is unknown.
- Additional HTTP role suite: **32 passed**, including allowed schedule writes by
  Operator/Admin, denied Viewer writes, directory revalidation and forbidden Admin routes.
- Production worker gate: **1 passed**, actual API/preview/Discovery/plan/prepare/
  apply/replan for ESXi and Proxmox VM/LXC over HTTPS 8443, scheduled no-op for each,
  scheduled refusal/recovery, and populated upgrade preserving the exact DB volume.
  After a controlled ESXi write refusal, fresh prepare and scheduled execution are
  blocked with no subsequent HTTP writes. Diagnostic/lifecycle metadata remains visible.
  The final real-browser/production-worker run passed in 171.32 seconds: Proxmox
  completes the positive confirmation cycle, while ESXi uncertainty disables both
  rebuild and confirmation and does not display misleading ready/allowed labels.
  The older fixture was updated to use separate empty clusters and matching source
  names, as required by the existing registration contract. Its prior sequence of
  resuming writes after uncertainty was replaced by an explicit refusal scenario.
- New regression proves no apply child dispatch after an uncertain outcome appears
  after preparation, and verifies the history check occurs under the shared lock.
- A SQL JSON operator mismatch was caught by real PostgreSQL and corrected. Earlier
  broad-suite failures were expectations for the new DTO/defaults and BLOCKED result;
  targeted reruns passed. A browser regression also caught premature scroll restoration
  before diagnostics changed table height; waiting for diagnostics fixes that race. No test failure is being attributed to a live system.

The 121 generic Linux skips are environment-gated, not 121 successful checks:
PostgreSQL DSN cases (the three affected files were separately run above), Docker
CLI/opt-in cases (production auth Compose separately run), cross-UID/capability
containers, historical upgrade/backup/naming rehearsals and intentionally unconfigured
live ESXi. Unchanged naming, old-version migration and capability timeout suites are
not newly claimed as validated. Existing 120-second limit and bounded cleanup code
were not modified. Systemd reboot and actual AD policy behavior remain host gates.

Implementation commits: `6c4c6a3` (directory users/roles) and `3b6720b`
(source evidence, UI and unresolved-outcome protection). Final TypeScript/Vite and
Dockerfile.web build passed; both unstaged and staged whitespace checks passed.

Screenshots are stored outside Git in the task artifact directory
`netbox-sync-live-audit-20260921/gallery.md`; filenames identify language/theme/state.
Fixtures contain synthetic names/IPs only. Production screenshots use isolated test
services and do not establish live acceptance.

## Sequential operator acceptance after review/publication

1. Confirm emergency local Admin login; take and verify a supported full backup.
2. Use the existing upgrade runbook with the reviewed published SHA and selected
   ROOT. Confirm unchanged volume, credentials, onboarding and ingress.
3. Sign in locally. Inspect migrated LDAP configuration; if disabled, choose one
   admission Group DN, verify CA/hostname, test then save. Synchronize Users.
4. Confirm users appear before login as Viewer. Assign one individual's Operator
   role; re-sync/rename and verify role retention. Check Viewer/Operator denial of
   Users/teams/removal/policy and Operator schedule access using server requests.
5. On approved AD test accounts, verify removal/disable, outage behavior, direct-only
   membership, paging and local emergency access. Do not expose bind passwords.
6. Inspect CM-QA's historical unknown outcomes read-only. Do not reset statuses,
   delete sources/history or repeat any old apply. Reconciliation is a separate review.
7. Sequentially PLAN ESXI-AM-QA2, then PLAN ESXI-PAM-QA; inspect Attention, conflict
   details and Discovery properties in EN/RU. No prepare/apply in this acceptance.
   Existing conflicting objects and historical write outcomes are not established by
   these local tests; the new UI does not claim that live conflicts are resolved.

Initial Docker inventory was performed once. Uncertain old resources were retained;
only uniquely owned test resources are removed by their fixture teardown. No global
or final cleanup and no manual access to Docker Desktop virtual disk files.

## Directory protocol references

- [Microsoft group objects](https://learn.microsoft.com/en-us/windows/win32/ad/group-objects): direct membership attributes; no recursive privilege inference.
- [ldap3 paged searches](https://ldap3.readthedocs.io/en/latest/searches.html): paging cookie and response completion checks.
- [Existing TLS/account-state references](ldaps-rbac.md#official-references).
