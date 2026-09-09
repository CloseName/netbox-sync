# Frontend foundation (UI-0 through UI-5)

The React application uses React Router in declarative BrowserRouter mode.
Routes: Overview `/`, Sources `/sources`, registration `/sources/add`,
source `/sources/:sourceInstance`, Runs `/runs`, run `/runs/:runId`,
and Diagnostics `/diagnostics`. Add Source is an action within Sources.
Settings is intentionally absent. Source detail and scheduling are organized into
source sections below. Runs and Diagnostics use the existing read-only contracts;
registration retains its existing workflow.

FastAPI serves the same built index only for the explicit frontend paths.
Unknown API routes, missing assets and unknown frontend paths do not fall back
to HTML. Vite provides the local development fallback. No API DTO or privilege
changes were made.

Overview independently reads sources, diagnostics, and the latest 50 runs.
It shows eight recent runs, up to five source attention items, up to three stale
record links, and five next-expected schedules. Running counts cover only the
returned recent records. Stale counts cover only the returned diagnostics
selection (currently limited to 100); neither is a global live total.
Provider connectivity, persisted snapshots, changes-waiting and applied-in-24h
metrics are not inferred. Expected schedule timestamps are not guaranteed starts.

Sources joins the full configuration list to diagnostics by exact source_instance.
Diagnostic projections are used only when registry and history checks are healthy.
Unavailable diagnostics never remove configuration rows or imply healthy status.
Source enabled, automatic sync, recorded outcome, and attention remain distinct.
Attention is derived in priority order: uncertain/partial, unhealthy/unavailable,
stale, delayed, failed/blocked/locked outcome, other reported warnings.

Sources search, provider/health/schedule/attention/site filters, sort/direction,
page and 25/50/100 page size live in URL query parameters. Filtering and pagination
apply to the complete returned source list, not to a partial run selection.
Source links preserve the originating query in browser history state.
Client-side operation is verified with 105 unit-test rows and 125 browser-fixture
rows. At several hundred sources, measure payload, join/render time and diagnostics
query latency before increasing scale. Server-side filtering/pagination and explicit
coverage metadata are follow-up backend work, not claimed by this UI.

Resources retain successful data on failed refresh and display its received time.
Requests have a 15-second client timeout, unmount cancellation, and no automatic
refresh or write retry. An aborted HTTP request does not promise server cancellation.
Source components are remounted by route identity to isolate in-flight local results.

Shared UI files under src/ui own health/schedule/outcome labels, attention/query
derivations, human date/duration formatting, primitives and light/dark theme tokens.
Unknown is neutral. Technical enums remain available as titles or technical details.
Light/Dark/System preference and its verification are documented in UI-5 below.

Validation:
- `npm test`: existing API client tests and deterministic projection tests.
- `npm run typecheck`, `npm run build`.
- `npx playwright install chromium`, then `npm run test:e2e`.
- Browser tests intercept every API call; only local Vite is started, with no
  provider, NetBox, registry, or production connection. Screenshots go to ignored
  test-results at 1440/1280/1024/768 widths.
- `python -m pytest tests/test_frontend_routes.py tests/test_api_health.py`.
- Build Dockerfile.web with a local Docker daemon before release.

The shell includes a skip link, route breadcrumbs, active navigation, route focus,
native controls, labeled filters, sortable table headers, controlled table overflow,
and reduced-motion rules. Browser checks cover navigation, direct refresh, basic
keyboard access and overflow; they are not a WCAG conformance certification.

## Source Detail and Schedule (UI-2)

Pre-implementation baseline: `e5f797020837e98c8eabdb4249245a504dbdd10c`
(the full tested UI-0/UI-1 baseline is recorded in git history). The old detail page
combined configuration, raw-second scheduling, Discovery and Plan/Sync in one
vertical view. Runs already supported a source_instance filter, and diagnostics
already projected per-source activity. No new API data contract was needed.

Source sections are addressable links:

| Section | Route | Content |
| --- | --- | --- |
| Overview | `/sources/:sourceInstance` | Activity, schedule, target and attention |
| Sync | `/sources/:sourceInstance/sync` | Existing read-only Discovery, exact Plan and manual result |
| Runs | `/sources/:sourceInstance/runs` | Latest 50 records filtered by exact source_instance |
| Schedule | `/sources/:sourceInstance/schedule` | Schedule evidence and human-readable editing |
| Diagnostics | `/sources/:sourceInstance/diagnostics` | Source-only status, warnings, activity and evidence time |
| Configuration | `/sources/:sourceInstance/configuration` | Read-only identity, connection, target, provider mapping and TLS |

The source route wrapper is keyed by sourceInstance, while all section links use
one shared source component. Source configuration, schedule and diagnostics are
loaded once per source entry, not on each tab click. Source breadcrumbs and the
document title use the loaded display name. Unknown sources and temporary API
failures have separate states; retry preserves the URL.

