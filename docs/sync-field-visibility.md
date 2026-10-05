# Sync field visibility

Initial prerequisite creation now explicitly hides managed JSON fields and makes
scalar observations visible only when set. Fields are not manually editable in
the standard form; Sync continues to write through the API. Guard provides the
readable panels. The prerequisite version is incremented to invalidate pending
preparation plans. Install the matching Guard before completing onboarding.

Previously the initial field definitions omitted presentation settings. A test
installation could look correct after running configure_sync_display while a
fresh production installation still showed the default raw JSON beside panels.

Existing field schemas and values remain compatible. Onboarding does not silently
rewrite existing operator metadata or require a new setup token for a cosmetic
change. For existing installations, back up the database and apply the bundled
Guard command once from the NetBox checkout:

```sh
docker compose exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py configure_sync_display
docker compose exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py configure_sync_display --apply
```

The first invocation previews changes. The second hides only the five managed
JSON fields with readable panels: sync_identities, sync_original_names,
sync_network_observations, physical_disks, esxi_host_network. It validates field
types and scopes before writing, uses a transaction, and updates only ui_visible.
No inventory JSON, Description, token permissions or schedules are changed.
No container rebuild/restart is needed for that command if Guard already includes
it. Pulling Sync source alone does not replace an installed Sync release: future
onboarding uses the new defaults only when deployed from the fixed revision.

Check device, VM and interface pages after applying. Readable Guard panels should
remain and raw JSON should disappear. Repeat after a synchronization. --raw
restores raw display for all five fields; for an exact rollback restore the
previous per-field visibility values captured before applying. Avoid restoring
the entire production database merely to undo a presentation setting.

The physical-disk and pfSense panel redesigns are separate deferred work.
