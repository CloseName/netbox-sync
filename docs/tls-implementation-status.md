# DNS/TLS hardening acceptance evidence

This records the earlier standalone TLS stage. The subsequent
[external/shared-ingress stage](external-ingress.md) now supports co-hosting behind
one operator-managed ingress; see acceptance evidence in that document.

Implemented on top of Bootstrap HEAD `94451abe262dd0471c861707b3b2f34a03bef815`.
The supported path and threat boundaries are in [tls.md](tls.md); the exact operator
procedure is [clean-install-tls-runbook.md](clean-install-tls-runbook.md).

## Automated validation

Local Docker Desktop Engine 29.7.2 / Compose v5.5.0 was used. No remote VM,
production deployment, external NetBox instance or provider was changed.

- Final Linux/Python 3.12 backend suite with dedicated disposable PostgreSQL 16
  registry/deployment/backup databases: **803 passed, 5 skipped**.
- Skips: Docker CLI unavailable in the Linux runner, the two opt-in Docker smokes,
  live ESXi credentials absent, and the separately marked naming-migration cluster
  absent. Compose rendering and both Docker smokes passed separately on the host.
  Live ESXi and legacy naming transition are not claimed as tested by this stage.
- Frontend unit suite: **48 passed**; TypeScript and Vite production build passed.
- Full Playwright suite: **134 passed**, including HTTPS-origin Bootstrap writes.
- Final production-image HTTPS and bundled backup transport smoke: **2 passed**.
- New Linux real HTTPS/CA/hostname/mode/backup tests passed. Source removal,
  tombstones, retained history, guarded apply, role grants and first-run regressions
  remained in the full suite.
- Bundled and external-PostgreSQL Compose models render successfully.
- Clean-install shell snippets passed `bash -n`; no installation command was executed.
- `git diff --check` passed. Dependency deprecation warnings remain non-failing.

Final production Web image manifest:
`sha256:899273f7b156c98e0c94bc01b03e12c5b8587244fee16a120338fd04d36992f2`.

The disposable smoke uses operator-like certificate mounts, nginx UID/GID 10001,
read-only filesystems, dropped capabilities, API Unix socket only and built frontend
assets (no Vite). It verifies:

- `/`, `/setup`, `/sources`, `/sources/test-source`, `/sources/add`, `/runs`,
  `/runs/test-run-id`, `/diagnostics`: SPA 200;
- referenced built JS/CSS: 200 and nonempty content;
- unknown API, missing static asset and unknown frontend-looking route: 404;
- HTTP `/setup`: canonical HTTPS 308;
- wrong Host: 421; wrong Origin: 403; client forwarded headers overwritten;
- no API published port or TCP listener, Unix liveness succeeds;
- real private-CA HTTPS mock NetBox validates through the Bootstrap worker,
  CONFIGURED -> VALIDATED -> READY without returning tokens;
- invalid certificate replacement prevents nginx startup and health availability.

Test certificates are ephemeral test-only fixtures, never installer output. A
Python 3.14 strict CA check exposed a missing Key Usage extension in the original
fixture; the certificate was corrected without weakening verification. Docker also
exposed initialization order with CHOWN-only capability: directory mode is now set
before ownership changes. Regression covers the actual production privilege boundary.

## Remaining live acceptance

Repository implementation gates pass. The Debian/systemd/reboot clean-install
rehearsal, operator-issued certificate validation against actual DNS, and real NetBox
permissions/prerequisites remain unexecuted. Supply the reviewed TLS release to the
VM only after explicit publication/transfer approval; this stage does not push.

NetBox is external. Canonical Sync Compose claims host 80/443; two separate proxies
cannot share those ports on one VM. Use a separate NetBox endpoint for this runbook,
or separately review co-hosted ingress. TLS does not add login/RBAC: the endpoint
must remain limited to a trusted operator network. No UI feature phase or NetBox
installer was introduced.