Sync and Schedule remain mounted but hidden outside their sections, preserving
local results and edits across sibling tabs. Leaving the source discards that local
state. Read requests ignore late responses after unmount; schedule writes also
check component lifetime before publishing results. They cannot update a newly
mounted source, including a later visit to the same ID. HTTP cancellation does
not cancel work already accepted by the backend. No automatic write retry occurs.

Discovery is optional and makes no NetBox changes. Build Plan remains independently
available. UI-2 retained the original confirmation prompt, shared apply lock and
stale-plan protection. UI-3 replaces the prompt and review presentation below
while preserving the backend protocol.

The header separates source enabled, automatic sync, last run, last success and
attention. Registry enabled is configuration, not provider health. Diagnostic
status is evidence from persisted records, not a connectivity or authentication
check. UNKNOWN is shown as Not verified; unavailable evidence never implies
success. Schedule and diagnostics can have different observation times; Diagnostics
labels its scheduler value as being at evidence time. Running outcomes say
Recorded as running. Source-level stale warnings do not prove that a particular
latest run is stale. Diagnostic warnings remain visible separately.

Source Runs requests `/api/v1/runs?source_instance=...&limit=50`, rejects foreign
source rows, and links to existing global run details. It is an explicitly bounded
recent list, not all-time history. Action counts describe the recorded plan, not
confirmed applied objects. Source Diagnostics links to system diagnostics instead
of copying global components. Configuration never exposes credentials and keeps
legacy ownership and stable identity in its advanced section.

### Human-readable schedules

Read mode shows On/Off, exact human frequency, recorded scheduled outcome/time,
derived scheduler state and next expected time. Expected is not guaranteed; the
API does not provide a live scheduler heartbeat.

Presets: 5, 10, 15, 30 minutes; 1, 2, 6 hours. Other stored values open as Custom,
with Seconds / Minutes / Hours. Existing values use the largest unit that preserves
an integer; 601 seconds remains 601 Seconds, and 9000 seconds displays 2 h 30 min.
Changing a unit or preset is an explicit user action. Decimal input is converted
using integer arithmetic and must produce exact whole seconds; 1.15 minutes is
69 seconds. No rounding or silent normalization occurs.

The existing contracts intentionally remain unchanged:
- Registration accepts 1..2147483647 seconds.
- Schedule updates accept 60..86400 seconds.
- Optimistic expected_sync_interval_seconds accepts the wider existing range.

Out-of-update-range values remain visible and unchanged. Editing explains the
mismatch and blocks saving until the operator explicitly chooses a supported
value. Even an enable/disable-only update must satisfy the current interval update
contract. Harmonizing registration/update validation is a documented backend
follow-up, not part of UI-2.

The editor distinguishes idle, editing, saving, saved, conflict and error. It
disables duplicate submissions, preserves inputs on failure, and sends the exact
loaded expected_sync_enabled and expected_sync_interval_seconds. A conflict
requires explicit reload; a failed reload keeps saving blocked. Reload awaits the
new response before updating the baseline. Save/read requests have a 15-second
client timeout. A transport failure may leave the server outcome unknown; there
is no automatic retry.

Enabling explains eligibility on a future scheduler cycle. Disabling explicitly
does not cancel a run that already started. A disabled source cannot run
automatically even when automatic sync is configured on.

### UI-2 validation

- 39 frontend unit tests, including exhaustive round-trip checks for every
  supported integer-second interval, plus custom units and legacy values.
- 42 Playwright tests in total: source direct routes/refresh, Back/Forward,
  keyboard links/forms, no redundant source reload between tabs, errors/conflict,
  late source/Discovery/Plan/Schedule responses and existing confirmation behavior.
- Screenshots inspected for Overview, Sync, Runs, Schedule read/edit, Configuration,
  warnings, schedule off, unusual intervals, invalid source and narrow layouts.
  Whole-page overflow checked at 1440, 1280, 1024 and 768 pixels.
- Strict TypeScript and Vite production build pass.
- 87 focused backend tests pass: frontend routes, API health/sources, scheduler
  and schedule worker. Only explicit read-only SPA entry routes changed in Python;
  no write contract, worker policy, DB migration or privilege boundary changed.
- Docker Engine 29.7.2 / Compose 5.5.0: Dockerfile.web builds successfully.
  Default Uvicorn, UID 10001, /app/web, read-only filesystem, network none, no
  mounts, credentials or published ports. Inside-container HTTP checks passed for
  /, /sources, /sources/add, /sources/test-source, all five source subroutes,
  /runs, /runs/test-run-id and /diagnostics.
- Unknown frontend/source paths, /api/unknown, /api/v1/unknown,
  /api/v1/sources/test-source/unknown and missing JS/CSS remain JSON 404.
  Served index and JS/CSS bytes match files inside the built image.
  The uniquely labeled smoke container and image were removed; no shared prune.
