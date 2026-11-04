"""Read provider-owned field names from Guard's protected inventory projection."""


def owned_fields(custom_fields):
    """Return only recognized native fields explicitly owned by Selectel inventory."""

    if not isinstance(custom_fields, dict) or not custom_fields.get("selectel_refs"):
        return set()
    snapshot = custom_fields.get("selectel_inventory")
    fields = snapshot.get("native_fields") if isinstance(snapshot, dict) else None
    if not isinstance(fields, list) or any(not isinstance(f, str) for f in fields):
        return set()
    return set(fields) & {
        "name",
        "serial",
        "site_id",
        "status",
        "vcpus",
        "memory",
        "primary_ip4_id",
        "primary_ip6_id",
    }


def primary_owned(record):
    """Protect the primary selected by the provider's confirmed interface projection."""
    return "primary_ip4_id" in owned_fields(record.serialize().get("custom_fields"))
