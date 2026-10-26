"""Closed import diagnostic vocabulary; never publish remote exception text."""

REASONS = frozenset(
    {
        "PROVIDER_COMPLETE_NETBOX_VISIBILITY_REQUIRED",
        "PROVIDER_NATIVE_SCOPE_CONFLICT",
        "PROVIDER_PLACEMENT_IDENTITY_REQUIRED",
        "PROVIDER_IDENTITY_INVALID",
        "PROVIDER_ACCOUNT_MISMATCH",
        "PROVIDER_NONCE_CONFLICT",
        "PROVIDER_ACCOUNT_DELETED",
        "PROVIDER_HISTORICAL_RUN_RETIRED",
        "PROVIDER_REVIEW_STALE",
        "PERMISSION_DENIED",
        "PROVIDER_NATIVE_PERMISSIONS_REQUIRED",
        "PROVIDER_FIELD_OWNED",
        "PROVIDER_PROJECTION_UNCLAIMED",
        "PROVIDER_IPAM_FIELD_OWNED",
        "DATABASE_CONSTRAINT",
        "OBJECT_VALIDATION",
        "INPUT_OR_POLICY_REJECTED",
        "INPUT_SHAPE_INVALID",
        "POLICY_REJECTED",
        "IMPORT_REJECTED",
    }
)


def diagnostic(value):
    """Sanitize again at persistence and public boundaries."""
    if not isinstance(value, dict):
        return {}
    result = {}
    if isinstance(value.get("reason"), str) and value["reason"] in REASONS:
        result["reason"] = value["reason"]
    if type(value.get("http_status")) is int and 100 <= value["http_status"] <= 599:
        result["http_status"] = value["http_status"]
    from uuid import UUID

    try:
        result["event_id"] = str(UUID(str(value["event_id"])))
    except (KeyError, ValueError, TypeError, AttributeError):
        pass
    return result


def atomic_refusal(method, path, status, value, body):
    """Only the exact account/run response can establish an atomic refusal."""
    return (
        method == "POST"
        and path == "providers/account-import/"
        and status == 409
        and value.get("code") == "PROVIDER_IMPORT_ROLLED_BACK"
        and value.get("rolled_back") is True
        and isinstance(body, dict)
        and isinstance(body.get("nonce"), str)
        and isinstance(body.get("account"), str)
        and value.get("nonce") == body["nonce"]
        and value.get("account") == body["account"]
    )