- git diff --check and changed frontend/documentation branding scan pass.

Browser writes use mocked APIs only. No live provider, NetBox, registry or server
was modified; no push or deploy. Deep Plan/Sync review, global Runs/Diagnostics,
onboarding and final visual polish remain deferred to UI-3 and later phases.

## Discovery, Plan and Sync workflow (UI-3)

The implementation was audited against baseline
`2b53ad05cbfbe696dc9ed0ee341818ed55480ade`. UI-3 changes only the frontend,
tests and this document. No backend DTO, write endpoint, worker, migration,
lock, ownership check or privilege boundary changed.

The Sync section at `/sources/:sourceInstance/sync` makes Build plan the
primary action. Discovery is a separate optional read-only tool. It inspects
source/NetBox matching, shows actual classification counts and exposes match
IDs/reason codes in details. Planning performs fresh reads; it does not reuse
the displayed discovery response. No snapshot history or change-since-discovery
claims are made.

### Plan evidence and counts

The audited runtime plan records guarded executor mutations. CREATE/UPDATE rows
are operations, and several operations can concern one object. Other counts are
explicitly labeled as rows. A source-kind RETAIN_ONLY row is a retention policy,
not a count of missing objects; it is excluded from numeric row totals and shown
as a safety note. Non-source retain rows can still be inspected if supplied.

Review defaults to Attention when BLOCKED rows exist, otherwise Changes.
Changes / Attention / All, action, kind and search filters affect display only.
Counts remain visible even when their rows are hidden. Rows are initially shown
in batches of 50. There are no selection checkboxes or partial-apply requests.

Expandable rows display only supplied managed-field pairs:
NetBox before -> Proposed. Missing fields say Not provided, while explicit null,
empty string, booleans and nested JSON retain their actual meaning. CREATE does
not fabricate absent-before values. A missing pair list yields no inferred diff.
Malformed or duplicate field pairs fail client validation rather than being
silently collapsed. Internal references are displayed as provided, not resolved
into invented objects. Distinct discovered-state provenance is absent from the
contract: three-way diff remains deferred.

REVIEW_REQUIRED rows are isolated by the existing guarded workflow and are not
automatically adopted as normal updates. They do not themselves disable global
apply. Only backend apply_allowed authorizes the confirmation action. BLOCKED
rows receive prominent attention, with their actual reason, and a disallowed
plan cannot open confirmation.

The UI records the response receipt time; plans have no server creation timestamp
or expiry countdown. Digests, fingerprints, schema/planner versions, external IDs
and raw reason codes are secondary details. Starting a new build marks the old
plan as previous and unusable; a failed build retains its evidence without
re-enabling apply.

### Confirmation and execution

The native modal replaces window.confirm. It shows source, target, plan receipt
time, complete plan totals and no-delete/retain-only notes. Cancel receives initial
focus; Tab/Shift+Tab wrap within the dialog. Escape and Cancel close it before
submission and return focus. Pending validation/apply disables duplicate submit
and dismissal; browser navigation still does not promise server cancellation.
An unsubmitted dialog closes when leaving the Sync tab.

The request sequence is unchanged:
1. Build a server-generated plan with an empty request.
2. Submit its exact digest and confirmed=true for preparation.
3. Keep the returned token only in the pending function scope.
4. Submit that token to apply, with the reviewed operation UUID as context metadata.

The worker re-plans before issuing and consuming the capability. The frontend
does not replace stale checks, apply_allowed, the shared lock or source/NetBox
ownership decisions. Every attempted confirmation makes the displayed plan
unusable for a second attempt; a new build and explicit review are required.
No token enters a URL, browser storage or rendered technical details.

Known phases are Building read-only plan, Preparing / validating and Submitting /
applying. Elapsed time is shown outside the live announcement; no percentages or
unreported internal stages are invented. Prepare/Apply requests have a 330-second
client response bound, longer than the current 310-second apply transport bound.
A client timeout does not cancel work already accepted by the server.

### Outcomes and uncertainty

The actual successful-response DTO allows SUCCEEDED, FAILED_BEFORE_WRITE,
PARTIALLY_APPLIED and OUTCOME_UNCERTAIN, with optional run_id. The client now
preserves those values instead of collapsing all responses into a success string.
A digest mismatch is treated as unconfirmed outcome, not success.

Stable error codes distinguish PLAN_STALE/invalid confirmations, PLAN_BLOCKED,
APPLY_LOCKED, failed-before-write, partial and uncertain outcomes. APPLY_FAILED
uses the backend's safe generic wording, Manual sync request failed; it does not
claim no changes. Generic FAILED is a history status, not an invented additional
ApplyResultDTO value. Unknown/malformed/lost responses after submitting apply
remain Outcome unknown. A failed preparation is distinct: the browser has not
submitted apply.

