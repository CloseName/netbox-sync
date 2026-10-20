# Structural refactoring completion — 2026-10-20

The planned structural pass is complete through PR #42, based on main
`d64cf3f3a30faef2b6414bb587bb88b50527aab3`. This document closes the remaining
stages listed in [the incremental plan](refactoring-plan.md). It does not claim
that every possible cleanup or existing defect has been eliminated.

## Delivered changes

| PR | Responsibility |
| --- | --- |
| [#39](https://github.com/CloseName/netbox-sync/pull/39) | LXC target preparation and inventory |
| [#40](https://github.com/CloseName/netbox-sync/pull/40) | Separate VM/LXC preflight, precheck reports and writes |
| [#41](https://github.com/CloseName/netbox-sync/pull/41) | Host/LXC planning and scoped disappearance reporting |
| [#42](https://github.com/CloseName/netbox-sync/pull/42) | Proxmox QEMU/LXC network and disk discovery components |

Every code stage added characterization tests before extraction, then ran focused
and complete Python suites before merging. Exact output and payload fixtures are
read-only during tests. AST round-trip checks independently compared moved bodies
with their original functions. Existing helper aliases/callbacks and error classes
remain available to callers. Thirty-five additional tests were added after #39.

## Where to change code

| Area | Entry/orchestration | Responsibilities |
| --- | --- | --- |
| CLI | `netbox_sync/__init__.py`, `entrypoint.py` | Entrypoint compatibility, mode dispatch, output and process control |
| Sources | `source_bootstrap.py`, `sync_execution.py` | Connection/discovery dispatch and ordered execution |
| VM apply | `netbox_vm_apply.py` | `vm_apply_inventory`, `vm_apply_preflight`, `vm_apply_report`, `vm_apply_writes` |
| LXC apply | `netbox_lxc_apply.py` | `lxc_apply_inventory`, `lxc_apply_preflight`, `lxc_apply_report`, `lxc_apply_writes` |
| Host apply | `netbox_apply.py` | `host_apply_targets`, `host_apply_preflight`, `host_precheck_report`, `host_apply_writes` |
| Network apply | `netbox_vm_network_apply.py`, `netbox_lxc_network_apply.py` | Separate VM/LXC inventory, preflight, reports and writes |
| Host planning | `netbox_planner.py` | `host_plan_targets`, `host_plan_report`; existing network matching helpers |
| Guest planning | `netbox_vm_planner.py`, `netbox_lxc_planner.py` | VM matching/details; `lxc_plan_container`, `lxc_plan_report` |
| Network planning | `netbox_vm_network_planner.py` | `vm_network_plan_*` inventory, matching, MAC/IP/VLAN/primary/report helpers |
| Disappearance | `netbox_disappearance.py` | `disappearance_inventory`, `disappearance_identity`, `disappearance_report` |
| Proxmox | `proxmox_discovery.py` | `proxmox_components` converts distinct QEMU/LXC network/disk representations |
| ESXi | `esxi_discovery.py` | Existing staged SDK reads in `esxi_inventory`, conversion and separate host network/neighbor modules |
| API | `api/app.py` | Previously separated route groups and request/error boundaries |

Module names without a path prefix are under `netbox_sync/`. Function length alone
is not a reason for another extraction: network preflight/write modules already
represent ordered safety policies, while API registration functions contain nested
routes. ESXi already separates reads and conversion; its SDK/property-collector
contracts were reviewed and retained rather than unified with Proxmox.

## Compatibility that remains intentional

- VM application sorts workloads and aggregates blocked prechecks; LXC retains
  input order and immediate refusal. Native Virtual Disk records suppress VM
  aggregate `disk` updates. Confirmation remains before every write stage.
- VM and LXC target/cluster reads differ. LXC still derives its target list from
  one global VM read and does not add VM-style cluster-type validation.
- Network ownership, primary IP/MAC policies, prefix handling and planner/apply
  conflict semantics remain separate. A planning conflict does not become a write.
- Disappearance is scoped by source and instance; missing objects are retained.
  Missing guests suppress redundant per-interface warnings.
- QEMU guest-agent address discovery and ISO exclusion differ from LXC static
  addresses and mount points. Existing malformed-input behavior is unchanged.
- Selectel remains [experimental](selectel-status.md). No feature acceptance,
  source synchronization, live writes or production deployment occurred.

## Script and documentation audit

Reviewed package entrypoints, Docker build definitions, CI/CD definitions, systemd
units, shell wrappers, deployment/test tools and their references in tests/docs.
No files were deleted based only on age, naming or lack of a direct Python import.

| Group | Decision and evidence |
| --- | --- |
| `scripts/run-scheduled-sync.sh` | Retain: systemd service and scheduler/shared-lock tests use it; owns the scheduled lock boundary. |
| `scripts/run-full-sync.sh`, `legacy_*` modules | Retain explicit legacy compatibility; CLI wrappers, legacy mode docs and shared-lock tests refer to them. |
| `deploy/install.py`, `compose.py`, `backup.py`, `auth.py` | Retain canonical install/operation/restore paths, referenced by runbooks and deployment/backup scenario tests. |
| `deploy/source_network_diagnostic.py`, network checks | Retain operator diagnostics with explicit tests and runbook use. |
| `deploy/update-*.sh`, Selectel test/audit scripts | Retain reviewed operational/historical procedures. They are not automatic cleanup candidates and were not executed. |
| `deploy/pfsense`, `deploy/netbox_guard` | Retain runtime integrations copied or installed by documented deployment paths; separate from CLI package discovery. |
| `tools/selectel_audit` | Retain experimental offline/audit tooling; Dockerfile.web copies it and 102 local tests pass. |
| `migrations`, guard migrations | Retain upgrade/recovery history; no migration rewritten or removed. |
| Dated audit/acceptance/progress Markdown | Retain historical evidence with stable links; [documentation map](README.md) distinguishes it from maintained contracts. |

The console script is still `netbox_sync:main`; package discovery includes only
`netbox_sync*`. The inspected Forgejo CD publishes on tags, not main pushes.
No tags/releases were created and no deployment script was run.

## Verification

Windows, Python 3.14; local test doubles, no live provider credentials:

| Check | Result |
| --- | --- |
| Full Python suite after #40 | 2012 passed, 485 skipped, 1 warning |
| Full Python suite after #41 | 2025 passed, 485 skipped, 1 warning |
| Full Python suite after #42 | **2030 passed, 485 skipped, 1 warning** |
| `tools/selectel_audit` | **102 passed** |
| Frontend unit tests | **93 passed** |
| Frontend typecheck/build | Passed; existing bundle-size warning |
| Chromium browser suite | **367 passed**, no skips; 8.1 minutes |
| Error/fatal lint on changed modules | Passed |
| Wheel build and content check | Passed with isolated build dependencies; all Python modules, `public_errors.json`, unchanged console entrypoint included |

The browser suite uses local Vite and intercepted API fixtures. Frontend code was
unchanged throughout these stages, so the complete browser result applies to the
same frontend tree at the final revision. The wheel was built locally, not installed
on a server or uploaded. The Python warning is the existing Starlette/httpx
deprecation warning. Platform, database and opt-in integration skips remain skips;
these results do not constitute Linux/PostgreSQL/live-NetBox acceptance.

### Existing findings outside this structural pass

1. **Full-project lint is not green.** The documented full lint command scores
   7.70/10 both at baseline #39 and after #41. Comparing normalized Error/Fatal
   findings yielded no new errors (183 baseline, 179 after #41). Existing Windows
   incompatibilities include `fcntl`, `os.geteuid`, `O_NOFOLLOW` and `O_DIRECTORY`,
   alongside other pre-existing findings. Changed Proxmox modules subsequently
   passed their Error/Fatal check. Do not represent scoped lint as a green CI gate.
2. **Host planning with no existing cluster** prints a create-cluster plan, then
   reaches guest planning with `None` and raises `AttributeError`. A before/after
   fixture records this existing behavior. Fix in a separate behavioral change.
3. **Selectel acceptance remains incomplete.** This pass does not resolve its
   matching/import uncertainty or enable production use.

Further work should be driven by a concrete defect, feature or maintenance need,
not by continuing the same extraction sequence indefinitely.

## Follow-up: missing-cluster planning fix — 2026-10-20

The missing-cluster finding above is resolved by a separate behavioral fix.
VM-network and LXC planners now follow the existing VM planner contract: print
`BLOCKED target cluster does not exist` and return before reading guest inventory.
Host planning still prints the proposed cluster creation and continues reporting
all hosts; it does not create the cluster or write any objects. Existing-cluster
plans retain their exact output fixture.

Four regression cases were run first: the existing VM case passed and the two
missing guards plus multi-host orchestration failed. After the fix all four pass,
and the 13 planning/report contracts pass. The previous failure fixture was
updated to require successful, read-only completion rather than catch an error.
