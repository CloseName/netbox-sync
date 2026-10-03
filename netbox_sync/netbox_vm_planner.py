from .netbox_vm_name import netbox_vm_name
import json

from .netbox_vm_metadata import (
    MANAGED_VM_CUSTOM_FIELDS,
    build_vm_custom_fields,
    find_vm_sync_identity_matches,
    vm_identity_source_id,
)


def _netbox_vm_status(source_status):
    mapping = {
        'running': 'active',
        'stopped': 'offline',
        'paused': 'paused',
    }

    if source_status not in mapping:
        raise RuntimeError(
            f'Unsupported Proxmox VM status: '
            f'{source_status!r}'
        )

    return mapping[source_status]


def _vm_memory_mib(vm):
    return (
        vm.memory_bytes
        // 1024**2
    )


def _vm_disk_mib(vm):
    return sum(
        disk.size_bytes
        for disk in vm.disks
    ) // 1024**2


def _vm_start_on_boot(vm):
    return (
        'on'
        if vm.autostart
        else 'off'
    )


def _find_vm_match(
        existing_vms,
        discovered_vm,
):
    """
    Safe VM bootstrap matching:

      1. sync identity -> MATCH
      2. exact name in target cluster
         -> ADOPT_CANDIDATE only
      3. no match -> CREATE
      4. duplicates -> CONFLICT
    """

    identity_matches = find_vm_sync_identity_matches(
        existing_vms, discovered_vm,
    )

    if len(identity_matches) > 1:
        return (
            'conflict_identity',
            identity_matches,
        )

    if len(identity_matches) == 1:
        return (
            'sync_identity',
            identity_matches,
        )

    name_matches = [
        candidate
        for candidate in existing_vms
        if (
            candidate.name.casefold()
            == netbox_vm_name(discovered_vm).casefold()
            and getattr(
                candidate,
                'tenant',
                None,
            ) is None
        )
    ]

    if len(name_matches) > 1:
        return (
            'conflict_name',
            name_matches,
        )

    if len(name_matches) == 1:
        return (
            'adopt_candidate',
            name_matches,
        )

    return (
        'create',
        [],
    )


def _print_desired_vm(
        vm,
        cluster,
        existing=None,
):
    desired_status = (
        _netbox_vm_status(
            vm.status
        )
    )

    desired_vcpus = vm.vcpus
    desired_memory = (
        _vm_memory_mib(vm)
    )

    desired_disk = (
        _vm_disk_mib(vm)
    )

    desired_start_on_boot = (
        _vm_start_on_boot(vm)
    )

    print(
        f'      cluster='
        f'{cluster.name}'
    )

    print(
        f'      status='
        f'{desired_status} '
        f'(source={vm.status})'
    )

    print(
        f'      vcpus={desired_vcpus}'
    )

    print(
        f'      memory_mib='
        f'{desired_memory}'
    )

    print(
        f'      disk_mib='
        f'{desired_disk}'
    )

    print(
        f'      start_on_boot='
        f'{desired_start_on_boot}'
    )

    print(
        f'      disks='
        f'{len(vm.disks)}'
    )

    if vm.disks:
        for disk in sorted(
            vm.disks,
            key=lambda item: item.name,
        ):
            print(
                f'        '
                f'{disk.name} '
                f'storage='
                f'{disk.storage or "-"} '
                f'size_mib='
                f'{disk.size_bytes // 1024**2}'
            )

    existing_custom_fields = (
        dict(
            getattr(
                existing,
                'custom_fields',
                None,
            )
            or {}
        )
        if existing is not None
        else {}
    )

    desired_custom_fields = (
        build_vm_custom_fields(
            vm,
            existing_custom_fields,
        )
    )

    print(
        '      managed_custom_fields:'
    )

    for field_name in (
        MANAGED_VM_CUSTOM_FIELDS
    ):
        current = (
            existing_custom_fields.get(
                field_name
            )
        )

        desired = (
            desired_custom_fields.get(
                field_name
            )
        )

        action = (
            'KEEP'
            if current == desired
            else 'SET'
        )

        rendered = json.dumps(
            desired,
            ensure_ascii=False,
            sort_keys=True,
        )

        print(
            f'        {action} '
            f'{field_name}='
            f'{rendered}'
        )


def plan_virtual_machines(
        nb_api,
        host,
        cluster,
):
    print()
    print('  QEMU VIRTUAL MACHINES')

    if cluster is None:
        print(
            '    BLOCKED '
            'target cluster does not exist'
        )
        return

    existing_vms = list(
        nb_api.virtualization
        .virtual_machines
        .filter(
            cluster_id=cluster.id
        )
    )

    print(
        f'    discovered='
        f'{len(host.virtual_machines)} '
        f'existing_in_cluster='
        f'{len(existing_vms)}'
    )

    print(
        '    bootstrap_policy='
        'identity-match; '
        'name-only=adopt-candidate; '
        'no automatic adoption'
    )

    print()

    counters = {
        'match': 0,
        'adopt_candidate': 0,
        'create': 0,
        'conflict': 0,
    }

    for vm in sorted(
        host.virtual_machines,
        key=lambda item: item.vmid,
    ):
        (
            reason,
            matches,
        ) = _find_vm_match(
            existing_vms,
            vm,
        )

        identity = (
            f'{vm.source}:'
            f'{vm_identity_source_id(vm)}'
        )

        if reason == 'sync_identity':
            existing = matches[0]

            counters[
                'match'
            ] += 1

            print(
                f'    MATCH VM '
                f'id={existing.id} '
                f'vmid={vm.vmid} '
                f'name={vm.original_name!r} '
                f'reason=sync_identity'
            )

            _print_desired_vm(
                vm,
                cluster,
                existing=existing,
            )

        elif reason == 'adopt_candidate':
            existing = matches[0]

            counters[
                'adopt_candidate'
            ] += 1

            print(
                f'    ADOPT CANDIDATE '
                f'id={existing.id} '
                f'vmid={vm.vmid} '
                f'name={vm.original_name!r} '
                f'reason=exact_name_in_cluster '
                f'action=not-adopted'
            )

            _print_desired_vm(
                vm,
                cluster,
                existing=existing,
            )

        elif reason == 'create':
            counters[
                'create'
            ] += 1

            print(
                f'    CREATE VM '
                f'vmid={vm.vmid} '
                f'name={vm.original_name!r}'
            )

            _print_desired_vm(
                vm,
                cluster,
                existing=None,
            )

        else:
            counters[
                'conflict'
            ] += 1

            print(
                f'    CONFLICT VM '
                f'vmid={vm.vmid} '
                f'name={vm.original_name!r} '
                f'reason={reason} '
                f'matches={len(matches)} '
                f'action=blocked'
            )

            for existing in matches:
                print(
                    f'      candidate '
                    f'id={existing.id} '
                    f'name={existing.name!r}'
                )

        print(
            f'      source_identity='
            f'{identity}'
        )

        print()

    print('    VM PLAN SUMMARY')
    print(
        f'      match='
        f'{counters["match"]}'
    )

    print(
        f'      adopt_candidate='
        f'{counters["adopt_candidate"]}'
    )

    print(
        f'      create='
        f'{counters["create"]}'
    )

    print(
        f'      conflict='
        f'{counters["conflict"]}'
    )