Partial and uncertain results remain prominent across sibling tabs and across
new planning. They direct the operator to run history/diagnostics; there is no
Retry Sync action or automatic write retry. Only a valid supplied run_id produces
Open run. The current error envelope has no run_id, so error responses cannot
offer a fabricated run-detail link.

SourceSync stays mounted across sibling tabs under the existing source-keyed
route wrapper. Late discovery/plan/apply responses cannot publish into another
source. A preparation response received after leaving the source is explicitly
prevented from launching apply. Prior results are retained during planning,
while old plans are marked unusable.

### UI-3 validation

- 42 frontend unit tests pass: exact pair handling, operation/policy counts,
  malformed data, real outcome DTOs, digest mismatch, safe error mappings.
- 68 Playwright tests pass across the frontend, including independent Discovery,
  105 unchanged rows, mixed/review/blocked plans, missing fields, unusual kinds,
  modal focus/Escape, exact token/digest bodies, duplicate clicks, preparation and
  apply races, stale rejection, response loss and persistent uncertainty.
- TypeScript strict and Vite production build pass.
- 36 focused backend tests pass unchanged: sync_plan, planning_netbox,
  manual_sync, manual_sync_web and apply_worker.
- Screenshots inspected for empty Sync, Discovery pending/result, large/mixed
  plans, review/blocked/stale, confirmation, success/uncertain and narrow layouts.
  Diff columns stack per field at 768; page overflow and dialog widths are checked
  at 1440/1280/1024/768.
- Docker Engine 29.7.2 / Compose 5.5.0: Dockerfile.web builds; default Uvicorn serves
  /, /sources/test-source, /sources/test-source/sync and the Schedule route from
  /app/web as UID 10001. Served JS/CSS bytes match the built files.
  Unknown frontend/source routes, unknown /api and /api/v1 routes and missing
  static assets remain JSON 404, not SPA HTML.
- The disposable smoke had network none, read-only filesystem and no mounts or
  published ports. Its uniquely labeled container/image were removed without
  pruning shared artifacts.
- git diff --check and changed frontend branding scan pass.

All browser mutations use mocked APIs. No real provider, NetBox, historical
server or production was touched, and no push/deploy was performed. At the UI-3
checkpoint, UI-4 Runs/Diagnostics and UI-5 visual polish remained separate work. Three-way diff,
persisted snapshots, selective apply, cancellation and progress jobs are not
introduced.

## Runs and Diagnostics (UI-4)

Pre-implementation baseline: `cc63c6a77605743b4befcfa06216657ffc335f89`.
The old Runs screen labeled null durations as in progress, called plan counters
"Changes", and discarded pagination. The old Diagnostics screen treated a
component without a safe code as Available, including UNKNOWN, and discarded
previous data after a refresh failure. UI-4 changes frontend presentation only;
API DTOs, persistence and safety boundaries are unchanged.

### Run history and detail

Runs uses the existing server filters `source_instance` (exact source ID),
`source_type`, `status`, and `trigger`, with `limit=50`. Filters and cursor
are URL parameters; changing filters resets the cursor. Results are ordered
by started_at DESC, run_id DESC. Older runs follows the returned UUID cursor;
Newest runs clears it. Browser Back/Forward restores earlier cursor locations.
A full last page can return a cursor followed by an empty response, because the
backend sets next_cursor whenever exactly limit records were returned. The UI
does not infer a total, page count or timeframe from this bounded selection.

Only the result resource remounts on query changes, preventing old-filter rows
from appearing beneath new filters while preserving filter control focus.
An editable source-ID draft is associated with its URL value; restoring a
different URL does not depend on a later effect updating the input.
Run links retain the originating list query in browser history state.
Source rows link to the canonical source route; source Runs still opens the
same global run detail. Unknown IDs and read failures offer a read retry.

Columns are Started, Source, Trigger, Outcome, Duration, Plan actions, Attention.
Plan actions describe the persisted ActionCounts.from_items projection. They are
not unique objects or confirmed applied changes, even for successful runs.
All eight counters are available in detail. A zero summary does not assert that
NetBox was unchanged. Missing duration always reads Not recorded independently
of outcome. Times reuse shared human formatters and expose exact timestamps.

The existing shared mapping remains authoritative:

| Recorded status | Presentation |
| --- | --- |
| SUCCEEDED | Completed |
| FAILED_BEFORE_WRITE | Failed before changes |
| BLOCKED | Blocked by safety checks |
| LOCKED | Not started — sync busy |
| PARTIALLY_APPLIED | Partially applied |
| OUTCOME_UNCERTAIN | Outcome unknown |
| FAILED | Failed |
| RUNNING | Recorded as running |
| RUNNING with matching stale evidence | Completion unconfirmed |

