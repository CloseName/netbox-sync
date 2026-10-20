"""Read-only planning stages preserving existing selection and output contracts."""


def find_missing_objects(target_vms, interfaces_by_vm, discovered_guests, discovered_interfaces, managed_identity):
    managed_guests = 0
    missing_guests = []

    managed_interfaces = 0
    missing_interfaces = []

    for vm in target_vms:
        guest_identity = (
            managed_identity(
                getattr(
                    vm,
                    'custom_fields',
                    None,
                )
                or {}
            )
        )

        if guest_identity is None:
            continue

        managed_guests += 1

        guest_missing = (
            guest_identity
            not in discovered_guests
        )

        if guest_missing:
            missing_guests.append(
                (
                    vm,
                    guest_identity,
                )
            )

        # If the whole guest disappeared,
        # its interfaces are implicitly stale.
        # Do not duplicate every NIC warning.
        if guest_missing:
            continue

        for interface in (
            interfaces_by_vm.get(
                vm.id,
                [],
            )
        ):
            interface_identity = (
                managed_identity(
                    getattr(
                        interface,
                        'custom_fields',
                        None,
                    )
                    or {}
                )
            )

            if (
                interface_identity
                is None
            ):
                continue

            managed_interfaces += 1

            if (
                interface_identity
                not in discovered_interfaces
            ):
                missing_interfaces.append(
                    (
                        vm,
                        interface,
                        interface_identity,
                    )
                )

    return managed_guests, missing_guests, managed_interfaces, missing_interfaces


def print_disappearance_report(managed_guests, missing_guests, managed_interfaces, missing_interfaces, discovered_guests, discovered_interfaces, *, _identity_label):
    print(
        '=== DISAPPEARANCE REPORT ==='
    )

    print(
        f'managed_guests='
        f'{managed_guests}'
    )

    print(
        f'discovered_guests='
        f'{len(discovered_guests)}'
    )

    print(
        f'missing_guests='
        f'{len(missing_guests)}'
    )

    print(
        f'managed_interfaces='
        f'{managed_interfaces}'
    )

    print(
        f'discovered_interfaces='
        f'{len(discovered_interfaces)}'
    )

    print(
        f'missing_interfaces='
        f'{len(missing_interfaces)}'
    )

    for (
        vm,
        identity,
    ) in missing_guests:
        print(
            f'WARNING MISSING GUEST '
            f'id={vm.id} '
            f'name={vm.name!r} '
            f'identity={_identity_label(identity)} '
            f'action=retained'
        )

    for (
        vm,
        interface,
        identity,
    ) in missing_interfaces:
        print(
            f'WARNING MISSING INTERFACE '
            f'vm_id={vm.id} '
            f'vm={vm.name!r} '
            f'interface_id='
            f'{interface.id} '
            f'name='
            f'{interface.name!r} '
            f'identity={_identity_label(identity)} '
            f'action=retained'
        )

    if (
        not missing_guests
        and not missing_interfaces
    ):
        print(
            'DISAPPEARANCE STATUS CLEAN'
        )

    print(
        'No objects were deleted.'
    )
