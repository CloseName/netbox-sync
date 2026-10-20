"""Read values from NetBox API records without coercing identifiers.

These helpers preserve the existing planner/apply conventions. They are not
validators: boolean IDs, dictionary values and record attributes pass through
unchanged. Stricter provider and network-scope helpers have separate contracts.
"""


def object_id(value):
    """Extract a relationship identifier from an integer, mapping or record."""

    if value is None:
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, dict):
        return value.get("id")

    return getattr(value, "id", None)


def choice_value(value):
    """Extract a choice value while retaining already scalar values."""

    if value is None:
        return None

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        return value.get("value")

    return getattr(value, "value", value)
