# Host preview verification record

Local review, 2026-09-09. No deployment, push or live hypervisor access.

## Executed checks

- Broad Linux backend snapshot: **864 passed, 98 skipped**, 69.67s. The additional PostgreSQL mapping case was added afterward and executed in the dedicated DB run; these numbers are the recorded broad snapshot, not a claim that every opt-in integration test ran.
- Final affected Linux preview/catalog/planning regression: **30 passed**, 2.74s.
- Real PostgreSQL onboarding and registry: **31 passed**, 3.03s; mapping persistence, disabled sync, unchanged legacy settings.
- Final production Compose API/auth/catalog/host preview: **2 passed**, 195.92s; bundled and external PostgreSQL, external ingress, private CA HTTPS/SOAP fixture outside API DB network, real worker RPC, registration, backup/restore and state preservation.
- Final production Compose TLS/bootstrap: **3 passed**, 109.37s; standalone, corporate, external. Product mounts, network isolation, tmpfs and privilege parameters retained.
- Host deployment/Compose model suites: **47 passed, 4 skipped**, 2.64s. Four skips are POSIX symlink/mode/root metadata assertions; covered by the broad Linux run, not replaced with Windows assertions.
- Frontend Node tests: **59 passed**. TypeScript and Vite build passed.
- Final Playwright: **208 passed**, 3.8 minutes, zero skipped.
- git diff --check passed; sources/ unchanged. Product Docker build passed; no deployment activation. Test-owned Compose resources cleaned; no running test containers remained.

## Opt-in skips in the broad networkless Linux snapshot

The test-runner container has no Docker socket and no PostgreSQL DSN. Dedicated host-controlled tests use uniquely labeled disposable resources. The following inventory accounts for all 98 recorded skips. Unrelated integration suites are not claimed as newly executed.

| File | Skips | Reason and current coverage |
|---|---:|---|
| `tests/test_api_sources_postgres.py` | 5 | Requires dedicated PostgreSQL DSN; storage/privilege implementation unchanged by this diff, separate opt-in suite not rerun. |
| `tests/test_auth_compose_docker.py` | 2 | Dedicated production Compose run: 2 passed, final image; real catalog/preview, auth, state and backup/restore. |
| `tests/test_auth_postgres.py` | 3 | Requires dedicated PostgreSQL DSN; storage/privilege implementation unchanged by this diff, separate opt-in suite not rerun. |
| `tests/test_auth_upgrade_docker.py` | 1 | Explicit isolated host/Docker opt-in required; unrelated installer/naming/auth-upgrade implementation unchanged, suite not rerun. |
| `tests/test_backup_clean_debian.py` | 2 | Explicit isolated host/Docker opt-in required; unrelated installer/naming/auth-upgrade implementation unchanged, suite not rerun. |
| `tests/test_backup_restore_docker.py` | 1 | Explicit isolated host/Docker opt-in required; unrelated installer/naming/auth-upgrade implementation unchanged, suite not rerun. |
| `tests/test_backup_restore_postgres.py` | 1 | Requires dedicated PostgreSQL DSN; storage/privilege implementation unchanged by this diff, separate opt-in suite not rerun. |
| `tests/test_container_names_docker.py` | 2 | Explicit isolated host/Docker opt-in required; unrelated installer/naming/auth-upgrade implementation unchanged, suite not rerun. |
| `tests/test_deployment_foundation.py` | 1 | Host Docker model test passed. POSIX-only host skips were already covered in broad Linux run. |
| `tests/test_deployment_postgres.py` | 6 | Requires dedicated PostgreSQL DSN; storage/privilege implementation unchanged by this diff, separate opt-in suite not rerun. |
| `tests/test_source_registry_postgres.py` | 20 | Dedicated PostgreSQL run with test_onboarding_postgres.py: 31 passed including added mapping persistence. |
| `tests/test_durable_worker_linux.py` | 1 | Requires dedicated PostgreSQL DSN; storage/privilege implementation unchanged by this diff, separate opt-in suite not rerun. |
| `tests/test_esxi_live.py` | 1 | Intentionally not run: user forbids live hypervisor access. SOAP fixture is not a live compatibility claim. |
| `tests/test_external_ingress.py` | 2 | Host Docker model tests passed; runtime external mode also covered by Compose auth/TLS. |
| `tests/test_migrations_postgres.py` | 4 | Requires dedicated PostgreSQL DSN; storage/privilege implementation unchanged by this diff, separate opt-in suite not rerun. |
| `tests/test_naming_migration_postgres.py` | 1 | Requires dedicated PostgreSQL DSN; storage/privilege implementation unchanged by this diff, separate opt-in suite not rerun. |
| `tests/test_onboarding_postgres.py` | 8 | Dedicated PostgreSQL run: includes mapping round-trip and unchanged legacy configuration. |
| `tests/test_probe_compose_docker.py` | 2 | Legacy standalone probe suite not repeated; changed preview/probe path exercised by actual auth Compose API scenarios in both DB modes. |
| `tests/test_production_proxy_docker.py` | 1 | Separate legacy proxy suite not repeated; final TLS smoke uses production proxy with exact tmpfs/security settings. |
| `tests/test_run_history_postgres.py` | 4 | Requires dedicated PostgreSQL DSN; storage/privilege implementation unchanged by this diff, separate opt-in suite not rerun. |
| `tests/test_source_lifecycle_postgres.py` | 15 | Requires dedicated PostgreSQL DSN; storage/privilege implementation unchanged by this diff, separate opt-in suite not rerun. |
| `tests/test_source_operations_postgres.py` | 12 | Requires dedicated PostgreSQL DSN; storage/privilege implementation unchanged by this diff, separate opt-in suite not rerun. |
| `tests/test_tls_docker.py` | 3 | Dedicated production Compose run: 3 passed; standalone/corporate/external TLS and bootstrap. |

## Fixture corrections and visual evidence

The first complete UI run had 205 passes and two failures in new fixtures: an incorrect Proxmox token input selector and an out-of-scope fixture variable in the session-expiry test. Both were corrected and the complete suite was repeated. No product security boundary was changed to make those tests pass.

The production SOAP fixture was extended for the actual pyVmomi Fetch path, including HostSystem summary. A fixture CA mount initially conflicted with the canonical readonly CA directory; it was corrected by preparing the CA in that canonical directory, without replacing product mounts.

Screenshots are generated by `frontend/e2e/source-placement.spec.ts`: EN/RU, light/dark, 1440/390; exact/generic/missing models; separate Proxmox nodes; changed selection and successful explicit retry. Catalog error, pagination, keyboard, 200% reflow and expired-session draft retention are asserted. Screenshots contain fixture names only, no passwords or API secrets.

These checks do not establish live hypervisor permission/version compatibility. The bounded preview does not replace a separate full discovery review. See [operator contract and official references](source-onboarding-preview.md).
