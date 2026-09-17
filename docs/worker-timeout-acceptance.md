# Worker timeout follow-up

Base b5f445043ceaf02336c3697d5aefa513134850d2. Local work only.

## Confirmed cause and limits

The reported PermissionError occurs in kill(), after the 120-second discovery
budget. Root with cap_drop ALL cannot signal a UID 10001 child without KILL.
Discovery/apply now add only KILL in production and web Compose. Children still
have CapEff=0 after UID drop; no-new-privileges, broker network_mode:none, API/DB
networks and ports are unchanged. Probe already had KILL.

Popen context-manager exit and communicate() without a timeout were unbounded.
The shared child helper kills the exact child PID and waits at most two seconds.
A natural exit race is collected. A failed kill remains secondary evidence:
exception_class=TimeoutExpired, termination=timeout, cleanup_error=PermissionError,
child_reaped=false. A daemon reaper collects eventual exit. If apply still has a
live child, a duplicate of the existing shared lock descriptor retains exclusion
until that child is collected; the request does not wait indefinitely. No write
or confirmation is retried. Under the corrected capabilities child_reaped=true.
Discovery reports DISCOVERY_TIMEOUT; apply reports OUTCOME_UNCERTAIN once writes
are possible. This is not evidence that the earlier live uncertain runs had the
same initiating cause.

A separate inherited metadata pipe contains only allowlisted phase/state/duration.
Provider reads, preliminary NetBox reads and planning have start/end records.
The planning phase includes the planner's own NetBox reads, not just CPU time.
A timeout includes the last started phase and completed durations in its correlated
event. It never includes raw stderr, URLs, tokens, exception messages or inventory.
The 120/300-second execution budgets are unchanged. Slow live PLAN cause remains
unknown; the two supplied event IDs prove timeout-cleanup failure, not why the
underlying reads were slow.

## Local evidence

- tests/test_worker_timeout_docker.py: 4 passed (29.03 s): production/web rendered
  Compose capabilities, with and deliberately without KILL. Each container is
  unique, networkless, read-only, no-new-privileges, cap_drop ALL, tmpfs /tmp.
- Real UID 10001 children verify zero effective capabilities, timeout/reaping,
  next job, natural-exit race, bounded PermissionError, retained shared lock and
  eventual release. No live endpoints or secret mounts.
- Discovery/apply/probe/onboarding Linux regressions: 112 passed (6.81 s).
- Host runner lacks argon2; tests therefore ran in the existing isolated Linux
  dependency image, not by adding packages to the host.

Bootstrap follow-up: the user explicitly authorized only the bootstrap-worker
validation timeout fix and minimal KILL capability. `run_probe` now reuses the
existing bounded child helper; its 45-second deadline and public
VALIDATION_UNAVAILABLE response remain unchanged. A BOOTSTRAP_PROBE_TIMEOUT log
preserves the original TimeoutExpired and optional cleanup_error/child_reaped,
without payload, tokens or stderr. Only KILL was added to bootstrap-worker in
production/web Compose. No catalog/setup subprocess implementation, shared lock,
LDAP, API, broker, network, mount or other capability was changed. The earlier
broad refactor rejection is historical; it does not block this now-authorized fix.
LDAP uses same-UID children and does not need KILL. General setup/catalog timeout
refactoring is explicitly out of this follow-up's scope.

Bootstrap follow-up evidence:
- Actual UID/GID 10001 child, CapEff=0, production/web rendered capability sets:
  **4 Docker cases passed, 46.56 s** (with and deliberately without KILL).
  Correct configuration kills/reaps; missing KILL returns promptly with separate
  PermissionError, accepts a subsequent validation while the old finite fixture
  is alive, and eventually reaps it. Existing exit-race/apply-lock cases also pass.
- Bootstrap/transport/preparation/catalog/security Linux suite: **116 passed,
  1 skipped, 14.46 s**. The zero-source deployment test requires
  NETBOX_SYNC_DEPLOYMENT_TEST_POSTGRES_DSN, absent in this networkless runner;
  this unrelated DB startup path was not counted as passing or rerun.
- Compose read_only, cap_drop ALL and no-new-privileges are asserted. Runtime
  fixtures are uniquely named, networkless and automatically removed. No live
  endpoint, secret mount, production resource or published port is involved.

## Future operator update / acceptance (not executed)