Stale presentation requires a healthy history check and matching run_id AND
source_instance in the diagnostic stale selection. It never changes persisted
status, labels a newer completed run stale, or treats a missing duration as
evidence of progress. The backend uses its configurable stale threshold
(default 7200 seconds), returning at most the 100 oldest RUNNING records.
Absence from this sample does not establish completion. The UI shows the exact
supporting sentence, safe evidence and age at the diagnostic snapshot, linking
to the run/source/system diagnostics. No Retry Sync action is introduced.

Run detail starts with outcome/source/trigger/start/duration/attention, then
plan actions, safe result message, factual Started/Finished lifecycle and
diagnostic links. A missing finished_at means no completion timestamp was
recorded; it does not fabricate stages. Uncertain and partial outcomes retain
a prominent investigation message. Run ID, recorded status, digest, planner
version, safe code, raw times and created_by live in native Technical evidence.
There is no schema version in this DTO, so none is invented.

### Diagnostic evidence

The aggregate backend status is preserved. Stale-only degraded evidence can
explain that checked components are available while historical completion is
unconfirmed; it does not become Healthy. A healthy aggregate is qualified as
a snapshot assessment, not a statement that all integrations are operational.

Compact component rows cover API, Registry, Run history, Discovery worker,
Apply worker and Scheduled activity. API/read checks and bounded worker health
responses describe what was actually tested. Worker health does not test
provider or NetBox connectivity. Scheduled activity is persisted run evidence,
not a scheduler heartbeat. UNKNOWN stays Not verified, including no scheduled
activity. Native disclosure exposes safe codes and actual evidence timestamps.

Attention combines component failures, returned stale/delay warnings and latest
source failures/uncertainty, with links to checks, runs, source diagnostics and
source schedules. It does not claim a global issue total. At 100 stale records,
the UI explicitly says that more may exist. Source assessments require healthy
registry AND history checks; partial failures never become an empty configuration
claim. Source Diagnostics reuses the attention presentation without duplicating
global components. Source header/last run/source Runs use the same exact stale
join. Overview's existing bounded dashboard is otherwise unchanged.

All screens keep previously loaded evidence on a failed refresh and expose a
read-only retry. Diagnostic warnings use generated_at, the snapshot timestamp;
history uses response receipt time because it has no snapshot timestamp.
Query changes do not retain another query's rows. No polling was added.

### Layout and remaining boundaries

Native labeled filters, semantic table headers, one h1, route links, keyboard
disclosure and visible focus continue the existing UI foundation. Plan actions
hide at 1280 and below, duration at 1024 and below; every value remains in run
detail. Tables scroll locally, with keyboard focus, while diagnostic rows stack
at 768. At the UI-4 checkpoint, whole-application visual polish remained for UI-5 (completed below).

No migrations, retries of synchronization, stale recovery, cancellation,
delete, activity persistence, credentials, totals endpoint or timeframe filter
were added. Push/deploy requires a separate explicit request.

### UI-4 validation

- 44 frontend unit tests pass. Obsolete page-source string checks were replaced
  with behavioral browser tests and pure evidence/contract checks.
- 98 Playwright tests pass across UI-0 through UI-4, including all eight outcomes,
  null durations, exact stale joins, 51-row cursor navigation, an exactly-full
  terminal page, URL restoration, empty/errors, retries, source links, and
  stale/partial/unknown/unavailable diagnostic scenarios. Refresh timestamps
  assert the actual diagnostic generated_at value. The source-filter Back race
  and retained diagnostic refresh checks also passed five targeted repeats.
- Strict TypeScript and Vite production build pass.
- 18 focused backend tests pass unchanged: test_run_history.py,
  test_run_history_api.py and test_diagnostics.py. No wider backend suite was
  required because backend contracts/code were not changed.
- Mocked state galleries cover 1440/1280/1024/768: one run, 50-row page with older
  records, filters, empty/error, uncertain/stale details, healthy/stale-only,
  unavailable worker, no scheduled activity, mixed source issues and failed
  refresh. Layout checks assert no document overflow; screenshots are retained
  in ignored frontend/test-results. Representative screenshots were inspected.
- Docker Engine 29.7.2 / Compose 5.5.0: Dockerfile.web build and production smoke
  pass on final frontend code. Default Uvicorn serves exact /app/web/index.html
  bytes as UID 10001 for /, /sources, /sources/test-source, /sources/add, /runs,
  /runs/test-run-id, /diagnostics and /sources/test-source/diagnostics.
  Served JS/CSS match image files byte-for-byte.
- /api/unknown, /api/v1/unknown, /assets/missing.js, /assets/missing.css,
  /unknown-frontend-route, /sources/test-source/unknown and
  /runs/test-run-id/unknown retain JSON 404 responses.
- Both disposable smoke runs used network none, read-only filesystem, no mounted
  credentials or published ports. Uniquely labeled containers/images were
  removed after verification; shared images/cache were not pruned.
- git diff --check and frontend stale-branding scan pass.

