# Live audit: execution reliability and operator review

This is a **future operator acceptance procedure**, not evidence of a live test.
No live infrastructure was contacted during implementation. Do not automatically
retry either unknown ESXI-CM-QA request, reuse its confirmation, enable its
schedule, remove its source, or delete/adopt NetBox objects.

## What is proved and what is not

The original audit ran on 9730860; this change starts from
8b656dac0a0c15f66a5a6e7cac0405e614272da1. Unified sign-in, the real 401 boundary,
non-secret draft retention during an auth outage, user menu, LDAP settings,
NetBox maintenance and neutral expiry already existed in that base.

The unguarded apply supervisor socket reply could terminate the server when its
recipient disconnected. This is a confirmed defect, including a local Linux
Unix-socket reproduction. Catching that delivery failure keeps the server alive;
it does not turn the run into success or retry a write.

The two original OUTCOME_UNCERTAIN events precede BrokenPipe. Their initiating
exception is not present in the supplied logs and has **not** been reproduced.
A controlled HTTP failure after earlier successful writes tests the recovery
contract, not the unknown live cause. No specific live HTTP status, timeout,
permission failure, OOM or provider defect is claimed.

Likewise the three original OPERATION_FAILED planning failures are not explained
by the supplied empty frames. Locally, unexpected result-validation exceptions
reproduced the missing-diagnostic branch. They now record exception class,
repository frame names/lines, phase and elapsed duration. No exception messages,
locals, raw response, authorization headers or credential values are logged.

## Request lifetime and durable evidence

- Browser → same-origin API → apply Unix socket → supervisor → isolated child.
- Current child budget: 300 s; API socket wait: 310 s; browser wait: 330 s.
  Product nginx upstream read timeout: 360 s in all three templates. Their
  30 s send timeout is not an overall execution deadline. External ingress is
  operator-owned; its actual timeout and disconnect history are not known.
- Discovery/PLAN child budget: 120 s. Durable operation execution continues
  independently of the start-request response. No budget was increased here.
- Before the apply child can write, the Run row is bound to the reviewed digest
  and planner version. The existing confirmation consumption, source generation
  guard and shared apply lock remain mandatory.
- The browser supplies a fresh Run UUID. GET `/api/v1/runs/{run_id}` can recover
  its persisted state after response loss or a new authenticated session. A 404
  is not proof that the request cannot still be accepted; do not resubmit.
- Latest-operation reads include an exact `used_run_id` lookup. This does not
  depend on the first 50 history rows. A used plan remains unconfirmable after
  navigation/reload. A new completed generation is required for reconciliation.
- A stale RUNNING row after a process/host crash remains uncertain. Neither
  missing counters nor missing delivery is evidence of zero writes. History
  counters represent recorded plan operations, not independently verified applied
  object counts.

## Acceptance order after a separately approved release/update

1. Keep automatic sync **off** for ESXI-CM-QA. Confirm the installed release and
   open its source by stable ID `esxi-5a1a57f31ec141ab97ec`. Do not change identity,
   credentials, target placement or ownership as a repair technique.
2. Inspect both retained Runs: `70d86e6c-d746-40a6-bf04-f42de1ff1512` and
   `012f9293-a6aa-4961-b250-c0534d1e7967`. Expect unknown outcome, not success and
   not a confirmed zero. Old rows cannot retroactively gain missing diagnostics.
3. Have the NetBox operator inspect currently retained device/VM/interface/MAC/IP
   ownership and relations read-only. The confirmed 116 VMs are a historical
   observation, not an assertion about the current total. Record counts and safe
   identifiers privately; do not paste tokens or full infrastructure responses.
4. Build a **new** read-only plan. Check source, target, time, unique targets,
   create/update operations, conflicts and unsupported categories. Inspect
   parent-grouped network changes. Stop on unexpected duplicates, ownership
   conflicts, a stale plan or any new planning failure; do not force apply.
5. Only if that residual plan is understood, separately confirm it once. Follow
   the Run link while it is running. On lost HTTP response, reload/read that Run;
   do not reuse the request/token. On uncertainty, stop writes and return to step
   3. On a confirmed terminal success, build another plan and verify convergence
   without performing an empty apply. Unsupported host networking is separate
   from create/update and must not be treated as a pending write.
6. For ESXI-AM-QA2 and ESXI-PAM-QA perform read-only Build plan first. If it fails,
   record the operation/event UUID, safe code and installed version. Correlate
   that UUID in discovery-worker output. Do not proceed to apply on a failed plan.
7. For any fresh apply failure correlate the public event UUID and Run UUID in
   apply-worker/API output. Retain only allowlisted diagnostic fields: code,
   phase/stage, exception_class, duration_ms, repository frames, child returncode/
   termination, HTTP status/method/endpoint. A receiver-loss entry is secondary.
   If no terminal Run exists, report that explicitly; do not infer rollback.
8. Check reload/login, header/history/Sync agreement, EN/RU, keyboard use, and
   source list at 1024/1280 px. Confirm genuine AUTH_REQUIRED signs out, while
   AUTH_UNAVAILABLE keeps non-secret form state. Secrets must be re-entered after
   a connection check; they are never persisted in browser storage.
9. Rehearse Add source without registration first: check address/DNS before
   credentials, explicitly permit a blocked exact destination, then test TLS and
   credentials. Choose site/cluster/type; incompatible choices explain why they
   cannot be selected. Review placement before final confirmation. Registration
   repeats the server check and leaves automatic synchronization off.
10. Existing scheduled ESXi/Proxmox should be observed separately after the
    recovery decision. Do not enable schedules as part of recovering an unknown
    manual operation. No live scheduled success is inferred from local fixtures.

If deeper diagnostics are needed, share the allowlisted event records rather
than full `docker inspect`, process environments, Docker env files, HTTP bodies
or raw logs that might contain unrelated historical data.

A retained OUTCOME_UNCERTAIN/PARTIALLY_APPLIED Run still blocks placement changes
and source removal under the existing lifecycle contract, even after a fresh
residual apply succeeds. This change deliberately does not erase history, relabel
that earlier attempt or add an administrative override. A separately designed
reconciliation/acknowledgement capability is needed to clear that lifecycle
barrier; never edit the database to work around it.

## TLS and remaining product limits

Use a source hostname present in the certificate SAN and its complete chain from
a CA trusted by the standard image. Correct a mismatched name or broken chain on
the source; do not globally disable verification. The optional **NetBox** CA is
not a provider-CA configuration. A dedicated supported private-provider CA mount/
upload is not implemented by this UX change; operators needing that must request
that capability rather than edit a running container or assume a NetBox CA helps.

Changing an existing source's address/credential is not supported through the
current web backend. Configuration now states this limitation explicitly; there
is no placeholder control or remove/recreate recommendation. Display-name and
mapping edits keep their existing supported server paths and stable Source ID.

Plan grouping is a presentation of the exact returned plan, not an independent
inventory. Parent names resolve where the plan includes the corresponding object
or named reference; technical details retain the original canonical operation.
Filters never change what confirmation submits. Deleted-source history falls
back to its retained stable ID when the current registry has no display name.
