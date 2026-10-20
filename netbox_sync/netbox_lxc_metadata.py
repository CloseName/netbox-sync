MANAGED_LXC_CUSTOM_FIELDS = (
    "sync_identities",
    "sync_original_names",
    "guest_kind",
    "guest_architecture",
    "guest_os_type",
    "swap_mb",
)

from .source_identity import (
    lxc_source_identity,
    merge_original_name,
    merge_source_identities,
    select_best_identity_matches,
    source_identity_match_rank,
)


def lxc_identity_source_id(container):
    source_id = str(container.source_id)

    prefix = f"{container.source}:"

    if source_id.startswith(prefix):
        return source_id[len(prefix) :]

    return source_id


def matches_lxc_sync_identity(
    custom_fields,
    container,
):
    return bool(lxc_sync_identity_match_rank(custom_fields, container))


def lxc_sync_identity_match_rank(custom_fields, container):
    """Return the centralized v2/v1 match priority for one LXC."""

    return source_identity_match_rank(
        custom_fields,
        lxc_source_identity(container),
        (lxc_identity_source_id(container),),
        container.legacy_identity_owner,
    )


def find_lxc_sync_identity_matches(candidates, container):
    """Find best-ranked LXC records, retaining same-rank duplicates."""

    return select_best_identity_matches(
        candidates,
        lambda candidate: lxc_sync_identity_match_rank(
            getattr(candidate, "custom_fields", None) or {},
            container,
        ),
    )


def build_lxc_custom_fields(
    container,
    existing_custom_fields=None,
):
    existing = dict(existing_custom_fields or {})

    desired_identity = lxc_source_identity(container)
    merged_identities = merge_source_identities(existing, desired_identity)
    merged_original_names = merge_original_name(
        existing,
        desired_identity,
        container.original_name,
    )

    result = dict(existing)

    result.update(
        {
            "sync_identities": merged_identities,
            "sync_original_names": merged_original_names,
            "guest_kind": "lxc",
            "guest_architecture": container.architecture,
            "guest_os_type": container.os_type,
            "swap_mb": container.swap_bytes // 1024**2,
        }
    )

    return result
