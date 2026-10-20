"""VM application report; preserve provider-specific behavior."""


def report_vm_precheck(site, cluster, discovered, target_vms, contexts, *, _identity, _desired_status, _desired_memory, _desired_disk, _desired_start_on_boot, VMApplyError):
    print(
        '=== VM APPLY PRECHECK ==='
    )
    print(
        f'target_site={site.name} '
        f'cluster={cluster.name}'
    )
    print(
        f'discovered={len(discovered)} '
        f'existing_in_cluster='
        f'{len(target_vms)}'
    )
    print()

    blocked = 0

    for context in contexts:
        vm = context['vm']

        if context['action'] == 'blocked':
            blocked += 1

            print(
                f'BLOCKED VM '
                f'vmid={vm.vmid} '
                f'name={vm.original_name!r} '
                f'identity={_identity(vm)} '
                f'reason={context["reason"]}'
            )

            for candidate in (
                context['candidates']
            ):
                print(
                    f'  candidate '
                    f'id={candidate.id} '
                    f'name={candidate.name!r}'
                )

            continue

        if context['action'] == 'create':
            print(
                f'CREATE VM '
                f'vmid={vm.vmid} '
                f'name={vm.original_name!r} '
                f'identity={_identity(vm)}'
            )
        else:
            existing = context['existing']

            print(
                f'MATCH VM '
                f'id={existing.id} '
                f'vmid={vm.vmid} '
                f'name={vm.original_name!r} '
                f'identity={_identity(vm)} '
                f'reason=sync_identity'
            )

        print(
            f'  status='
            f'{_desired_status(vm)} '
            f'vcpus={vm.vcpus} '
            f'memory={_desired_memory(vm)} '
            f'disk={_desired_disk(vm)} '
            f'start_on_boot='
            f'{_desired_start_on_boot(vm)}'
        )

        print(
            f'  managed_custom_fields_changed='
            f'{len(context["changed_custom_fields"])}'
        )

        if context['action'] == 'match':
            fields = list(
                context['changes']
            )

            print(
                '  pending_fields='
                + (
                    ','.join(fields)
                    if fields
                    else '-'
                )
            )

    print()

    if blocked:
        print(
            f'PRECHECK BLOCKED '
            f'blocked={blocked}'
        )
        print(
            'No changes were written '
            'to NetBox.'
        )

        raise VMApplyError(
            'VM apply precheck failed'
        )

    print('PRECHECK PASSED')

