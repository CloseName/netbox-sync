from .lxc_network_report import print_lxc_network_precheck
from .lxc_network_inventory import prepare_lxc_network_inventory
from .netbox_record_values import object_id as _object_id
from .interface_display import interface_display_name, validate_interface_names
from .host_mapping import cluster_filter
import ipaddress
from .network_scopes import scope_key,object_id as scope_object_id

from .netbox_lxc_metadata import (
    find_lxc_sync_identity_matches,
)

from .netbox_vm_interface_metadata import (
    MANAGED_VM_INTERFACE_CUSTOM_FIELDS,
    build_nic_custom_fields,
    find_nic_sync_identity_matches,
)


from .lxc_network_preflight import (
    LXCNetworkApplyError,
    _canonical_mac,
    _canonical_ip,
    _usable_ip,
    _assigned_object,
    _find_lxc_vm,
    _find_interface,
    _interface_changes,
    _primary_mac_id,
    _primary_ip4_id,
    prepare_lxc_network_contexts,
)


def apply_lxc_networks(
    nb_api,
    hosts,
    config,
    *,
    confirmed=False,
):
    site = nb_api.dcim.sites.get(
        slug=config.site_slug
    )

    if site is None:
        raise LXCNetworkApplyError(
            'Target site not found'
        )

    cluster_matches = list(
        nb_api.virtualization
        .clusters
        .filter(
            **cluster_filter(config)
        )
    )

    cluster_matches = [
        cluster
        for cluster in cluster_matches
        if (
            cluster.serialize().get(
                'scope_type'
            ) == 'dcim.site'
            and cluster.serialize().get(
                'scope_id'
            ) == site.id
        )
    ]

    if len(cluster_matches) != 1:
        raise LXCNetworkApplyError(
            'Expected exactly one '
            'target cluster'
        )

    cluster = cluster_matches[0]

    inventory = prepare_lxc_network_inventory(
        nb_api, _canonical_mac=_canonical_mac, _canonical_ip=_canonical_ip,
    )
    contexts = prepare_lxc_network_contexts(hosts, inventory, cluster)

    print_lxc_network_precheck(contexts, site, cluster)

    if not confirmed:
        print(
            'APPLY_CONFIRM='
            'LXC_NETWORK_WRITE '
            'is not set.'
        )

        print(
            'No changes were written '
            'to NetBox.'
        )

        return

    created_interfaces = 0
    updated_interfaces = 0

    created_macs = 0
    updated_macs = 0

    created_ips = 0
    updated_ips = 0

    primary_updated = 0
    skipped = 0

    print()
    print(
        '=== LXC NETWORK APPLY ==='
    )

    for context in contexts:
        container = context['container']
        netbox_vm = context[
            'netbox_vm'
        ]

        applied_ips = {}

        for nic_context in context[
            'nics'
        ]:
            nic = nic_context[
                'source'
            ]

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
                        name=interface_display_name(container, nic),
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
                    f'lxc={netbox_vm.name!r} '
                    f'name={interface_display_name(container, nic)}'
                )

            elif nic_context[
                'changes'
            ]:
                interface.update(
                    nic_context[
                        'changes'
                    ]
                )

                updated_interfaces += 1

                print(
                    f'UPDATE INTERFACE '
                    f'id={interface.id} '
                    f'name={interface_display_name(container, nic)}'
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
                    ) = _assigned_object(
                        mac
                    )

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

                    else:
                        skipped += 1

                if (
                    _primary_mac_id(
                        interface
                    )
                    != mac.id
                ):
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
                    ) = _assigned_object(
                        ip
                    )

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
        ):
            ip = applied_ips[
                candidate
            ]

            if (
                _primary_ip4_id(
                    netbox_vm
                )
                != ip.id
            ):
                netbox_vm.update({
                    'primary_ip4':
                        ip.id,
                })

                primary_updated += 1

                print(
                    f'SET PRIMARY IPv4 '
                    f'lxc={netbox_vm.name!r} '
                    f'address={candidate}'
                )

            else:
                skipped += 1

    print()
    print(
        'LXC NETWORK APPLY SUMMARY'
    )

    print(
        f'  interfaces_created='
        f'{created_interfaces}'
    )

    print(
        f'  interfaces_updated='
        f'{updated_interfaces}'
    )

    print(
        f'  macs_created='
        f'{created_macs}'
    )

    print(
        f'  macs_updated='
        f'{updated_macs}'
    )

    print(
        f'  ips_created='
        f'{created_ips}'
    )

    print(
        f'  ips_updated='
        f'{updated_ips}'
    )

    print(
        f'  primary_updated='
        f'{primary_updated}'
    )

    print(
        f'  skipped={skipped}'
    )
