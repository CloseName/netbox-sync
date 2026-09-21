# UX acceptance continuation from 9d2b6ce

Status: local verification complete; operator review and live acceptance pending. No push or deployment.

## Initial Docker review (one time only)

Local desktop-linux, Windows named pipe dockerDesktopLinuxEngine, Engine 29.7.2.
Operator-selected disk storage: E:/Docker/DockerDesktopWSL; no VHD file operations.
E: free 414887227392 bytes (~386 GiB). Docker: images 7.077 GB, containers 1.358 GB,
volumes 1.901 GB, cache 2.727 GB. Fifteen stopped historical rehearsal containers
include PostgreSQL. Their data/continued need cannot be disproved; preserved.
Cache is shared and project ownership is not established for safe selective removal;
preserved. Current test-helper images are needed for runtime gates. No deletion,
no space reclaimed. No final cleanup sweep will be performed.

## Requirement map

| Requirement | Baseline | Change | Check | Evidence |
|---|---|---|---|---|
| Shared floating login/password | Separate controls | CredentialField, semantic labels, icon + focus/hover tooltip | Native autocomplete attributes, value/geometry preserved, no submit; EN/RU light/dark, 390px, 200% text | ux-acceptance browser suite |
| Automatic placement | Manual selectors | Server-held preview; exact unique manufacturer/model/provider/role; configured default site | Generic exact model accepted; missing/ambiguous/incomplete refused; heterogeneous hosts | placement_resolution + netbox_catalog tests |
| Cluster follows name | Manual checkbox/select | Server re-resolution, exact site/type/name, occupied cluster blocks; create only at final registration | Fresh/read-only resolution, mismatch before secret writes; real HTTPS final cluster write | Operator API + production Compose |
| Validation and draft | Native browser validation | Linked error summary, inline errors, late-response fencing; placement readiness tied to name/site | Empty submit, focus, retry, expiry, changed address, lost response, no blind replay | wizard + placement browser suites |
| Wizard copy | Technical ordinary path | Three concise steps, computed parameters in details, explicit pending cluster, sync off | Admin/Operator, both providers, RU narrow review and success | wizard and UX captures |
| Page focus | Whole-page outline | Remove only programmatic content outline, retain controls and skip link | Keyboard navigation, Escape, route focus, skip link | foundation + hardening |
| Navigation | Separate diagnostics/config tabs | Global Overview/Sources/Run history; source Overview/Sync/Schedule; redirects; Admin settings link | Direct old routes, reload, Back/Forward, source state retention | source-detail + foundation |
| Sources/teams | Inline CRUD, redundant link | Add left, Refresh right; team modal Admin only, conditional filter, source name link, return scroll | Create/assign/concurrency, filters/empty states; exact query and scroll restoration | source-teams + foundation |
| Source overview | Duplicate history summaries | Server/placement, single header outcome, retained run history; diagnostics/config in details | Failure vs successful run vs unknown, source isolation, blocked plan survives reload | source-detail + durable-lifecycle |
| Removal | Typed name + cleanup checkbox | Explicit short Admin dialog; backend defaults exclusive cleanup; absolute removal timestamp | CSRF/revision and Admin gate, active/uncertain blocking, shared refs retained, cleanup failure durable | 29 Linux PostgreSQL/HTTP tests; responsive browser deletion |
| Conflict report | Repeated policy/row reports | Single compact list, IDs in details, distinct same-interface masks vs multiple VM mapping | No ready claim/false zero summary; disabled confirmation; reload; EN/RU narrow | durable-lifecycle conflict tests |
| Screenshots | Previous version only | Current login, three steps, errors, automatic parameters, list, detail, removal, conflict | Screenshot review + narrow reflow; fixtures are not live infrastructure | final browser capture output |
| AD/recovery | Previously incomplete | No identity or AD changes; occupied clusters require ownership review; no automatic recovery | No live AD/hypervisor access; no adoption by name/address | automatic-source-placement.md |

## Verification and evidence boundaries

- Targeted server suite: **169 passed on Linux, no skips**. Windows originally skipped
  7 platform-specific checks; the Linux run executed all seven.
- Lifecycle/PostgreSQL + HTTP: **29 passed**, disposable networkless PostgreSQL on tmpfs,
  runner shares only that test network namespace; no host ports or existing volume.
- Frontend unit tests: **70 passed**. TypeScript and Vite build passed. Vite reports
  the existing large-bundle warning; this change does not introduce code splitting.
- Seven affected browser suites together: **131 passed** in the final combined run,
  including direct scroll restoration and the last visual corrections.
- Additional keyboard and RU full-page galleries passed in the hardening suite. Earlier
  failures exposed obsolete selector expectations and eager duplicate Overview reads;
  selectors were migrated without dropping negative cases, and collapsed diagnostics
  now load only on expansion. Runs during code edits were superseded by the frozen
  combined run, not counted as successful evidence.
- Production Compose (bundled and external PostgreSQL): **2 passed** on the implementation
  image, then **2 passed again (209.83 s)** after rebuilding the Web image.
  Two subsequent UI-only adjustments (duplicate success timestamp and cluster error
  placement) were covered by the final 131-browser-test run, TypeScript and Vite;
  the Compose run preceded those two presentation changes. Backend code is identical.
- Browser tests use authenticated fixtures. Server role enforcement is separately tested
  through real API/AuthPolicy checks; Compose uses an isolated authenticated Admin and
  a controlled HTTPS peer. None of these results imply acceptance against live NetBox,
  ESXi, Proxmox, AD or a third-party password-manager extension.

The deletion change was initially rejected by automatic approval review. After the
operator explicitly confirmed the exact short-dialog/exclusive-local-cleanup change
in the conversation, it was approved, applied and tested. No unresolved approval block.

## Limits to review

Automatic matching is deliberately exact and bounded; see automatic-source-placement.md.
More than 20 unresolved catalog candidates fail closed. An ambiguous hardware match must
be corrected by Admin; the wizard does not invent a model or choose an arbitrary record.
Occupied clusters are blocked conservatively even when an operator believes them to be
from a removed source. Safe restoration is still unavailable and is not claimed here.
Source list health remains a diagnostic/history snapshot; the source workspace reloads
the durable plan and shows its current conflict separately. These evidence types must
not be interpreted as a connectivity check or successful synchronization.

Screenshots are generated under frontend/test-results by the named suites. A local
review gallery is retained outside Git; private keys, real credentials and unmasked
fixture passwords are not included. Counts supplement, rather than replace, visual
inspection and the explicit scenarios above.

Sources reviewed: GOV.UK error-summary, error-message, button and details components;
WCAG 2.2 Focus Visible. Apply error summary + linked inline messages and keep a visible
focus indicator on interactive controls; optional details must not hide blocking errors.
https://design-system.service.gov.uk/components/error-summary/
https://design-system.service.gov.uk/components/error-message/
https://design-system.service.gov.uk/components/button/
https://design-system.service.gov.uk/components/details/
https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html

## Implementation commits

- 4a51634: guarded short removal flow and exclusive credential cleanup.
- 23fe538: server-verified automatic placement and production regression coverage.
- 8c8c85b: source wizard, navigation, conflict presentation and browser regressions.
