# Scheduled Proxmox parity and failure diagnostics

## Incident and certainty

Baseline: `7d052005c13c48439bb94dfcfeb73ebdbd86b7eb`.
Reported scheduled Run `5e0b333b-8571-4bf6-a432-ecb93c7588fe` ran from
2026-09-15T18:59:23.546421Z to 18:59:35.290577Z and failed with RequestError.
Manual Proxmox and ESXi apply/replan succeeded on the operator's installation.
No connection to that installation or any live provider was made for this review.
The original response/status/endpoint is still unknown. In particular, neither
Proxmox permissions nor a particular live HTTP status has been established as
its cause.

Two local defects are confirmed:

1. Scheduled Proxmox full sync invoked `_load_nb_objects` before the shared
   planner. This legacy loader fetches global devices, VMs, interfaces, MACs,
   prefixes, IPs, VLANs, **virtual disks**, and tags. Manual full sync does not
   invoke it. An unrelated denied/unavailable endpoint can therefore fail only
   scheduled Proxmox. ESXi returns before this loader, explaining an asymmetry
   in the implementation, not proving the live incident's exact cause.
2. `orchestrator.run_sources` discarded the exception context, leaving only
   `RequestError: source execution failed`, no stage or correlated HTTP details.

The regression completes manual plan/apply/replan against real pynetbox and a
strict local HTTP server with existing host, QEMU, LXC, interfaces, MACs and IPs.
The fixture deliberately refuses Virtual Disks with 403. Before the fix,
`execute_discovered_source` fails at `_load_nb_objects: virtual_disks.all()`;
manual sync succeeds and replan has no CREATE/UPDATE. The old production image
also reproduces this through the actual one-shot scheduler Compose service.
**403 is a controlled fixture response, not a claim about the reported server.**

## Path comparison

| Boundary | Manual production workers | Scheduled production entrypoint |
|---|---|---|
| Source configuration | Registry record, immutable child payload | Same registry conversion, eligible fixed-tick sources |
| Source credentials | Supervisor resolves source-scoped files and passes bounded stdin to child | Scheduler resolves the same registry references from the read-only source-secret mount |
| Proxmox discovery | ProxmoxAPI + discover_hosts, configured port/TLS, normalized token name | Same SDK/discovery, configured port/TLS and token-name normalization |
| ESXi discovery | EsxiClient session + discover_hosts | Same client/session/discovery |
| NetBox token | Discovery/plan uses read; prepare/apply uses apply token from durable bootstrap | Full apply uses apply token from the same durable bootstrap |
| NetBox client/TLS | pynetbox.api + configure_session | Same; verification remains enabled, additional NetBox CA unchanged |
| Plan | build_runtime_plan, canonical inventory and mutation ordering | Same; now reached without the unnecessary legacy preload |
| Apply | Fresh recomputation/digest confirmation; preflight and provider executor | Fresh plan for each due run, refuses blocked plans, provider executor with its global prechecks; no reuse of browser confirmation |
| Lock | apply-worker flock on shared host-backed inode | Host run-scheduled-sync.sh takes the same inode before Compose run |
| Output/history | Long-lived workers/child protocol, manual Run | One-shot scheduler stdout/stderr goes to systemd journal; scheduled Run is created before source execution |

No source permission expansion is part of this fix. Read/apply token visibility
on the live NetBox remains unverified; successful manual apply does not justify
adding unrelated endpoint permissions to compensate for the legacy preload.
Normal full sync now branches before `_load_nb_objects`; legacy inventory/partial
CLI paths retain their existing behavior. Full sync's required NetBox reads and
all ownership/conflict checks remain active. A denied required devices read is
still a failed run, not an empty inventory. No write retry was added.

## Diagnostic contract

Each source failure emits one JSON line on stderr with event `SCHEDULED_FAILURE`:
- exact persisted `run_id` (null only for non-persistent orchestration callers);
- closed `stage`: dispatch, credentials, provider, netbox, legacy_read, planning, apply;
- exception class and at most eight repository-only function/module/line frames;
- optional HTTP numeric status, allowlisted method and allowlisted endpoint name;
- `write_outcome`: NOT_STARTED before full execution enters apply, otherwise
  MAY_HAVE_WRITTEN. The latter includes errors in apply's internal prechecks;
  it is deliberately conservative, not a claim of confirmed mutation.

HTTP details are read only from structured exception/response metadata. No
exception messages, response bodies, request URLs/query strings, headers, local
variables, tokens, payloads or arbitrary paths are logged. A bounded explicit
cause chain may supply HTTP metadata; its free-form text is never serialized.
If the request metadata is unavailable, a field is omitted instead of guessed.
The one-shot scheduler suppresses old executor object dumps; bounded source/tick
summaries and structured failure diagnostics remain. Stages are reset per source.

A plan digest/version already computed before failure is retained in Run History.
Counts are not an acknowledged-write ledger: default zero counts and absent
digest are **not evidence that no write occurred**. Failed runs retain their
existing closed public error/status contract; inspect the correlated journal
record for the phase and possible-write boundary. No UI or DB migration is added.

## Operator follow-up after a separately approved update

Use the established [upgrade runbook](source-sync-upgrade-runbook.md); no current,
credentials, volume or onboarding changes are needed for diagnosis. Publishing,
installation and service actions remain separate operator decisions. Do not
force repeated syncs merely to obtain more error output.

