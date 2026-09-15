# Source sync and operator editing — local acceptance

Follow-up: the first-sync HTTP fixture was too permissive about virtual IDs. See
[planned reference fix](planning-virtual-reference-fix.md) for the reproduced
Proxmox failure, stricter fixture and replacement worker evidence. Earlier green
results below did not prove absence of virtual ID leakage.

Date: 2026-09-15. Base: `9140682652cf8dd3e65d4ed0fb2485a91ae9f7cf`.
Implementation commits: backend/runtime `17b08689127ffae1edf0903936b91e64bc421e0c`; UI `425a2be70fdc5e3e00a65c9d094df9315a25f250`.

The approved local implementation and priority runtime gates are complete. This is not a live-hypervisor certification. No push, deployment or VM access was performed. Historical checkpoints in source-sync-review-progress.md are superseded by this record.

## Reproduced defects and limits

ESXi previously planned only already-managed VM updates. New stable-identity hosts and VMs now use the guarded creation path. Name-only matching does not adopt infrastructure; existing managed VM compatibility and explicit legacy adoption remain covered. ESXi host VMkernel/vSwitch networking remains report-only and is identified as unsupported.

The locally reproduced Proxmox failure was `VMNetworkApplyError`: global network preflight ran before a newly planned VM existed. The preflight now models the complete dependency chain on an isolated nested PlanningNetBox before allowing executor writes. Controlled HTTP and production-worker tests include a host, QEMU VM and LXC. This proves that defect and its correction; it does not prove that the operator's original live Build plan failure had the same sole cause. The next operator rehearsal must correlate the new safe event/code/stage evidence if a failure remains.

No raw exception text, credentials or stderr stream is added to public errors. Diagnostics use a closed shared EN/RU code contract and bounded repository frame locations. An empty or unsupported plan is not presented as a ready transfer.

## Completed behavior

| Requirement | Implementation and evidence |
|---|---|
| First sync | esxi_runtime.py, netbox_full_apply.py, test_first_sync.py and worker_full_sync_scenario.py: real SDKs and production workers, explicit prepare/apply, exact object counts and replan without CREATE/UPDATE |
| Explicit HTTPS port | Strict integer 1–65535, default 8006/443; receipt bound to selected port; settings.api_port preserved through registration, preview, discovery, plan, apply and upgrade. No fallback scanning; existing DNS pinning/TLS behavior retained |
| Placement editor | Configuration tab, shared selectors, explicit review/save. API checks source.configure and fresh catalog selections; lifecycle worker owns DB changes under existing shared apply and source locks. Revision and Discovery ID fence writes. READY plans become STALE. Absent-host mappings retained |
| Name/removal | Narrow name update; stable Source ID unchanged. Exact case-sensitive current display name and revision required for removal; tombstones, history, retained NetBox objects and credential ownership semantics retained |
| Wizard recovery | Non-secret in-memory draft survives receipt/session expiry. No secrets or receipt in browser storage. Unknown registration requires server reconciliation before another write |
| Catalogs | Explicit Manufacturer/Device Type/Platform/Device Role/Cluster Type/Cluster creation with separate bounded token and catalog.create. No silent write-token privilege expansion. Site must exist; see catalog-creation.md |
| UI | Unified searchable combobox, EN/RU, provider token parsing with independent editable token name, cluster suggestions, top account controls, animated/reduced-motion loading, responsive fields |

Lifecycle gains UPDATE on only the placement columns/settings and the operation invalidation columns. Web/API receives no additional DB writer grants, credentials or NetBox egress. The broker remains literal network_mode:none. PostgreSQL and worker ports remain unpublished. The API still uses the private Unix HTTP boundary and source credentials remain source-scoped.

## Executed checks

