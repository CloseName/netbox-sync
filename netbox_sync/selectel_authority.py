"""Read provider-owned field names from Guard's protected inventory projection."""


def owned_fields(custom_fields):
    if not isinstance(custom_fields, dict) or not custom_fields.get("selectel_refs"):
        return set()
    snapshot = custom_fields.get("selectel_inventory")
    fields = snapshot.get("native_fields") if isinstance(snapshot, dict) else None
    if not isinstance(fields, list) or any(not isinstance(f, str) for f in fields):
        return set()
    return set(fields) & {"name", "serial", "site_id", "status", "vcpus", "memory"}
