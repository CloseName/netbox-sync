# Historical UI preview bridge: read-only diagnosis

Status: operator procedure, not executed against the historical server. UI-6 runtime
integration, grants and automated acceptance are documented in the UI-6 report.
No implicit INFRA_SYNC environment or socket fallback has been added.

## What is known

The message "Planning worker unavailable" does not distinguish a missing mount,
wrong socket path, denied peer UID, stopped worker, protocol mismatch, or timeout.
The repository cannot establish the historical server's actual cause. No server
inspection, modification, restart, migration, provider call, or apply was performed.

In the canonical production Compose contract, the API runs as UID/GID 10001 and
shares named socket volumes with the corresponding root supervisors. The API mounts
these volumes read-only; connecting to an existing socket does not require creating
files in that mount. Workers authorize the caller using SO_PEERCRED. Canonical paths:

| API setting | Socket | Compose worker |
| --- | --- | --- |
| NETBOX_SYNC_DISCOVERY_SOCKET | /run/netbox-sync-discovery/worker.sock | netbox-sync-discovery-worker |
| NETBOX_SYNC_APPLY_SOCKET | /run/netbox-sync-apply/worker.sock | netbox-sync-apply-worker |
| NETBOX_SYNC_SCHEDULE_SOCKET | /run/netbox-sync-schedule/worker.sock | netbox-sync-schedule-worker |
| NETBOX_SYNC_BROKER_SOCKET | /run/netbox-sync-broker/broker.sock | netbox-sync-secret-broker |

The canonical discovery/apply/schedule health request is exactly
`{"operation":"health"}`. Expected response:
`{"ok":true,"result":{"status":"ok"}}`.
The existing secret broker does **not** implement this health protocol. Do not send
create/rollback requests as a health check.

## Read-only procedure for a separately authorized operator

These commands are documentation only. Run them on the historical Docker host only
when its inspection is separately authorized. Supply actual container names from
inventory; do not assume the pre-Naming deployment uses canonical service names.
Do not print full inspect JSON, environment, DSNs, secret contents, or raw logs.

```sh
docker ps -a --format '{{.Names}}  {{.Image}}  {{.Status}}'
API_CONTAINER='REPLACE_WITH_ACTUAL_PREVIEW_API_CONTAINER'
WORKER_CONTAINER='REPLACE_WITH_ACTUAL_DISCOVERY_WORKER_CONTAINER'
docker inspect --format '{{.Name}} image={{.Config.Image}} user={{.Config.User}} state={{.State.Status}} restarts={{.RestartCount}}' "$API_CONTAINER" "$WORKER_CONTAINER"
docker inspect --format '{{.Name}}{{range .Mounts}} {{.Type}}:{{.Source}}=>{{.Destination}} rw={{.RW}}{{end}}' "$API_CONTAINER" "$WORKER_CONTAINER"
```

Compare the API socket directory mount with the worker's actual socket directory.
They must reference the same backing directory/volume. Merely having identically
named directories in separate containers is insufficient. A bind mount of an
individual socket inode can remain stale after the worker recreates the socket;
prefer a shared directory in the eventual isolated test stack.

The following probe uses the API's configured path and actual UID. It sends only the
fixed health request. It prints allowlisted classifications, never response text or
exception details. Run it for discovery first, then apply and schedule as needed.

```sh
docker exec -i --user 10001:10001 "$API_CONTAINER" python - <<'PY'
import errno, json, os, socket, stat
for key in ('NETBOX_SYNC_DISCOVERY_SOCKET', 'NETBOX_SYNC_APPLY_SOCKET',
            'NETBOX_SYNC_SCHEDULE_SOCKET'):
    path = os.environ.get(key)
    if not path:
        print(key, 'SETTING_MISSING'); continue
    try:
        meta = os.stat(path)
        if not stat.S_ISSOCK(meta.st_mode):
            print(key, 'NOT_A_SOCKET'); continue
        print(key, 'socket_uid', meta.st_uid, 'socket_gid', meta.st_gid,
              'mode', oct(stat.S_IMODE(meta.st_mode)))
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(path)
            client.sendall(b'{"operation":"health"}')
            client.shutdown(socket.SHUT_WR)
            raw = client.recv(1025)
        if len(raw) > 1024:
            print(key, 'PROTOCOL_RESPONSE_TOO_LARGE'); continue
        value = json.loads(raw)
        if value == {'ok': True, 'result': {'status': 'ok'}}:
            print(key, 'HEALTH_OK')
        elif isinstance(value, dict) and value.get('error') == 'PEER_FORBIDDEN':
            print(key, 'PEER_UID_DENIED')
        else:
            print(key, 'PROTOCOL_OR_WORKER_FAILURE')
    except TimeoutError:
        print(key, 'HEALTH_TIMEOUT')
    except OSError as error:
        labels = {errno.ENOENT: 'PATH_NOT_VISIBLE', errno.EACCES: 'PATH_PERMISSION_DENIED',
                  errno.ECONNREFUSED: 'NO_LISTENER', errno.ECONNRESET: 'CONNECTION_RESET'}
        print(key, labels.get(error.errno, 'SOCKET_FAILURE'))
    except (ValueError, TypeError):
        print(key, 'PROTOCOL_RESPONSE_INVALID')
PY
```

