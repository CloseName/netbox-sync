# NetBox Sync containers

This page describes the NetBox Sync Compose services in `compose.production.yml`.
It does not cover the separate NetBox deployment. Update this list whenever a
service is added, removed, or given a different responsibility.

## Long-running services

| Container | Responsibility |
| --- | --- |
| `netbox-sync-proxy` | Nginx entry point for NetBox Sync HTTP traffic; forwards requests to the API through a private socket. |
| `netbox-sync-api` | Serves the UI and API, checks requests, and delegates privileged operations to dedicated workers. |
| `netbox-sync-postgres` | Stores source configuration, users, schedules, operation state, and run history. |
| `netbox-sync-auth-worker` | Handles local and directory login, sessions, and application roles. |
| `netbox-sync-probe-worker` | Tests a proposed source connection and access policy before registration; does not synchronize inventory. |
| `netbox-sync-secret-broker` | Manages local provider and directory credentials through a private socket; has no network access. |
| `netbox-sync-lifecycle-worker` | Coordinates source changes and removal, including state checks and source credential cleanup. |
| `netbox-sync-retirement-worker` | Performs the separately guarded NetBox side of source retirement. Present in the current Compose definition; check the deployed release before assuming it is running. |
| `netbox-sync-bootstrap-worker` | Checks NetBox integration prerequisites and performs explicitly requested setup actions. |
| `netbox-sync-discovery-worker` | Reads source inventory and NetBox state and prepares plans; does not apply inventory changes. |
| `netbox-sync-apply-worker` | Rechecks a confirmed plan and writes allowed inventory changes to NetBox. |
| `netbox-sync-schedule-worker` | Saves schedule settings; it does not run scheduled synchronization. |

## Short-lived services

The host timer launches `netbox-sync-scheduler` only for a scheduled tick. It
checks which sources are due and runs their synchronization with the shared
apply lock. It is separate from the long-running schedule-settings worker.

Compose also defines one-shot setup and maintenance services under the `tools`
profile, including database role/grant setup, migrations, and HTTP socket
initialization. They are not expected to remain running.

The API, workers, scheduler, and maintenance tools use the same NetBox Sync
application image but run as separate processes with different permissions and
network access. Container count therefore does not represent separate copies of
the application code on disk.
