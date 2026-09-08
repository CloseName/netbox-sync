# Interrupted deployment-path recovery audit

Base: `b069d57ae291e1c48c61c54877c88ca3e95503c7`, branch main.
Local HEAD and remote origin/main matched at recovery; no post-base commits existed.
No reset or cleanup of source changes was performed. There were 19 modified and
3 untracked files. No unrelated changes (D) were found.

A = preserved useful generalized work; B = examples/matrix generalized;
C = incomplete behavior corrected. Categories can coexist within a file.

| Existing changed file | Classification and disposition |
|---|---|
| `README.md` | B: replace company example with generic example |
| `compose.production.yml` | A: configurable TLS template mount |
| `deploy/backup.py` | A/C: preserve root/global lock work; add identity metadata and explicit restore target |
| `deploy/compose.py` | A: selected/installed root |
| `deploy/install.py` | A/C: preserve selected root and unit rendering; remove automatic corporate TLS default |
| `deploy/systemd/netbox-sync.service` | A: rendered root |
| `docs/backup-restore.md` | A/C: selected paths; complete identity/restore contract |
| `docs/clean-install-tls-runbook.md` | B: explicitly labeled test example |
| `docs/deployment.md` | A/C: derived paths; correct generic TLS default |
| `docs/external-ingress.md` | A/C: derived socket; correct TLS default |
| `docs/first-run.md` | A: derived paths |
| `docs/tls.md` | B/C: optional operator convention, generic default retained |
| `scripts/run-full-sync.sh` | A: explicit historical checkout |
| `scripts/run-scheduled-sync.sh` | A: selected or physical installed root |
| `tests/test_backup_restore.py` | A/C: maintenance mocks preserved, manifest regressions added |
| `tests/test_deployment_foundation.py` | A: rendered unit assertions |
| `tests/test_external_ingress.py` | A: explicit legacy fixture |
| `tests/test_shared_apply_lock.py` | A: rendered unit assertion |
| `tests/test_tls_docker.py` | A: optional TLS layout smoke |
| `deploy/nginx.corporate.conf.template` | A: new optional filename layout; no company defaults |
| `docs/deployment-paths.md` | B/C: new path contract corrected to portable defaults |
| `tests/test_selected_root.py` | B/C: new one-root coverage expanded to three roots and restore refusal |

## Literal audit

Every matching line in product sources, tracked files and new task files was reviewed.
Company values occur only in tests or explicitly labeled documentation/runbooks.
The only runtime generic-root occurrences are the checkout default and the explicit
historical naming translator; the translator is not a clean-install path.
No `10.24.0.6` occurrence was found. Tests and production use one release/main branch.

The inventory below excludes this audit's own quoted search terms and file references.
Line numbers refer to the final pre-commit source snapshot.

| File | Matching lines | Classification |
|---|---|---|
| `README.md` | 60 | Documentation: generic or historical example |
| `deploy/install.py` | 89, 285 | Generic default / historical naming compatibility |
| `docs/clean-install-tls-runbook.md` | 20, 21, 59, 60, 127, 143, 223, 241, 242, 243, 246, 249, 253, 256, 259, 269, 276, 277, 294, 295 | Explicitly labeled test examples / path contract |
| `docs/deployment-paths.md` | 3, 8, 9, 22, 26, 61, 62, 63, 79, 110 | Explicitly labeled test examples / path contract |
| `docs/deployment.md` | 40 | Explicitly labeled test examples / path contract |
| `docs/external-ingress.md` | 118, 120, 128, 129, 139 | Explicitly labeled test examples / path contract |
| `docs/historical-ui-test-bridge.md` | 139 | Documentation: generic or historical example |
| `docs/legacy-proxmox-mode.md` | 1, 11 | Documentation: generic or historical example |
| `docs/migrations.md` | 1, 20, 21 | Documentation: generic or historical example |
| `docs/naming-migration.md` | 13, 31, 36 | Documentation: generic or historical example |
| `docs/tls.md` | 62, 63, 77 | Explicitly labeled test examples / path contract |
| `docs/web.md` | 1, 162, 556 | Documentation: generic or historical example |
| `tests/test_deployment_foundation.py` | 148, 149, 452 | Regression fixtures |
| `tests/test_selected_root.py` | 21, 23, 32, 36, 51, 55, 61 | Regression fixtures |

## Verification scope

- Linux backend suite: 829 passed, 9 skipped. Skips: four opt-in Docker smokes,
  three host Compose checks, live ESXi and isolated legacy naming-cluster integration.
- Host deployment/Compose/ingress suite: 46 passed, 4 platform/integration skips;
  includes all four Docker smokes (default TLS, selected-directory TLS, external
  ingress and bundled PostgreSQL backup/restore). Compose checks passed here.
- Frontend unit tests: 48 passed; TypeScript and Vite production build passed.
- Docker Engine 29.7.2, Compose 5.5.0.
- Shell syntax of executable runbook blocks and git diff whitespace checks passed.

Exact-root install tests execute real layout/config/release/unit generation in
fresh disposable Linux containers while intercepting host service/DB activation.
They do not claim a real systemd reboot or live VM acceptance. Existing origin,
CSRF, private-worker, broker network isolation and bootstrap regressions passed.
No code for providers, application privileges, lifecycle coordination or DB schema
was changed. No live host, test VM, deployment or remote repository was modified.

- Playwright: 134 passed. Task-owned Docker test container/images were removed after verification.
- Implementation commit: `ba8a409c4e7abcfcb9fc590aaea52df6d1ddc965`.
