# ESXi event evidence for alerts

Scope: all standalone ESXi sources. This does not change Proxmox or pfSense,
send messages, install a webhook, or modify an existing n8n workflow.

## Data path

ESXi EventManager -> the existing discovery and reviewed sync -> NetBox **Device**
`custom_fields.esxi_events` -> consumer webhook/poll -> durable dedupe -> notification.
The field is intentionally hidden in the NetBox UI and available through its API.
No per-VM "last changed by" is inferred from the last unrelated host event.

Prerequisites: prepare the new optional JSON field using the Sync preparation
contract (version 7), or the bounded `deploy/prepare-esxi-events.py` management-shell
helper. No Guard upgrade or database schema migration is required. Existing
Read-only credentials should include System.View; live permission coverage is
not established by tests. A missing/incompatible field skips event export with
a warning; it does not block inventory. NetBox transport/write failures retain
the normal guarded failure handling and are never silently ignored.

Each successful discovery queries the preceding seven days for creation, clone,
deployment, registration, removal, reconfiguration, power, suspend, reset request,
migration and relocation events. The query is scoped to the observed host. It
includes the collector's latest page and older pages, destroys the collector,
and bounds its request count and output. Existing connection timeouts and worker
deadlines still apply. A count/time limit is reported as `partial`.

## Contract, version 1

`version`, `source_instance`, `host_id`, `initialized`, `baseline_through`,
`status`, `lookback_days`, `retention_limit`, `events`.

Status: `available`, `partial`, `permission_denied`, `unsupported`, `unavailable`.
Available means the bounded provider query completed, NOT proof of complete
provider retention or visibility. There is no full audit archive or durable
delivery acknowledgement in this field.

Every event contains:

- `event_id`: SHA256 of source, host, provider key, UTC timestamp and event type.
  Deduplicate using this identifier, never VM name or timestamp alone.
- `provider_event_id`, `occurred_at` (UTC), `event_type`, `action`.
- `actor`: reported login or null; `actor_status`: reported/unknown. A login can
  be a service/shared account. Direct ESXi does not promise the vCenter human actor.
- `vm_reference`, `vm_name`: historical event evidence. A MoRef is not a durable
  VM UUID and may be reused. We do not attach historical events to today's VM
  merely because its MoRef/name matches. Deleted VM events can remain in this
  host feed, provided the host sync itself is allowed and succeeds.
- `changes`: optional numCPUs, memoryMB and device operation/type/key/capacity.
  This is the event's supplied configSpec, not a complete before/after diff.
  Empty changes do not mean nothing changed. Reset is labelled reset_requested.
- `alert_eligible`: false on initial baseline, true for newly observed events
  strictly after that baseline's latest timestamp. Late older events remain quiet.

Full formatted messages, descriptions, configChanges, extraConfig, disk paths,
guest customization and arbitrary SDK objects are never exported. Consumers must
still escape login/VM names in HTML/Markdown messages.

## Consumer requirements

Existing VM-only webhook filters will NOT see this device field. Add a Device
update rule restricted to the intended ESXi devices (start with DEV-BA/DEV-BA2),
and/or periodically GET their device objects. A Device create should establish
the baseline, not announce VM creation. The NetBox actor remains the Sync account;
use each event's actor in the notification.

For each snapshot:

1. Check version, source scope and status. Alert separately on collection coverage
   failures if desired. Never manufacture a human actor when evidence is absent.
2. For each `alert_eligible=true`, atomically claim event_id in persistent consumer
   storage. Only the successful claimant may send. Keep pending/delivered state and
   retry failed deliveries; n8n process memory is not durable deduplication.
3. Display source/host, event VM name, action, actor and occurred_at converted to
   Europe/Moscow. This is event time, not discovery or NetBox update time.
4. Mark delivered after successful delivery. A transport timeout still needs the
   destination's idempotency support or reconciliation to avoid duplicate delivery.

The feed retains at most 1000 events, merging by ID and preserving previous
evidence during provider read failures. A new event does not rewrite older actors.
An idle successful repeat does not PATCH NetBox solely to update a polling timestamp.
The field does not acknowledge consumer delivery. Poll frequently enough: source
retention, seven-day lookback, >1000 events, consumer outages, blocked source plans,
failed sync, or a deleted field can cause gaps. Baseline deletion/reset suppresses
historical alerts again. This must not be advertised as lossless audit delivery.

## Acceptance

1. Prepare the field, update Sync, build and apply a fresh plan on DEV-BA/DEV-BA2.
2. GET the device field; require available status and baseline events marked false.
3. Perform an authorized test change with a personal ESXi account. On the next
   successful sync require a new event with that actor and the real event time.
4. Check creation vs registration vs clone separately, and disk/CPU/memory edits.
5. Repeat sync: no new event IDs or duplicate alert. Exercise consumer webhook
   retries and persistent dedupe before enabling real chat notifications.
6. Test a denied EventManager read: ordinary VM discovery continues; prior event
   evidence remains and status shows permission_denied.

Official references:
- https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.event.EventManager.html
- https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.event.EventHistoryCollector.html
- https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.HistoryCollector.html
- https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.event.VmReconfiguredEvent.html
