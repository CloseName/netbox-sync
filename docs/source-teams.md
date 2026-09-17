# Source ownership teams

Teams are organization metadata, not authorization groups. Admins (existing
source.configure permission) create/rename teams and assign/unassign an existing
source in Configuration. All existing authenticated reader roles can view/filter
teams. Creating a team named admin never grants a role. LDAP mapping, permission
matrix, source identity, scheduler settings and plan digests remain independent.
No notifications or recipient addresses are implemented.

Storage: versioned `source_teams` in the existing transactional auth_state JSONB
control-state row, with separate revision, UUID team entities and source-instance
assignments. This deliberately reuses the existing narrow control writer without
adding API database writes or registry capabilities to it. Future normalization
can migrate this versioned metadata without turning it into permission policy.
Legacy rows migrate additively under the existing row lock on first teams access;
absent assignments mean No team. No source row or credential changes are needed.
Migration is idempotent and requires no new SQL table/grant/Alembic revision.

Each mutation checks server permission and exact revision, validates unique names,
then audits actor/action/team/source/revision. The API checks that an assigned
source exists. A stale browser gets TEAM_CONFLICT and must reload, not blindly
retry. Names are 1–80 characters, up to 100 teams; the entire control response is
bounded to 24 KiB. Invalid/oversize changes leave prior metadata unchanged.
Deleted-source assignments remain historical metadata; reserved Source IDs prevent
an unrelated replacement source from inheriting them. There is no destructive team
delete endpoint. Rename preserves the team UUID and assignments.

Upgrade retains the existing auth_state row. Supported full backup includes this
row and audit; restore merges capability revocation fields rather than rebuilding
the row, preserving ownership metadata while invalidating sessions/receipts.
Local acceptance covers legacy migration, restart/reopen, concurrent PostgreSQL
CAS, admin/operator/viewer, EN/RU create/assign/filter/reload/conflict at 390 px.
Production Compose with bundled PostgreSQL additionally verifies team entities
survive installer activation, assignments survive auth-worker restart and the
supported create/verify/inspect/restore path, and restored session capabilities
are invalidated while team metadata remains identical. See
[timeout integration evidence](worker-timeout-acceptance.md).
