from .lxc_plan_container import plan_lxc_container
from .lxc_plan_report import print_desired_lxc
import json

from .netbox_lxc_metadata import (
    MANAGED_LXC_CUSTOM_FIELDS,
    build_lxc_custom_fields,
    find_lxc_sync_identity_matches,
    lxc_identity_source_id,
)


def _status(value):
    mapping = {
        'running': 'active',
        'stopped': 'offline',
        'paused': 'paused',
    }

    if value not in mapping:
        raise RuntimeError(
            f'Unsupported LXC status: '
            f'{value!r}'
        )

    return mapping[value]


def _disk_mib(container):
    return sum(
        disk.size_bytes
        for disk in container.disks
    ) // 1024**2


def plan_lxc_containers(
        nb_api,
        host,
        cluster,
):
    print()
    print(
        '  LXC CONTAINERS'
    )

    existing_vms = list(
        nb_api.virtualization
        .virtual_machines
        .filter(
            cluster_id=cluster.id
        )
    )

    counters = {
        'match': 0,
        'create': 0,
        'adopt_candidate': 0,
        'conflict': 0,
    }

    for container in sorted(
        host.containers,
        key=lambda item: item.vmid,
    ):
        plan_lxc_container(
            container, existing_vms, cluster, counters,
            find_lxc_sync_identity_matches=find_lxc_sync_identity_matches,
            print_desired_lxc=print_desired_lxc, lxc_identity_source_id=lxc_identity_source_id,
            _status=_status, _disk_mib=_disk_mib, build_lxc_custom_fields=build_lxc_custom_fields,
            MANAGED_LXC_CUSTOM_FIELDS=MANAGED_LXC_CUSTOM_FIELDS, json=json,
        )

    print()
    print(
        '    LXC PLAN SUMMARY'
    )

    for key in (
        'match',
        'create',
        'adopt_candidate',
        'conflict',
    ):
        print(
            f'      {key}='
            f'{counters[key]}'
        )
