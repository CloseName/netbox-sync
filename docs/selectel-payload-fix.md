# Selectel collection output, 2026-10-14

Production account 29916 reproduced a read-only collection failure after 530.9 s:
exit 120, stdout exactly 25,165,824 bytes (24 MiB), OSError, non-JSON prefix.
The child hit RLIMIT_FSIZE; its parent accepted only 16 MiB. The former combined
error did not distinguish those failures. Container OOMKilled was false.

The collection subprocess now suppresses normal progress and redirects incidental
stdout to stderr, reserving stdout for one complete JSON response. The importer
receives server dataset items and coverage, without duplicate audit responses or
field-shape reports. DNS and storage remain in the independently built registry;
the UI summary is computed from the original audit. No resources are truncated.

The wire response and actual import envelope are checked against the existing
Guard 16 MiB limit before output or POST. Encoding matches requests' JSON encoding,
including Unicode escaping. An over-limit result becomes a small structured error.
The OS file cap has 4 KiB headroom above the application limit as a fallback.
Abnormal import completion remains unconfirmed: no claim of zero writes is made.

Regression coverage compares normalized server inventory, registry and summaries
before/after compaction, exercises a 25 MiB redundant response, JSON contamination,
Unicode boundary sizes, and rejection before HTTP POST. The disposable NetBox
scenario imports the compact document and checks permissions, atomic rollback,
idempotency and preservation of native devices.

## Production rollout

Run deploy/update-selectel-payload-production.sh from a clean pinned checkout on
netbox-sync only. It validates the production target, refuses a running Selectel
collection, pauses the scheduler timer, drains the current apply writer, creates
and verifies a Sync backup, installs the release, and restores the prior timer
state. Backup and previous release path are printed/stored under
/var/tmp/netbox-sync-selectel-payload-backup.*. No NetBox upgrade is required.

After rollout refresh the UI and run one collection for account 29916. The original
production payload was not copied out, so its compact size and final import outcome
must be confirmed by this run. If still over 16 MiB, the job fails before import
with SELECTEL_RESULT_TOO_LARGE; it never silently drops resource observations.

## Follow-up: scope catalogs to discovered VM references

The production read-only size probe measured 33,774,214 import bytes: image/images
24,716,124 bytes (13,580 rows in 90 datasets) and compute/flavors 4,436,540 bytes
(9,898 rows in 90 datasets). Those are available catalog choices, not a count of
owned virtual machines. All remaining payload accounts for 4,621,550 bytes.

The transport now retains only image and flavor entries referenced by discovered
VMs in the same project and region. It preserves selected rows and ordering,
endpoint statuses, coverage and missing-ID join behavior. Conflicting duplicate
catalog datasets are left intact so filtering cannot conceal a conflict. Full
audit collection and summary accounting remain unchanged. DNS, storage, volumes,
network observations and dedicated server data are unaffected.

Regression tests compare Inventory.normalize before/after filtering, including
27 MB of unused catalogs, duplicate conflicts, failed endpoints and absent IDs.
The actual NetBox scenario imports this filtered payload. Production success
still requires a fresh collection after rollout; no live resources were read or
changed from the development environment.