Interpretation:

- PATH_NOT_VISIBLE: compare configured path with the mounts and actual worker socket.
- PATH_PERMISSION_DENIED: check parent directory traversal and socket UID/GID/mode.
  Do not solve this by using API root or chmod 777.
- NO_LISTENER: a stale socket or stopped/unhealthy listener is likely; process state
  and version evidence are still required before choosing a remedy.
- PEER_UID_DENIED: verify actual API UID and the worker's allowed UID configuration.
- PROTOCOL_OR_WORKER_FAILURE / invalid response: compare the exact installed worker
  source/version with the expected protocol; this is not proof of a path issue.
- HEALTH_TIMEOUT: old synchronous workers can be occupied by another request.
  Do not restart or kill them based on this probe alone.
- HEALTH_OK proves transport/peer/protocol reachability only, not provider credentials,
  schema compatibility, permissions, or successful Plan/Discovery execution.

## Temporary compatibility policy

Do not attach the UI-6 API to old workers and claim durable operations:
old workers do not implement start_plan/start_discovery/operations. Do not run UI-6
migrations against the historical database. No source re-registration, identity
adoption, automatic provider retry, or provider token revocation is part of a bridge.

The preferred eventual test setup is a completely separate clone from a reviewed
backup, with new matching API/discovery/apply/schedule/broker images and dedicated DB
roles. It requires separate PostgreSQL and socket volumes, copied protected secrets,
a distinct shared apply-lock directory, localhost-only UI, and no automatic scheduler.
NetBox must be a disposable test target. Keep provider egress disabled for mocked
acceptance; real-provider tests require their own explicit scope.

## Isolated clone procedure for later manual acceptance

Use a new disposable Debian VM with no access to the historical or production DB,
provider and NetBox networks. Do not run these commands on the historical host. Use a
reviewed complete bundled-PostgreSQL backup; inspect configuration offline first and
reject external DSNs targeting an existing installation. Use only disposable NetBox
and separately authorized provider targets for eventual real calls. No naming/socket
compatibility hack is required: the clone uses matching current components.

On that isolated VM, obtain the reviewed repository release locally and run:

```sh
sudo python deploy/install.py --no-systemd --no-start --release-id ui6-manual-test
cd /opt/netbox-sync/current
sudo python deploy/backup.py --no-systemd verify /protected/REVIEWED-BUNDLE
sudo python deploy/backup.py --no-systemd restore /protected/REVIEWED-BUNDLE --check
sudo python deploy/backup.py --no-systemd restore /protected/REVIEWED-BUNDLE
```

The first command creates the fresh Foundation, starts its own PostgreSQL, builds and
migrates it, and activates the release; it does not start application workers or a timer.
It is not a read-only preparation. Restore uses only this empty clone, starts ordinary
API/control workers and checks health/Diagnostics; it never starts a scheduler timer or
invokes Apply. Distinct VM volumes, lock/socket directories and localhost-bound UI keep
this separate from the historical stack. Keep outbound access blocked until restored
configuration has been reviewed against disposable targets. Use an SSH tunnel to its
localhost UI. Do not enable a timer during UI acceptance.

Run the fixed health probes above against the clone, then test two browsers, reopen,
duplicate Plan/Discovery, failed/stale display and retained history. Use a dedicated
removal fixture and exact typed ID; verify the tombstone and reserved-ID message.
RUNNING durable operations restored from backup become interrupted and READY plans
stale; no automatic retry. Uncertain sync history remains evidence, not a successful
run. Actual historical cause remains unknown until separately authorized diagnosis.