No live provider, NetBox, historical server or production was touched.
No push/deploy was performed. UI-5 had not started at this UI-4 checkpoint.

## Final visual language and UX hardening (UI-5)

Baseline: clean main at `091bd231e398cffb31c35b70d729c613c9c58760`.
The repository, contracts, tests and rendered application were inspected before
editing. UI-0 through UI-4 were already implemented; this phase changes the
frontend presentation and interaction details, not backend safety semantics.

### Pre-polish audit

| Area | Observed problem | Severity | Resolution |
| --- | --- | --- | --- |
| Shell and surfaces | White canvas, navigation and cards had weak separation | High | Cool canvas, distinct dark navigation, layered panels and muted technical regions |
| Overview | Sparse attention panels stretched to match adjacent content | High | Top-aligned compact panels, clear section headers and evidence summary |
| Tables and filters | Weak toolbar grouping and column emphasis | Medium | Grouped filter surface, compact alternating rows, stronger source/outcome hierarchy |
| Source detail | Header, tabs and panels appeared disconnected | Medium | Shared object header, tab surface, metadata rhythm and panel treatment |
| Sync | Uncertainty resembled ordinary warnings | High | Stronger uncertain outcome treatment, readable plan summary, review and result actions |
| Diagnostics | Repeated timestamps and loose component rows encouraged scanning a long wall | Medium | Compact component rows; additional timestamps retained in Technical details |
| Schedule/configuration | Uneven spacing and label hierarchy | Medium | Shared form/section styling, quieter identifiers and human schedule labels |
| Add Source | Legacy fieldsets and terminal success view did not match other pages | High | Grouped forms, clear review, focused error/success states and links to registered source |
| Cross-screen accessibility | Native zoom, themes and extended keyboard journeys lacked coverage | High | Theme/contrast, keyboard, narrow-height, long-text and true browser-zoom checks |

### Visual principles and tokens

