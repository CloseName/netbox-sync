"""Allowlisted model/field/code projection for public Selectel errors."""

MODELS = frozenset(
    {
        "dcim.device",
        "dcim.site",
        "dcim.region",
        "dcim.manufacturer",
        "dcim.devicetype",
        "dcim.devicerole",
        "virtualization.virtualmachine",
        "extras.customfield",
    }
)
FIELDS = frozenset(
    {
        "name",
        "slug",
        "serial",
        "status",
        "site",
        "region",
        "cluster",
        "device",
        "device_type",
        "role",
        "tenant",
        "rack",
        "location",
        "position",
        "face",
        "vcpus",
        "memory",
        "disk",
        "custom_field_data",
        "description",
        "comments",
        "manufacturer",
        "model",
        "type",
        "group_name",
        "required",
        "unique",
        "__all__",
    }
)
CODES = frozenset(
    {
        "blank",
        "null",
        "invalid",
        "invalid_choice",
        "unique",
        "unique_together",
        "max_length",
        "min_length",
        "max_value",
        "min_value",
        "max_digits",
        "max_decimal_places",
        "max_whole_digits",
    }
)


def validation_detail(value):
    """Never trust diagnostic dictionaries across the child/API boundaries."""
    if not isinstance(value, dict):
        return None

    def allowed(key, choices, fallback):
        candidate = value.get(key)
        return candidate if isinstance(candidate, str) and candidate in choices else fallback

    result = {
        "model": allowed("model", MODELS, "unknown"),
        "phase": allowed("phase", {"full_clean", "save"}, "unknown"),
        "issues": [],
    }
    if type(value.get("object_id")) is int and value["object_id"] > 0:
        result["object_id"] = value["object_id"]
    issues = value.get("issues")
    if isinstance(issues, list):
        for row in issues[:12]:
            if not isinstance(row, dict):
                continue
            field, code = row.get("field"), row.get("code")
            result["issues"].append(
                {
                    "field": field if isinstance(field, str) and field in FIELDS else "other",
                    "code": code if isinstance(code, str) and code in CODES else "unspecified",
                }
            )
    return result