1. Stop on an active/uncertain write until its actual state has been reconciled.
   Read only the installed release, current symlink and service status; never dump
   env files. Take and verify a supported backup before updating.
2. After separate publication approval, obtain the exact reviewed commit in the
   existing checkout. Keep ROOT=/netbox-sync-test and use the installer from that
   new checkout, not the old current symlink. Check a clean tree and exact SHA.
3. Validate first, preserving existing ingress/TLS/credentials:
   `sudo python3 "$ROOT/repo/deploy/install.py" --root "$ROOT" --check`.
   Stop on any failed check. Do not delete volumes or fabricate credentials.
4. Run the supported installer with `--root "$ROOT" --source "$ROOT/repo"
   --release-id "$RELEASE"` (RELEASE is the exact reviewed commit). Do not use
   prepare-only/no-start for activation and do not overwrite the selected ingress.
5. Verify installed container metadata for discovery/apply/bootstrap: User, CapAdd,
   CapDrop, SecurityOpt. Expect root supervisor, CHOWN/SETUID/SETGID/KILL, ALL drop,
   no-new-privileges. Image rebuild alone is insufficient: recreate containers via
   installer so changed capabilities take effect. Broker must still be networkless.
6. Run read-only PLAN on ESXI-AM-QA2 and ESXI-PAM-QA, one at a time. Correlate new
   event IDs. If timeout persists, collect safe phase/duration/cleanup/returncode
   fields and worker restart count. Do not increase deadlines or apply a failed plan.
7. Independently rehearse partial-run recovery from live-audit-acceptance.md.
   Never automatically resubmit the previous uncertain operation.

## Final local integration evidence (2026-09-17)

- Networkless Linux backend: 1019 passed, 113 skipped, 127.74 s. Skips are
  opt-in Docker/host suites, PostgreSQL DSN suites and prohibited live tests;
  they are not reported as successes. The newly affected cross-UID tests ran
  separately (4 Docker cases above), and auth persistence ran against isolated
  PostgreSQL (4 passed, 2.15 s). No live systems were used.
- Follow-up affected validation/API/diagnostic/export tests after final input
  hardening: 19 passed, 3.80 s. The full backend total above predates four added
  malformed-team-ID cases; these four passed in the follow-up.
- Frontend: unit suite, TypeScript and Vite production build passed; complete
  Playwright suite 266 passed, 5.1 minutes, including EN/RU ownership-team flows.
  Vite reports its existing bundle-size advisory; there are no build errors.
- Actual production Compose with bundled and external PostgreSQL: 2 passed,
  354.13 s. Real API/browser -> workers -> controlled HTTPS endpoints on 8443;
  ESXi and Proxmox VM/LXC plan/prepare/apply/replan, scheduled no-change and
  required-read rejection, durable partial-apply result and consumed-plan refusal.
  Bundled populated upgrade preserved source rows, credentials/config/READY/policy,
  DB identity and complete mount metadata. No systemd/reboot or live-server claim.
- A concurrently started second Compose suite initially failed because both
  fixture instances reserve the same controlled subnet. This was a test-resource
  collision, not a passing gate. Repeat suites sequentially; never remove another
  project's networks to make a test pass.

Additional work and limits: [VM comments](vm-description-contract.md),
[source ownership teams](source-teams.md), [exact ESXi diagnostics](esxi-dev-ba-connection.md),
[NetBox field presentation proposal](netbox-readable-fields.md). The latter does
not claim an installed embedded-card extension: the server version is unknown.
Original slow PLAN and historical live OUTCOME_UNCERTAIN causes remain unproven.
The narrowly authorized Bootstrap validation follow-up is recorded above; general
setup/catalog refactoring remains out of scope.

- Sequential repeat on the final product image: production auth/upgrade/backup
  Compose suite **2 passed, 198.51 s**, bundled/external PostgreSQL. Bundled path
  exercised supported host CLI create/verify/inspect and fresh restore, exact
  ownership-team metadata, source credentials, READY and policy retention, service
  state restoration and session revocation. External path verified authentication,
  safe probe outcomes, catalog uncertainty/reconciliation and restart/session flow.
- Final export-path correction (canonical physical_disks.path): 2 passed, 0.89 s.
- git diff --check passed. Runtime resources are removed only by each suite's
  exact ownership labels; no live/foreign resources were changed.
