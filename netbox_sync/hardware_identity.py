"""Typed physical-system observations. Never infer identity from IP, disk or asset IDs."""

from datetime import datetime, timezone
from uuid import UUID

KINDS = ("system_serial", "service_tag", "system_uuid")
PLACEHOLDERS = {
    "unknown",
    "none",
    "n/a",
    "na",
    "not specified",
    "not applicable",
    "to be filled by o.e.m.",
    "to be filled by oem",
    "default string",
    "default",
    "system serial number",
    "serial number",
    "not available",
    "o.e.m.",
}


def canonical(kind, value):
    if kind not in KINDS or not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 256 or not value.isprintable() or value.casefold() in PLACEHOLDERS:
        return None
    compact = value.replace("-", "").replace(" ", "").casefold()
    if not compact or set(compact) <= {"0"} or set(compact) <= {"f"} or compact in {"123456789", "0123456789"}:
        return None
    if kind == "system_uuid":
        try:
            return str(UUID(value))
        except ValueError:
            return None
    return value.casefold()


def observation(source, values, *, status=None, observed_at=None):
    identifiers = []
    for kind, value, path in values:
        normalized = canonical(kind, value)
        if normalized:
            identifiers.append(dict(kind=kind, value=normalized, field=path))
    identifiers = sorted({(r["kind"], r["value"], r["field"]) for r in identifiers})
    conflicts = [kind for kind in KINDS if len({v for k, v, p in identifiers if k == kind}) > 1]
    return dict(
        version=1,
        source=source,
        status="conflict" if conflicts else status or ("collected" if identifiers else "not_reported"),
        observed_at=observed_at or datetime.now(timezone.utc).isoformat(),
        identifiers=[dict(kind=k, value=v, field=p) for k, v, p in identifiers],
        conflicts=conflicts,
    )


def tokens(document, *, now=None):
    if not isinstance(document, dict) or document.get("version") != 1 or document.get("status") != "collected":
        return set()
    try:
        at = datetime.fromisoformat(document["observed_at"].replace("Z", "+00:00"))
        age = ((now or datetime.now(timezone.utc)) - at).total_seconds()
        if not -300 <= age <= 48 * 3600:
            return set()
        rows = document["identifiers"]
        values = {(r["kind"], canonical(r["kind"], r["value"])) for r in rows}
        values = {(k, v) for k, v in values if v}
        if any(len({v for k, v in values if k == kind}) > 1 for kind in KINDS):
            return set()
        return values
    except (KeyError, TypeError, ValueError, AttributeError):
        return set()


def collect_esxi(host):
    def get(obj, path):
        for part in path.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                break
        return obj

    try:
        info = get(host, "hardware.systemInfo")
        values = [
            ("system_serial", get(info, "serialNumber"), "hardware.systemInfo.serialNumber"),
            ("system_uuid", get(info, "uuid"), "hardware.systemInfo.uuid"),
            ("system_uuid", get(host, "summary.hardware.uuid"), "summary.hardware.uuid"),
        ]
        for entry in get(info, "otherIdentifyingInfo") or ():
            kind = {"SerialNumberTag": "system_serial", "ServiceTag": "service_tag"}.get(
                get(entry, "identifierType.key")
            )
            if kind:
                values.append(
                    (
                        kind,
                        get(entry, "identifierValue"),
                        "hardware.systemInfo.otherIdentifyingInfo." + get(entry, "identifierType.key"),
                    )
                )
        return observation("esxi", values)
    except Exception as exc:
        # Do not log SDK faults, connection data or credentials.
        denied = type(exc).__name__ in ("NoPermission", "NotAuthenticated")
        return observation("esxi", [], status="access_denied" if denied else "read_error")


def collect_proxmox():
    # Stock node hardware API exposes PCI/USB, not system DMI. No speculative
    # endpoint, guest SMBIOS, disk serial or subscription serverid fallback.
    return observation("proxmox", [], status="unsupported_api")


def selectel_observation(sections, observed_at):
    values = []
    coverage = {}
    for name in ("resource", "details", "hardware"):
        section = sections.get(name, {})
        coverage[name] = section.get("status", "not_collected")
        if section.get("status") != "collected" or section.get("retained"):
            continue
        data = section.get("data")
        if not isinstance(data, dict):
            continue
        for field, kind in (
            ("serial", "system_serial"),
            ("service_tag", "service_tag"),
            ("system_uuid", "system_uuid"),
        ):
            values.append((kind, data.get(field), name + "." + field))
    result = observation("selectel", values, observed_at=observed_at)
    result["coverage"] = coverage
    # hw_uuid, resource UUID and nested disk/board/chassis serials have different
    # namespaces. They are retained by inventory but never compared as system IDs.
    return result


def compare(left, right):
    if not left & right:
        return "none"
    common = {k for k, v in left} & {k for k, v in right}
    if any({v for k, v in left if k == kind} != {v for k, v in right if k == kind} for kind in common):
        return "conflict"
    return "match"
