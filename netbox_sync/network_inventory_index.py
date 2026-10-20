"""Shared record indexing where planner and writer normalization agree."""


def index_mac_records(records, canonical_mac):
    """Group original MAC records under canonical addresses without collapsing duplicates."""
    result = {}
    for record in records:
        value = canonical_mac(record.serialize().get("mac_address"))
        if value:
            result.setdefault(value, []).append(record)
    return result