- Full Linux backend with isolated PostgreSQL: **998 passed, 26 skipped**, 2 dependency deprecation warnings, 74.34 s.
- Placement/lifecycle PostgreSQL subset: **18 passed**; dedicated deployment/grants: **5 passed**.
- Full browser suite: **227 passed**, 4.2 min. After the final Source ID editor-state key, the entire affected detail/placement suite was repeated: **58 passed**, 54.4 s.
- Frontend unit **66 passed**, TypeScript/Vite passed. Main bundle 521.90 kB; the existing >500 kB advisory remains.
- Production Compose full-worker suite: **2 passed**, 241.63 s. Both bundled and external PostgreSQL execute both providers using real API, probe, discovery and apply processes and real SDK HTTPS calls on port **8443**. NetBox REST fixture uses trusted HTTPS **9443**. Each provider is first against empty infrastructure in one variant; the second proves coexistence/source isolation. Assertions check one host + one ESXi VM and one host + Proxmox VM/LXC, explicit plan generation fencing, prepare/apply, created counts, replan without duplicates, catalog refusal, mapping update, stale revision, STALE old plan, stable Source ID and changed Device Type in the next plan.
- The bundled full-worker variant also runs the actual installer against populated mappings/ports, compares complete source rows and protected config/credential hashes, READY/policy, and the same PostgreSQL container/mounts. This is an idempotent prepared-release upgrade, separate from the historical upgrade below.
- Historical pre-auth **897de2a -> prepared image**: **1 passed**, 125.27 s. Actual backup/create/verify/inspect, explicit enrollment guard, retained source/history/config/credentials/READY and volume. No systemd exists in this operator-container harness.
- Ordinary production auth/probe + proxy: **3 passed**, 240.34 s; includes safe DNS/TLS/timeout/auth/destination errors, catalog uncertain-response restart reconciliation and backup/restore.
- Final-image TLS standalone/corporate/external: **3 passed**, 98.31 s. Host deployment/Compose suite: **47 passed, 4 Windows-only skips** (POSIX symlink replacement x2, POSIX modes, Linux root TLS metadata; covered by Linux suite).
- Docker Engine **29.7.2 Linux**, Compose **5.5.0**. Final image `netbox-sync-auth:review`: `sha256:79ff1372c42f96457bae8f9fe88cdd9f3f22c3a897e98db5c91966fe32058bf3`. Final rebuild changes only the frontend state key versus the full-worker image; backend code is identical. Final TLS smoke uses the rebuilt image.
- git diff --check passed. Only test-owned containers/networks/volumes were cleaned. Product Compose has no Docker socket; the explicitly authorized temporary operator harness has one, without privileged.

The initial full backend attempt had three test-double failures because the diagnostic source lacked api_port; corrected fixture and full rerun above pass. The initial mapping browser test opened Overview instead of Configuration; corrected and entire suites repeated. The first new production prepare omitted operation_id and was correctly rejected PLAN_STALE; the harness now supplies the saved operation generation. No stale-plan protection was weakened.

## Exact general-run skip disposition

| Group | Count | Disposition |
|---|---:|---|
| test_auth_compose_docker | 2 | Separate opt-in full production worker runs passed |
| test_auth_upgrade_docker | 1 | Separate historical installer upgrade passed |
| test_probe_compose_docker | 2 | Same delegated auth/probe scenario, executed through auth suite |
| test_production_proxy_docker | 1 | Separate actual production proxy smoke passed |
| test_deployment_postgres | 6 | Five dedicated grant tests passed; imported registry test is covered by main DB suite |
| test_deployment_foundation / test_external_ingress | 3 | Docker CLI unavailable in general runner; host Compose checks passed |
| test_tls_docker | 3 | All three separately passed on final image |
| test_backup_clean_debian | 2 | Dedicated host opt-ins not repeated; backup implementation unchanged, actual installed backup exercised by upgrade/auth harness |
| test_backup_restore_docker / test_backup_restore_postgres | 2 | Separate fixture/DSN not enabled; actual CLI backup/restore covered by auth harness; these specific cases not rerun |
| test_container_names_docker | 2 | Independent naming migration unchanged; not rerun |
| test_naming_migration_postgres | 1 | Naming migration unchanged; dedicated DSN not enabled |
| test_esxi_live | 1 | Live access prohibited; remains operator-only |

## Scope of evidence

The HTTPS peers are controlled protocol fixtures, not real NetBox or hypervisors. The product SDKs, production Compose networks/processes, local Unix transports, PostgreSQL grants, persistent operations, confirmation and apply locks are real. Partial/uncertain infrastructure apply remains covered by existing backend safety/worker tests and browser failure-contract tests; the new full provider HTTPS scenario proves the successful first-sync and placement paths. It does not claim live fault-injection certification.

Systemd timer/reboot behavior remains unit/installer-contract evidence, not a VM reboot test. Proxmox SMBIOS manufacturer/model remains an explicit operator choice without SSH/root or a broad report fetch; see source-hardware-discovery.md. Existing NetBox custom fields/plugins may require catalog creation in NetBox instead of the compact wizard.

Current screenshot files are generated by Playwright under frontend/test-results/: placement-en-light-1440.png, placement-ru-dark-390.png, placement-success.png and catalog-ru-dark-390.png. Inputs containing temporary catalog tokens are empty in those screenshots.

See source-sync-upgrade-runbook.md for the post-review operator procedure. Publishing and deployment require separate user instructions.