After the next operator-approved/normally scheduled run, read only the new safe
records from the one-shot service journal:

```sh
sudo journalctl -u netbox-sync.service --since today --no-pager -o cat \
  --grep 'SCHEDULED_FAILURE'
```

Match `run_id` to the failed scheduled Run in the UI and retain the installed
release SHA, stage, exception class, frames, HTTP status/method/endpoint and
write_outcome. Share that bounded record, not Docker env, token files or raw
HTTP debug logs. Do not enable HTTP wire logging. The old September 15 run
cannot acquire new diagnostics retroactively. If only historical evidence is
available, an operator may supply already-sanitized NetBox request metadata for
that exact time window; this review does not require or authorize live access.
If MAY_HAVE_WRITTEN, reconcile current NetBox state through a fresh reviewed
plan before deciding whether further execution is safe. Do not infer no changes
from the failed run's action totals.

## Verification

- Before fix: real HTTP regression failed in `_load_nb_objects` at
  `virtual_disks.all()`; the old production image reproduced manual success
  followed by scheduled RequestError. Baseline Docker gate: **1 passed**
  (expected failure asserted), 122.56 s, bundled PostgreSQL.
- Final focused Python subset: **44 passed**, 6.82 s. Includes required-read
  errors, safe cause metadata, log redaction, per-source context reset, blocked
  plan refusal, and actual HTTP PATCH 503 with exactly one write attempt and
  retained plan digest/version. Partial CLI scope also marks possible writes.
- Final full Linux backend + isolated PostgreSQL: **1028 passed, 26 skipped**,
  84.04 s; two existing dependency deprecation warnings.
- Final production Compose scheduler/full-worker gate: **2 passed**, 247.68 s,
  bundled and external PostgreSQL, external ingress. Both providers complete
  manual create/apply/empty-replan followed by successful scheduled no-op.
  Proxmox required-read refusal emits the exact persisted Run ID, planning stage,
  RequestError, frames and GET/dcim.devices/403; no raw response or token appears.
  After test endpoint recovery a distinct scheduled tick succeeds. The bundled
  populated installer upgrade also preserves exact source/config/credential
  snapshots, onboarding READY/policy, PostgreSQL container and mount metadata.
- `git diff --check` passed. Test containers/networks/volumes were cleaned by
  exact unique ownership labels. No push, deployment or live connections.
- Docker Engine 29.7.2 Linux, Compose 5.5.0. Built image:
  `sha256:b21cd6e1596ca99e7603765d63a2d21f1c17e1b37355398672b87ef339e8b907`.
  Dockerfile.web builds successfully; TypeScript/Vite pass (unchanged 525.78 kB
  bundle advisory). UI source was not modified; browser/visual suites were not
  repeated for this backend-only change.

General Linux runner skips (not silently counted as successful tests):

| Group | Count | Disposition for this change |
|---|---:|---|
| auth Compose / probe Compose | 4 | Same runtime harness, executed separately through the two auth variants with full worker/scheduler flag |
| auth historical upgrade | 1 | Unchanged pre-auth upgrade opt-in; populated current installer upgrade remains part of bundled runtime gate |
| clean Debian backup | 2 | Unchanged host backup opt-ins, not rerun |
| backup Docker / dedicated PostgreSQL | 2 | Unchanged dedicated opt-ins, not rerun; existing auth harness still exercises its backup/restore path |
| container naming Docker / naming PostgreSQL | 3 | Unchanged naming migration, not rerun |
| deployment PostgreSQL | 6 | Dedicated deployment DSN not configured; actual production grants/bootstrap exercised in both runtime variants |
| deployment foundation / external ingress rendering | 3 | Docker CLI absent in general Linux runner; actual production Compose configuration is validated in runtime harness |
| production proxy / dedicated TLS smoke | 4 | Unchanged proxy/TLS opt-ins, not rerun; external ingress is used by actual runtime gate |
| live ESXi | 1 | Explicitly prohibited; no live endpoint/credentials used |

The previous full-worker gate missed this defect because it exercised the Web
worker entrypoints, not the one-shot scheduler's Proxmox branch. The in-memory
catalog also allowed every legacy endpoint. This change adds a strict denied
legacy endpoint and the real scheduled entrypoint **after** manual create/apply
and empty replan. No-op claims use the HTTP write-attempt ledger and unchanged
fixture state, not just plan counts. The runtime fixture has two Proxmox hosts,
one QEMU and one LXC; it represents object/network relationships, not the live
27-workload dataset.

The production fixtures are controlled HTTPS/SOAP/REST, not live hypervisors or
a full NetBox distribution. Runtime uses the product SDKs, built image, actual
production Compose service command/env, real PostgreSQL and source-secret files.
The test CA is the only scheduler service override; no scheduler entrypoint,
network/capability setting or product logic is replaced. The test invokes the
same host flock + Compose command as the wrapper; systemd/reboot itself is not
exercised. Resources have unique exact project labels; only owned resources are
cleaned. The Docker socket exists only in the local operator test container.

Security boundaries remain unchanged: broker network_mode:none, private DB/API,
private workers, no product Docker socket or systemd access, shared apply lock,
source isolation and read-only credential mounts. External PostgreSQL and
external ingress are covered by the existing production harness variants.
