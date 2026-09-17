# Live audit follow-up

Base: `8b656dac0a0c15f66a5a6e7cac0405e614272da1`, main, canonical
`https://github.com/CloseName/netbox-sync.git`. Initial tree was clean. Work stays
in `E:/Codex/Project/netbox-sync`; the historical checkout was not changed.
No push, deployment or live infrastructure connection.

**Mandatory local worker runtime and presentation gates passed. Live acceptance remains separate.**

## Requirement / implementation / evidence

| Requirement | Implementation and evidence | Boundary / remaining acceptance |
|---|---|---|
| Preserve preceding UX/RBAC work | Base commit, `docs/ldaps-ux-acceptance.md`; full browser suite retains auth/LDAP/settings/expired-result cases | Real 401 still signs out; an outage is not relabeled as expired login |
| Broken reply must not kill worker | `apply_worker.serve` catches delivery OSError; real Linux Unix-server regression follows disconnected apply with health request | Does not explain original earlier uncertainty |
| Useful PLAN/apply failure evidence | `worker_failure`, `source_operations`, discovery/apply child handling: allowlisted class/frames/phase/duration/exit/HTTP; correlated IDs | Original live initiating exceptions remain unknown; no raw messages or payloads |
| Durable acceptance, no replay, reconcile | Bind Run digest before child, exact `plan_run`, `used_run_id` projection, client-known UUID, existing lock/confirmation/generation fences | Fresh residual plan and separate confirmation; never automatic writes |
| Truthful counters and coherent views | Unknown zero-filled failure counters; explicit prewrite distinction; persisted Run recovery, header refresh, used-plan fence, shared timestamp clock | Counts are plan operations, not independently confirmed applied totals |
| Readable plan/no-op | Unique mutation targets plus operation counts; network parent groups; raw original row in details; distinct provider/NetBox kinds; unsupported filter | No-op does not erase unsupported or real blocking evidence |
| Optional Discovery | Healthy inventory collapsed, active/failed/expired evidence visible; all rows still accessible | Retains earlier neutral-expiry behavior |
| Address before credentials | Dedicated secret-free address/DNS policy precheck in existing isolated probe; explicit allow remains separate | Full probe rechecks current revision/address and pins DNS; precheck is not authentication |
| Placement before confirmation | `receipt.check` validates session/revision without consuming; read-only fresh catalog validation; registration revalidates | No provider or NetBox credentials in API; no new egress/mount/grant |
| Wizard readability | Preserve non-secret fields, positive auto-sync Off confirmation, readonly reviewed port, edited full cluster suggestion, incompatible cluster explanation, early catalog token requirement | No automatic schedule enable or catalog creation |
| TLS / existing connection edits | Explain hostname and standard-image trusted chain; existing connection editing limitation explicit | Private provider CA upload/mount and address/credential web editing remain separate product gaps |
| Source/history/diagnostics layout | Compact source columns, advanced filters with count, one-page pagination hidden, source names/address search with deleted-ID fallback | Exact identities and existing deep links retained |
| EN/RU/theme/accessibility | Translation regression, full Playwright including roles, keyboard, 390–1440 px and 200% zoom | Screenshots are local fixtures, not live proof |

## Verification evidence

- Intermediate full Linux backend: **1003 passed, 105 skipped**, 109.70 s.
  Networkless `netbox-sync-ldap-tests:review` image, source bind read-only.
- Latest affected Linux backend/API/transport: **100 passed**, 9.34 s.
- Separate PostgreSQL after row-factory correction: **39 passed**, 13.61 s;
  source operations, durable Linux worker, run history, auth and lifecycle. Unique
  networkless PostgreSQL container; test runner shares only its network namespace;
  no host ports; exact test label checked before cleanup.
- Final full browser suite: **264 passed**, 4.4 minutes, including four added
  light/dark plan variants. Earlier complete run: 260 passed before those additions.
- Final frontend units: **70 passed**. TypeScript and Vite build passed; existing
  bundle-size advisory remains (563.88 kB main JS before compression).
