"""Bounded ESXi evidence for alert consumers, never inferred from inventory diffs.

Only explicit SDK fields are exported. Free-form messages/configuration may contain
secrets and are deliberately omitted. MoRefs are historical references, not UUIDs.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import time

FIELD = "esxi_events"
LIMIT = 1000
PAGE = 200
LOOKBACK_DAYS = 7
LOGGER = logging.getLogger(__name__)
TYPES = {
    "VmCreatedEvent": "created",
    "VmClonedEvent": "cloned",
    "VmDeployedEvent": "deployed",
    "VmRegisteredEvent": "registered",
    "VmRemovedEvent": "removed",
    "VmReconfiguredEvent": "reconfigured",
    "VmPoweredOnEvent": "powered_on",
    "VmPoweredOffEvent": "powered_off",
    "VmResettingEvent": "reset_requested",
    "VmSuspendedEvent": "suspended",
    "VmMigratedEvent": "migrated",
    "VmRelocatedEvent": "relocated",
}


def text(value, limit=256):
    """Strip nonprintable characters and bound event text."""

    return "".join(c for c in str(value or "") if c.isprintable())[:limit]


def normalize(event, source, host):
    """Project a supported ESXi event into bounded, timestamped evidence with a stable digest."""

    kind = type(event).__name__.split(".")[-1]
    if kind not in TYPES:
        return None
    timestamp = getattr(event, "createdTime", None)
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
        raise ValueError("Invalid event timestamp")
    key = getattr(event, "key", None)
    if not isinstance(key, int):
        raise ValueError("Invalid event key")
    timestamp = timestamp.astimezone(timezone.utc).isoformat(timespec="microseconds")
    argument = getattr(event, "vm", None)
    reference = getattr(getattr(argument, "vm", None), "_moId", None)
    actor = text(getattr(event, "userName", None)) or None
    row = {
        "provider_event_id": key,
        "occurred_at": timestamp,
        "event_type": kind,
        "action": TYPES[kind],
        "actor": actor,
        "actor_status": "reported" if actor else "unknown",
        "vm_reference": text(reference) or None,
        "vm_name": text(getattr(argument, "name", None)) or None,
    }
    # Include time/type to tolerate provider event-key reuse after reset/restore.
    row["event_id"] = hashlib.sha256(
        json.dumps([source, host, key, timestamp, kind], separators=(",", ":")).encode()
    ).hexdigest()
    spec = getattr(event, "configSpec", None)
    changes = {}
    for name in ("numCPUs", "memoryMB"):
        value = getattr(spec, name, None)
        if isinstance(value, int) and value > 0:
            changes[name] = value
    devices = []
    for item in (getattr(spec, "deviceChange", None) or ())[:32]:
        operation = str(getattr(item, "operation", ""))
        device = getattr(item, "device", None)
        device_kind = type(device).__name__.split(".")[-1]
        key = getattr(device, "key", None)
        if operation in ("add", "edit", "remove") and isinstance(key, int):
            detail = {"operation": operation, "device_type": text(device_kind, 64), "key": key}
            capacity = getattr(device, "capacityInBytes", None)
            if not isinstance(capacity, int):
                kb = getattr(device, "capacityInKB", None)
                capacity = kb * 1024 if isinstance(kb, int) else None
            if isinstance(capacity, int) and capacity >= 0:
                detail["capacity_bytes"] = capacity
            devices.append(detail)
    if devices:
        changes["devices"] = devices
    row["changes"] = changes
    return row


def collect_events(content, host_object, source, host_id, *, now=None):
    """At most 1000 recent events, bounded calls; optional failures stay isolated."""
    from pyVmomi import vim

    collector = None
    rows = {}
    started = time.monotonic()
    now = now or datetime.now(timezone.utc)
    begin = now - timedelta(days=LOOKBACK_DAYS)
    status = "unavailable"
    try:
        manager = getattr(content, "eventManager", None)
        if manager is None:
            return {"status": "unsupported", "events": []}
        spec = vim.event.EventFilterSpec(
            entity=vim.event.EventFilterSpec.ByEntity(entity=host_object, recursion="all"),
            time=vim.event.EventFilterSpec.ByTime(beginTime=begin, endTime=now),
            eventTypeId=list(TYPES),
            disableFullMessage=True,
        )
        collector = manager.CreateCollectorForEvents(spec)
        collector.SetCollectorPageSize(PAGE)
        collector.ResetCollector()
        batch = collector.latestPage or []
        status = "partial"
        for _ in range(6):
            for event in batch:
                row = normalize(event, source, host_id)
                if row and begin <= datetime.fromisoformat(row["occurred_at"]) <= now:
                    rows[row["event_id"]] = row
            if len(rows) >= LIMIT or time.monotonic() - started > 20:
                break
            batch = collector.ReadPreviousEvents(PAGE) or []
            if not batch:
                status = "available"
                break
    except Exception as error:
        # Never emit provider fault text (can contain private configuration).
        status = "permission_denied" if isinstance(error, vim.fault.NoPermission) else "unavailable"
        rows = {}
    finally:
        if collector is not None:
            try:
                collector.DestroyCollector()
            except Exception:
                pass
    if status != "available":
        LOGGER.warning("ESXi event collection status=%s", status)
    return {"status": status, "events": sorted(rows.values(), key=lambda r: (r["occurred_at"], r["event_id"]))[-LIMIT:]}


def merge_events(previous, observed, source, host):
    """Stable bounded history. Baseline is quiet; consumers persist event_id dedupe."""
    if previous is not None and not isinstance(previous, dict):
        raise ValueError("Invalid existing event evidence")
    previous = deepcopy(previous) if isinstance(previous, dict) else {}
    if previous and (
        previous.get("version") != 1 or previous.get("source_instance") != source or previous.get("host_id") != host
    ):
        raise ValueError("Event source scope mismatch")
    initialized = previous.get("initialized", False)
    boundary = previous.get("baseline_through", "")
    if not initialized and observed["status"] in ("available", "partial"):
        boundary = max((r["occurred_at"] for r in observed["events"]), default="")
    rows = {r["event_id"]: r for r in previous.get("events", [])}
    for event in observed["events"]:
        if event["event_id"] not in rows:
            rows[event["event_id"]] = {**event, "alert_eligible": bool(initialized and event["occurred_at"] > boundary)}
    # A partial first read is still a baseline; do not silently label it complete.
    initialized = initialized or observed["status"] in ("available", "partial")
    return {
        "version": 1,
        "source_instance": source,
        "host_id": host,
        "status": observed["status"],
        "initialized": initialized,
        "baseline_through": boundary,
        "lookback_days": LOOKBACK_DAYS,
        "retention_limit": LIMIT,
        "events": sorted(rows.values(), key=lambda r: (r["occurred_at"], r["event_id"]))[-LIMIT:],
    }


def apply_event_snapshots(api, hosts):
    """Merge event evidence only for uniquely matched hosts with a ready custom field."""

    from .netbox_metadata import find_sync_identity_matches
    from .prerequisites import reconcile

    hosts = [h for h in hosts if h.esxi_events is not None]
    if not hosts:
        return
    fields = [r.serialize() for r in api.extras.custom_fields.filter(name=FIELD)]
    if next(r for r in reconcile(fields) if r["name"] == FIELD)["status"] != "ready":
        LOGGER.warning("ESXi event export skipped: prepare esxi_events custom field")
        return
    devices = list(api.dcim.devices.all())
    for host in hosts:
        matches = find_sync_identity_matches(devices, host)
        if len(matches) != 1:
            LOGGER.warning("ESXi event export skipped: host identity not unique")
            continue
        device = matches[0]
        values = deepcopy(getattr(device, "custom_fields", None) or {})
        try:
            merged = merge_events(values.get(FIELD), host.esxi_events, host.source_instance, host.source_id)
        except (ValueError, KeyError, TypeError):
            LOGGER.warning("ESXi event export skipped: incompatible existing evidence")
            continue
        if values.get(FIELD) != merged:
            values[FIELD] = merged
            device.update({"custom_fields": values})
