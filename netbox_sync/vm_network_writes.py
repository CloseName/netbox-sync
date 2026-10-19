"""Write previously validated VM network contexts in their original order."""
from .interface_display import interface_display_name
from .vm_network_preflight import (
    _assigned_object, _current_primary_mac_id, _current_primary_ip_id,
)


def write_vm_networks(nb_api, contexts):
    """Apply checked contexts and report results; caller owns confirmation."""
    print()
    print('=== VM NETWORK APPLY ===')

    created_interfaces = 0
    updated_interfaces = 0
    created_macs = 0
    updated_macs = 0
    created_ips = 0
    updated_ips = 0
    updated_primary = 0
    skipped = 0

    for context in contexts:
        vm = context['source_vm']
        netbox_vm = context['netbox_vm']
        applied_ips = {}

        for nic_context in context['nics']:
            nic = nic_context['source']
            interface = nic_context[
                'existing'
            ]

            if interface is None:
                interface = (
                    nb_api.virtualization
                    .interfaces
                    .create(
                        virtual_machine=(
                            netbox_vm.id
                        ),
                        name=interface_display_name(vm, nic),
                        enabled=True,
                        custom_fields=(
                            nic_context[
                                'desired_custom_fields'
                            ]
                        ),
                    )
                )

                created_interfaces += 1

                print(
                    f'CREATE INTERFACE '
                    f'id={interface.id} '
                    f'vm={netbox_vm.name!r} '
                    f'name={interface_display_name(vm, nic)}'
                )

            elif nic_context[
                'interface_changes'
            ]:
                interface.update(
                    nic_context[
                        'interface_changes'
                    ]
                )

                updated_interfaces += 1

                print(
                    f'UPDATE INTERFACE '
                    f'id={interface.id} '
                    f'name={interface_display_name(vm, nic)}'
                )
            else:
                skipped += 1

            mac_value = nic_context[
                'mac_value'
            ]

            if mac_value:
                mac = nic_context[
                    'existing_mac'
                ]

                if mac is None:
                    mac = (
                        nb_api.dcim
                        .mac_addresses
                        .create(
                            mac_address=(
                                mac_value
                            ),
                            assigned_object_type=(
                                'virtualization.'
                                'vminterface'
                            ),
                            assigned_object_id=(
                                interface.id
                            ),
                        )
                    )

                    created_macs += 1

                    print(
                        f'CREATE MAC '
                        f'id={mac.id} '
                        f'{mac_value}'
                    )

                else:
                    (
                        assigned_type,
                        assigned_id,
                    ) = _assigned_object(mac)

                    if (
                        assigned_type is None
                        and assigned_id is None
                    ):
                        mac.update({
                            'assigned_object_type':
                                'virtualization.'
                                'vminterface',
                            'assigned_object_id':
                                interface.id,
                        })

                        updated_macs += 1

                        print(
                            f'ASSIGN MAC '
                            f'id={mac.id} '
                            f'{mac_value}'
                        )
                    else:
                        skipped += 1

                primary_mac_id = (
                    _current_primary_mac_id(
                        interface
                    )
                )

                if primary_mac_id != mac.id:
                    interface.update({
                        'primary_mac_address':
                            mac.id,
                    })

                    updated_interfaces += 1

                    print(
                        f'SET PRIMARY MAC '
                        f'interface={interface.id} '
                        f'mac={mac.id}'
                    )
                else:
                    skipped += 1

            for ip_context in (
                nic_context['ips']
            ):
                address = ip_context[
                    'address'
                ]

                ip = ip_context[
                    'existing'
                ]

                if ip is None:
                    ip = (
                        nb_api.ipam
                        .ip_addresses
                        .create(
                            address=address,
                            **({'vrf':ip_context['vrf_id']} if ip_context['vrf_id'] is not None else {}),
                            status='active',
                            assigned_object_type=(
                                'virtualization.'
                                'vminterface'
                            ),
                            assigned_object_id=(
                                interface.id
                            ),
                        )
                    )

                    created_ips += 1

                    print(
                        f'CREATE IP '
                        f'id={ip.id} '
                        f'address={address}'
                    )

                else:
                    (
                        assigned_type,
                        assigned_id,
                    ) = _assigned_object(ip)

                    if (
                        assigned_type is None
                        and assigned_id is None
                    ):
                        ip.update({
                            'assigned_object_type':
                                'virtualization.'
                                'vminterface',
                            'assigned_object_id':
                                interface.id,
                        })

                        updated_ips += 1

                        print(
                            f'ASSIGN IP '
                            f'id={ip.id} '
                            f'address={address}'
                        )
                    else:
                        skipped += 1

                applied_ips[
                    ip_context['key']
                ] = ip

        candidate = context[
            'primary_candidate'
        ]

        if (
            candidate is not None
            and candidate in applied_ips
            and context['primary_action'] != 'preserve_manual'
        ):
            ip = applied_ips[
                candidate
            ]

            current_primary = (
                _current_primary_ip_id(
                    netbox_vm
                )
            )

            if current_primary != ip.id:
                netbox_vm.update({
                    'primary_ip4': ip.id,
                })

                updated_primary += 1

                print(
                    f'SET PRIMARY IPv4 '
                    f'vm={netbox_vm.name!r} '
                    f'address={candidate}'
                )
            else:
                skipped += 1

    print()
    print('VM NETWORK APPLY SUMMARY')
    print(
        f'  interfaces_created='
        f'{created_interfaces}'
    )
    print(
        f'  interfaces_updated='
        f'{updated_interfaces}'
    )
    print(
        f'  macs_created={created_macs}'
    )
    print(
        f'  macs_updated={updated_macs}'
    )
    print(
        f'  ips_created={created_ips}'
    )
    print(
        f'  ips_updated={updated_ips}'
    )
    print(
        f'  primary_updated='
        f'{updated_primary}'
    )
    print(
        f'  skipped={skipped}'
    )
