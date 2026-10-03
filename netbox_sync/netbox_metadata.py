MANAGED_DEVICE_CUSTOM_FIELDS = (
    'sync_identities',
    'sync_original_names',
    'hypervisor_version',
    'cpu_model',
    'cpu_vendor',
    'cpu_sockets',
    'cpu_cores',
    'cpu_threads',
    'memory_mb',
    'physical_disks',
    'esxi_host_network',
)

from .source_identity import (
    host_source_identity,
    merge_original_name,
    merge_source_identities,
    select_best_identity_matches,
    source_identity_match_rank,
)


def matches_sync_identity(
        custom_fields,
        host,
):
    return bool(sync_identity_match_rank(custom_fields, host))


def sync_identity_match_rank(custom_fields, host):
    """Return the centralized v2/v1 match priority for one host."""

    return source_identity_match_rank(
        custom_fields,
        host_source_identity(host),
        (host.source_id,),
        host.legacy_identity_owner,
    )


def find_sync_identity_matches(candidates, host):
    """Find best-ranked host records, retaining same-rank duplicates."""

    return select_best_identity_matches(
        candidates,
        lambda candidate: sync_identity_match_rank(
            getattr(candidate, 'custom_fields', None) or {}, host,
        ),
    )


def build_device_custom_fields(
        host,
        existing_custom_fields=None,
):
    existing = dict(
        existing_custom_fields or {}
    )

    desired_identity = host_source_identity(host)
    merged_identities = merge_source_identities(existing, desired_identity)
    merged_original_names = merge_original_name(
        existing, desired_identity, host.original_name,
    )

    physical_disks = []

    for disk in sorted(
        host.disks,
        key=lambda item: item.path,
    ):
        physical_disks.append({
            'path': disk.path,
            'model': disk.model,
            'serial': disk.serial,
            'type': disk.disk_type,
            'size_bytes': disk.size_bytes,
            'health': disk.health,
        })

    result = dict(existing)

    result.update({
        'sync_identities':
            merged_identities,

        'sync_original_names':
            merged_original_names,

        'hypervisor_version':
            host.hypervisor_version,

        'cpu_model':
            host.cpu.model,

        'cpu_vendor':
            host.cpu.vendor,

        'cpu_sockets':
            host.cpu.sockets,

        'cpu_cores':
            host.cpu.cores,

        'cpu_threads':
            host.cpu.logical_cpus,

        'memory_mb':
            host.memory_bytes // 1024**2,

        'physical_disks':
            physical_disks,
    })

    if host.source == 'esxi' and host.esxi_host_network is not None:
        from copy import deepcopy
        result['esxi_host_network'] = deepcopy(host.esxi_host_network)

    return result
