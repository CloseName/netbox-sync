"""Validate the account import result before publishing successful completion."""


def confirmed_import(result, account):
    """Require the current Guard account-result contract, never just HTTP success."""
    if not isinstance(result, dict) or result.get("account") != account or "error" in result:
        return False
    counters = ["servers", "matched", "unmatched", "registry_resources", "retained"]
    if result.get("native_mode") == "automatic":
        counters.extend(("native_created", "native_adopted", "native_blocked"))
    elif result.get("native_mode") != "registry_only":
        return False
    return (
        all(type(result.get(key)) is int and result[key] >= 0 for key in counters)
        and all(type(result.get(key)) is bool for key in ("replayed", "writes_performed"))
        and isinstance(result.get("placement_pending"), list)
    )