- Docker Engine **29.7.2 Linux**, Compose **5.5.0**.
- Actual production Compose bundled/external PostgreSQL: **2 passed**, 315.13 s.
  `NETBOX_SYNC_AUTH_DOCKER_TEST=1`, `NETBOX_SYNC_WORKER_FULL_SYNC_TEST=1`,
  `NETBOX_SYNC_BROWSER_FULL_SYNC_TEST=1`,
  `python -m pytest tests/test_auth_compose_docker.py -q -s --tb=short --show-capture=no`.
  Production image `sha256:9f71cc54b5fae8a03ef512e62397ed8a6891c49fb59531a0a8e20e354c2c6342`;
  final subsequent UI-only changes are reason-label precedence, RU copy, column
  width and visual-test theme coverage. No runtime/backend change followed this gate.
- Both production modes exercise real API/isolated workers and HTTPS fixtures:
  address policy, placement rejection, Proxmox VM/LXC and ESXi inventory,
  plan/prepare/apply/replan, nonstandard port 8443, real browser confirmation,
  scheduler after manual convergence with no new writes. The bundled mode also
  exercises installer component upgrade preserving onboarding, credentials and
  the existing DB container/volume. These are local fixtures, not live hypervisors.
- Controlled required-read PLAN refusal records correlated UUID/class/HTTP/frames.
  Controlled third-write ESXi failure retains earlier objects and durable uncertain
  Run/digest, refuses replay/old-plan preparation, then converges using a separately
  confirmed fresh residual plan. Historical uncertainty remains in history and
  continues to block placement under the existing lifecycle contract.
- Real Linux Unix-socket tests cover a disconnected recipient after both success
  and failure; the same server answers a subsequent health request. Unexpected
  supervisor failure also returns a correlated event without raw exception text.
- Resource cleanup is limited to unique project labels (including restore project).
  No Compose-labeled containers, networks or volumes remain after this run. Production socket/mount/
  network definitions are unchanged: broker networkless, private DB/workers,
  API without provider credentials or provider egress, shared apply lock retained.

Failures found during verification were not counted as successful gates:
address-precheck omitted policy revision; exact Run lookup initially assumed a
positional row; ESXi fixture originally had no NIC and never reached its intended
third-write failure; old tests expected intentionally removed pagination and raw
counter labels. The strengthened SOAP fixture now includes VM NIC/MAC/IP.

## Separate gates and limits

The networkless full backend skips PostgreSQL DSNs, opt-in Docker/deployment and
privileged clean-Debian host tests, and live ESXi/NetBox tests. Affected persistence
is executed separately above, and production Compose separately below. Naming,
backup/restore, unrelated host installer and historical upgrade suites were not
rerun merely to eliminate unrelated skips: no corresponding product changes here.
Live tests remain prohibited in this task, not silently counted as passing.

See [future live acceptance](live-audit-acceptance.md), starting with read-only
reconciliation of the partially written ESXI-CM-QA source. No claim of successful
live ESXi synchronization or fixed original live planning cause is made.


## Visual evidence

Current local Playwright artifacts (ignored by Git; fixture data only):

- `frontend/test-results/sources-1024.png`: all source status/action columns fit.
- `frontend/test-results/live-audit-grouped-en-light-1280.png`: 120 operations,
  parent grouping and unchanged/unsupported counts; first 50 rows plus explicit more.
- `frontend/test-results/live-audit-plan-ru-dark-390.png`: narrow RU unsupported
  explanation, distinct from changes, with no horizontal document overflow.
- Companion `live-audit-{grouped,plan}-{en,ru}-{light,dark}-{390,1280}.png`
  files cover both languages and themes. These are generated by
  `frontend/e2e/live-audit.spec.ts`; they do not contain credentials.

The 1024 px list, EN grouped plan and narrow RU dark explanation were also
visually inspected after the final copy/column changes.

Final `git diff --check` passed. Existing previous commits are preserved.
