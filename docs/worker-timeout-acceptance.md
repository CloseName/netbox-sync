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

Other audited paths: Bootstrap validation, setup and catalog use subprocess.run
with cross-UID children and have the same missing-KILL risk. Their additional
capability change was rejected by automatic approval review and is pending
explicit permission. No Bootstrap or LDAP modifications have been made by the
rejected command. LDAP's subprocess uses the same UID; it does not require KILL.

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
5. Verify installed container metadata for discovery/apply only: User, CapAdd,
   CapDrop, SecurityOpt. Expect root supervisor, CHOWN/SETUID/SETGID/KILL, ALL drop,
   no-new-privileges. Image rebuild alone is insufficient: recreate containers via
   installer so changed capabilities take effect. Broker must still be networkless.
6. Run read-only PLAN on ESXI-AM-QA2 and ESXI-PAM-QA, one at a time. Correlate new
   event IDs. If timeout persists, collect safe phase/duration/cleanup/returncode
   fields and worker restart count. Do not increase deadlines or apply a failed plan.
7. Independently rehearse partial-run recovery from live-audit-acceptance.md.
   Never automatically resubmit the previous uncertain operation.
