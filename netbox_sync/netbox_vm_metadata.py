"""Build and match managed VM identity and custom-field metadata."""

MANAGED_VM_CUSTOM_FIELDS = (
    "sync_identities",
    "sync_original_names",
)

from .source_identity import (
    merge_original_name,
    merge_source_identities,
    virtual_machine_source_identity,
    select_best_identity_matches,
    source_identity_match_rank,
)


def vm_identity_source_id(vm):
    """
    Return a source-local VM identifier.

    Discovery currently exposes:
        proxmox:new-infra-test:100

    The custom field stores:
        source=proxmox
        source_id=new-infra-test:100
    """

    source_id = str(vm.source_id)
    prefix = f"{vm.source}:"

    if source_id.startswith(prefix):
        return source_id[len(prefix) :]

    return source_id


def matches_vm_sync_identity(
    custom_fields,
    vm,
):
    return bool(vm_sync_identity_match_rank(custom_fields, vm))


def vm_sync_identity_match_rank(custom_fields, vm):
    """Return the centralized v2/v1 match priority for one VM."""

    wanted_id = vm_identity_source_id(vm)
    return source_identity_match_rank(
        custom_fields,
        virtual_machine_source_identity(vm),
        (wanted_id, vm.source_id),
        vm.legacy_identity_owner,
    )


def find_vm_sync_identity_matches(candidates, vm):
    """Find best-ranked VM records, retaining same-rank duplicates."""

    return select_best_identity_matches(
        candidates,
        lambda candidate: vm_sync_identity_match_rank(
            getattr(candidate, "custom_fields", None) or {},
            vm,
        ),
    )


def build_vm_custom_fields(
    vm,
    existing_custom_fields=None,
):
    existing = dict(existing_custom_fields or {})
    normalized = dict(existing)
    if normalized.get("sync_identities") is None:
        normalized["sync_identities"] = []
    if normalized.get("sync_original_names") is None:
        normalized["sync_original_names"] = {}

    desired_identity = virtual_machine_source_identity(vm)
    merged_identities = merge_source_identities(normalized, desired_identity)
    merged_original_names = merge_original_name(
        normalized,
        desired_identity,
        vm.original_name,
    )

    result = dict(existing)

    result.update(
        {
            "sync_identities": merged_identities,
            "sync_original_names": merged_original_names,
        }
    )

    return result
