from .netbox_apply import apply_hosts
from .netbox_vm_apply import apply_virtual_machines
from .netbox_vm_network_apply import apply_vm_networks
from .netbox_lxc_apply import apply_lxc_containers
from .netbox_lxc_network_apply import apply_lxc_networks
from .netbox_disappearance import (
    report_missing_managed_objects,
)


STAGES = (
    (
        'HOST',
        apply_hosts,
    ),
    (
        'QEMU VM',
        apply_virtual_machines,
    ),
    (
        'QEMU NETWORK',
        apply_vm_networks,
    ),
    (
        'LXC',
        apply_lxc_containers,
    ),
    (
        'LXC NETWORK',
        apply_lxc_networks,
    ),
)


def _run_stage(
    name,
    function,
    nb_api,
    hosts,
    config,
    *,
    confirmed,
    phase,
):
    print()
    print(
        '========================================'
    )
    print(
        f'FULL SYNC {phase}: {name}'
    )
    print(
        '========================================'
    )

    function(
        nb_api,
        hosts,
        config,
        confirmed=confirmed,
    )


def apply_full_sync(
    nb_api,
    hosts,
    config,
    *,
    confirmed=False,
):
    from .host_mapping import validate
    validate(nb_api,config,hosts)
    print(
        '=== FULL PROXMOX SYNC ==='
    )

    print(
        'write_enabled='
        + (
            'yes'
            if confirmed
            else 'no'
        )
    )

    print()
    print(
        '=== GLOBAL PRECHECK PHASE ==='
    )

    # Critical safety property:
    # every stage must complete its read-only
    # precheck before ANY stage may write.
    for name, function in STAGES:
        _run_stage(
            name,
            function,
            nb_api,
            hosts,
            config,
            confirmed=False,
            phase='PRECHECK',
        )

    print()
    print(
        '========================================'
    )
    print(
        'FULL SYNC PRECHECK: '
        'DISAPPEARANCE'
    )
    print(
        '========================================'
    )

    report_missing_managed_objects(
        nb_api,
        hosts,
        config,
    )

    print()
    print(
        '========================================'
    )
    print(
        'GLOBAL PRECHECK PASSED'
    )
    print(
        '========================================'
    )

    if not confirmed:
        print(
            'APPLY_CONFIRM=FULL_WRITE '
            'is not set.'
        )
        print(
            'No changes were written '
            'to NetBox.'
        )
        return

    print()
    print(
        '=== WRITE PHASE ==='
    )

    for name, function in STAGES:
        _run_stage(
            name,
            function,
            nb_api,
            hosts,
            config,
            confirmed=True,
            phase='WRITE',
        )

    print()
    print(
        '========================================'
    )
    print(
        'FULL PROXMOX SYNC COMPLETED'
    )
    print(
        '========================================'
    )