The interface is a dense operator console: information hierarchy and the next
safe action take precedence over decorative metrics. The NetBox reference was
its object navigation, tables, panels and disclosure structure:
[NetBox UI components](https://netboxlabs.com/docs/netbox/plugins/development/ui-components/).
No NetBox CSS, logo or visual assets were copied, and no official/plugin status
is implied. Four small original SVG navigation icons supplement text labels;
no icon or UI dependency was added.

`src/ui/tokens.css` owns semantic colors for canvas, surface, raised surface,
muted/hover surface, border/control border, text/muted text, interaction/focus,
info, success, warning, danger, neutral and navigation. `foundation.css` applies
these tokens to shared layouts and components. Legacy base styles no longer
introduce an independent color palette. Shadows are restrained; borders,
section headers and surface contrast establish most separation.

Page headings remain dominant without dashboard-sized typography. Table text
is 14px, metadata generally 13px, with compact row padding and readable line
height. Controls generally have a 36px minimum height. Rows and technical regions
are visually secondary to source names, outcomes and primary actions. Large
empty panels are avoided; empty states retain concise context and relevant links.
Existing loading placeholders, independent resource loading and retained refresh
context remain; no progress estimates or fake data were added.

Overview and Sources now reuse UI-4's exact stale-evidence join: a recorded
RUNNING outcome, matching run AND source identities, and usable history evidence.
This avoids cross-source stale attribution. Failed refresh notices name the
resource and keep its prior timestamp, so simultaneous history/diagnostic errors
remain distinguishable. Technical details consistently use secondary disclosure.
Raw transport enums are removed from ordinary overview prose where human labels
exist; exact enums/identifiers remain available in appropriate technical context.

Info/activity, success, attention/warning, danger and neutral have distinct
presentations. Outcome uncertain is stronger than an ordinary warning. Unknown
and disabled remain neutral; source enabled uses info rather than success.
Labels/icons remain alongside color. Sync still submits the entire reviewed plan,
retains missing objects, checks staleness, isolates review rows and never retries
an uncertain write automatically. No capability or authorization rules changed.

All source tabs share the same object header and section surfaces. Schedule
keeps its exact custom interval and conflict checks. Configuration remains
read-first with grouped identity, connection, target, provider and TLS facts.
Add Source retains test/review/register and credential clearing; it only gains
consistent grouping, focus feedback and navigation after successful registration.
This is not the future Bootstrap wizard.

### Theme decision

Light, Dark and System are implemented across the shell, panels, tables, forms,
dialogs, empty/error states and technical disclosures. System is the default.
The explicit choice lives only in `localStorage` under `netbox-sync.theme`;
invalid values revert to System and blocked storage does not break the UI.
The initial theme is applied before React renders. System changes and another
tab's preference changes update the theme without refetching operational data.
The preference stores no source or credential data.

### Responsive and accessibility verification

- Complete screen galleries cover 1440, 1280, 1024 and 768 CSS pixels in both
  light and dark themes. Navigation collapses at 800px; tabs and controls wrap,
  diagnostic rows stack, and wide tables scroll inside focusable local regions.
- Long source/VM names and reasons were checked at 720x400. Dialog controls remain
  reachable with keyboard focus and internal scrolling. Focus is visible for
  links, inputs, buttons, disclosures and route content. The skip link is clipped
  when unfocused and visible when focused; Escape returns collapsed-navigation
  focus to its toggle. Route changes focus content and Back/Forward retain
  existing routing behavior.
- True 200% browser zoom uses a fresh full-Chromium profile with a native zoom
  preference, not CSS zoom or a pinch-scale emulation. The test asserts DPR >=
  1.99 and a layout viewport <= 720px from a 1440px window, checks all main pages
  for overflow, then builds a plan and checks the confirmation dialog. The
  screenshot comes directly from Chromium's compositor so native zoom is not
  misinterpreted by screenshot clipping. The temporary profile is safely removed.
- Browser journeys exercise skip/route focus, navigation, tab links, plan row
  disclosure, modal focus trap/cancel/return, registration review/success focus,
  forms, async states and error messages. Existing stale-plan, late-response,
  duplicate-submit and schedule-conflict regressions remain.
- Computed semantic text/background pairs pass 4.5:1 and control borders against
  input surfaces pass 3:1 in both themes. Reduced-motion preference is exercised;
  existing reduced-motion rules remain. These checks cover the defined pairs,
  not every possible OS/browser rendering or user stylesheet.
- Manual visual inspection covered representative screenshots of every main
  screen, both themes, desktop/tablet widths, mixed plan, confirmation, uncertain
  result, healthy/degraded diagnostics and empty/refresh-error states. Native
  zoom dialog capture was also inspected. Keyboard interactions were exercised
  through browser automation; no independent screen-reader user study was run.

This is an accessibility hardening pass aimed at WCAG 2.2 AA, not a conformance
certification. Firefox, WebKit, forced-colors and assistive-technology combinations
were not independently verified. These remain verification limitations rather
than claims about supported or unsupported browsers.

### UI-5 validation and performance

- 44 frontend unit tests pass; strict TypeScript and Vite production build pass.
- 119 Playwright tests pass, preserving the UI-0 through UI-4 suite and adding
  21 UI-5 checks. The subsequently expanded all-screen native-zoom check also
  passes independently. No real providers or NetBox were contacted.
- Mocked journeys cover Overview attention to source; plan/review/confirm/success;
  stale plan; uncertain outcome; read-only Runs/Diagnostics; schedule save and
  conflict; and the existing Add Source flow with cleared credentials and sync off.
- Sources/Runs were checked with 125 fixture records: 100 visible source rows and
  50/50/25 run pages. The local navigation/render scenario completed in under one
  second in the final run; this is an observation, not a benchmark or server SLA.
  Theme switching does not refetch data. No dependency, polling or animation load
  was introduced.
- Final JS: 338.80 kB (101.48 kB gzip); CSS: 27.93 kB (6.06 kB gzip).
  UI-4 JS was about 334.98 kB; the increase is small and includes theme handling
  and form/navigation hardening. CSS growth supplies the complete two-theme
  surface system. No bundle splitting or speculative performance framework added.
- The UI-5 gallery contains 138 PNGs in ignored `frontend/test-results`, including
  all main screens and key states in both themes at four widths, plus narrow
  dialog and native zoom captures. Tests regenerate these; they are not brittle
  pixel-perfect snapshot assertions or committed binary assets.
- Backend code, API DTOs, dependencies, migrations and Dockerfile.web are unchanged.
  No unrelated backend suite was required for these frontend-only changes.
- `git diff --check` and the frontend/docs stale-branding scan pass.

### Production-container acceptance

Docker Engine 29.7.2 / Compose 5.5.0. Dockerfile.web builds successfully.
The final disposable container ran the default Uvicorn command as UID 10001,
serving `/app/web` with network none, a read-only filesystem, dropped capabilities,
no-new-privileges, and only an ephemeral /tmp. No ports, credentials or host
volumes were exposed.

The following direct requests returned 200 HTML identical to the image's
`/app/web/index.html`:

- `/`
- `/sources`
- `/sources/test-source`
- `/sources/test-source/sync`
- `/sources/test-source/schedule`
- `/runs`
- `/runs/test-run`
- `/diagnostics`
- `/sources/add`

`/api/v1/health` returned 200 with healthy status. Built JS and CSS were served
with correct MIME types and matched image files byte-for-byte (338803 / 27926
bytes). `/api/unknown`, `/api/v1/unknown`, `/assets/missing.js`,
`/assets/missing.css`, `/unknown-frontend-route`, `/sources/test-source/unknown`
and `/runs/test-run/unknown` retained JSON 404 responses. This verifies the
production serving path independently of Vite. Uniquely labeled smoke containers
and images were removed after ownership checks; shared Docker cache was not pruned.

UI-5 closes the current full redesign. Remaining product boundaries are unchanged:
no Bootstrap wizard, LDAP/RBAC, global search, saved views, bulk actions, deletion,
telemetry, new integrations or speculative post-v1 work. Large-scale backend
pagination/coverage work remains outside this phase. Production and the historical
server were untouched. Push/deploy requires a separate explicit user request.

## UI-6 operator lifecycle

Sync loads durable operations when opened or refocused. While the source has RUNNING
work, sequential reads poll every 2.5 seconds; navigation stops browser polling, not
server work. Reads time out after 10 seconds; starts after 15 seconds. A lost start
acknowledgement triggers a read, never an automatic POST retry. Unknown state disables
new operation controls until reloaded. Only the latest source/kind slots are returned.

Another browser sees the same Planning/Discovering status, server start time and elapsed
time; duplicate starts return the active UUID. PLAN and DISCOVERY can run independently.
A newly observed Discovery generation opens its inspection section, including on reopen.
READY results repopulate review from server truth. FAILED/STALE stay explicit; a previous
plan may remain visible in the current page but cannot be applied. Reopening never revives
an older generation. Prepare binds the reviewed UUID; Apply's token remains authoritative.

Configuration > Lifecycle offers Remove Source. The dialog lists retained NetBox objects,
retained history, stopped automatic sync and reserved identity; requires the exact Source
ID; and defaults to retaining local credentials. Explicit cleanup is conditional on
exclusive broker ownership. Shared/legacy and failed cleanup states explain operator
follow-up without claiming provider revocation. Removed direct URLs show a read-only
state and history link; source lists exclude removed sources. Registration of that ID
reports: "This Source ID was previously used and is reserved by a removed source."
No actor name is invented before RBAC exists.

Automated browser evidence is distinct from real-provider acceptance. UI-6 covers two
browser contexts, close/reopen, deduplication, cross-source work, failed/stale results,
removal blockers and tombstones, with visual scenarios at 1440/1024/768. See
[UI-6 report](ui6-implementation-status.md) for the final executed matrix and limits.

## First-run gate

`BootstrapGate` wraps routed content, reads durable server state on load/focus, and
polls accepted validation work. Incomplete/unavailable state shows setup on any direct
route. `/setup` supports deliberate token replacement after completion. No token is
loaded from GET or stored in browser storage. POST outcomes are reconciled through
explicit Reload, without automatic mutation retry. See [first-run flow](first-run.md)
and its disposable-VM checklist; browser mocks are not live NetBox permission evidence.

## Shared operator UX hardening

See [audit, screen/role map and verification](ux-hardening-audit.md).
EN/RU and Light/Dark/System are shared between setup and the operational panel.
Only language/theme preferences are persisted in browser storage; changing them
neither remounts forms nor grants permissions. Storage denial uses an in-memory
fallback. UI copy is explicit in `src/ui/ru.ts`; provider names, identities, managed
field values and original technical evidence must not be passed through translation.
Backend-generated technical explanations can retain their original language; the
surrounding controls, safe failure messages and status labels are localized.

`/system` is a production SPA route and exposes the frontend content fingerprint in
its details. The same `ui-<16 hex>` identity appears in index metadata under
`netbox-sync-ui-build`. It fingerprints the frontend input bytes, not a Git commit;
it can change between builds and must not be used for authorization or version fencing.
Dockerfile.web builds Vite and copies dist into `/app/web`. Production serves `/assets`
and recognized SPA routes with no-store. There is no service worker. Test artifacts
and nested Python caches are excluded from the Docker build context.

Inter is bundled locally with its unmodified SIL OFL 1.1 license in
`frontend/public/assets/Inter-LICENSE.txt`. Upstream font file:
https://github.com/rsms/inter/blob/master/docs/font-files/InterVariable.woff2
SHA-256: `693b77d4f32ee9b8bfc995589b5fad5e99adf2832738661f5402f9978429a8e3`.
The font contains Cyrillic; there are no third-party font requests. Brand SVG/PNG/ICO
files live under `/assets/brand`, the production static mount.

Client dispatch is labelled “Request sent / waiting for acknowledgement”. Only a
persisted RUNNING/VALIDATING state is labelled server-confirmed execution. Elapsed
time is outside the live region and is not a completion estimate. No determinate
progressbar is introduced. Returning to a durable operation loads its existing state;
a lost response does not automatically resubmit a mutation. Apply retains separate
confirmation, digest/revision fencing and the shared lock.

Saved Bootstrap validation is labelled with its timestamp. Missing detailed checks
are explicitly reported as unavailable historical evidence. An absent/expired
validated_at cannot enable Finish; the UI uses the current backend 300-second window
and backend remains authoritative. READY installations remain READY on normal visits.
