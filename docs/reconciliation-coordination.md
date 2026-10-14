# Reconciliation while scheduling remains enabled

Review and explicit baseline acceptance take a kernel-owned reconciliation intent lock,
then wait up to 10 seconds per request for the existing shared apply lock. New scheduler
ticks skip normally while intent is held. A second intent check inside the scheduler's
apply lock closes the check/acquisition race. An active run finishes normally.

The UI retries only SOURCE_APPLY_ACTIVE for up to five minutes, preserving the operation
ID and reviewed digest. A transport failure or any other refusal is never retried
as confirmation. The administrator must review saved decisions after a lost response.
Intent and apply locks release on exit or process death; no persisted scheduler pause
needs cleanup. Manual writers still compete for the ordinary apply lock.

The review/confirm request timeout is 95 seconds (browser 100), covering the 10-second
lock wait and existing 75-second audit request. Waiting can expire; the UI then explains
that synchronization is still active and offers a later review. It never kills a writer.

Baseline acceptance remains explicit, checks fresh evidence, preserves the historical
unknown result, and leaves this source's schedule disabled until a fresh manual sync.
No inventory, IP, pfSense, or identity-binding changes are part of this update.

Production: run deploy/update-reconciliation-production.sh on netbox-sync. It validates
the production target, creates and verifies a Sync backup, and installs the pinned
checkout. No NetBox host update or schema migration is needed.
