from .host_mapping import cluster_filter
import ipaddress

from .netbox_lxc_metadata import (
    find_lxc_sync_identity_matches,
)

from .netbox_vm_interface_metadata import (
    MANAGED_VM_INTERFACE_CUSTOM_FIELDS,
    build_nic_custom_fields,
    find_nic_sync_identity_matches,
)


class LXCNetworkApplyError(RuntimeError):
    pass


def _object_id(value):
    if value is None:
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, dict):
        return value.get('id')

    return getattr(value, 'id', None)


def _canonical_mac(value):
    if not value:
        return None

    return str(value).strip().upper()


def _canonical_ip(value):
    return str(
        ipaddress.ip_interface(
            str(value)
        )
    )


def _usable_ip(value):
    try:
        interface = ipaddress.ip_interface(
            str(value)
        )
    except ValueError:
        return None

    address = interface.ip

    if (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    ):
        return None

    return str(interface)


def _assigned_object(record):
    data = record.serialize()

    return (
        data.get(
            'assigned_object_type'
        ),
        data.get(
            'assigned_object_id'
        ),
    )


def _find_lxc_vm(
    all_vms,
    container,
):
    matches = find_lxc_sync_identity_matches(all_vms, container)

    if len(matches) != 1:
        raise LXCNetworkApplyError(
            f'Expected exactly one '
            f'NetBox LXC object for '
            f'{container.source_id}; '
            f'found {len(matches)}'
        )

    return matches[0]


def _find_interface(
    interfaces,
    container,
    nic,
):
    identity_matches = find_nic_sync_identity_matches(
        interfaces, container, nic,
    )

    if len(identity_matches) > 1:
        raise LXCNetworkApplyError(
            f'Duplicate interface identity '
            f'on {container.original_name}:'
            f'{nic.name}'
        )

    if len(identity_matches) == 1:
        return identity_matches[0]

    name_matches = [
        interface
        for interface in interfaces
        if (
            interface.name.casefold()
            == nic.name.casefold()
        )
    ]

    if name_matches:
        raise LXCNetworkApplyError(
            f'LXC NIC adoption candidate '
            f'exists without identity: '
            f'{container.original_name}:'
            f'{nic.name}'
        )

    return None


def _interface_changes(
    interface,
    container,
    nic,
):
    current_cf = dict(
        getattr(
            interface,
            'custom_fields',
            None,
        )
        or {}
    )

    desired_cf = (
        build_nic_custom_fields(
            container,
            nic,
            current_cf,
        )
    )

    changes = {}

    data = interface.serialize()

    if interface.name != nic.name:
        changes[
            'name'
        ] = nic.name

    if data.get(
        'enabled'
    ) is not True:
        changes[
            'enabled'
        ] = True

    if any(
        current_cf.get(field)
        != desired_cf.get(field)
        for field
        in MANAGED_VM_INTERFACE_CUSTOM_FIELDS
    ):
        changes[
            'custom_fields'
        ] = desired_cf

    return (
        changes,
        desired_cf,
    )


def _primary_mac_id(interface):
    if interface is None:
        return None

    return _object_id(
        interface.serialize().get(
            'primary_mac_address'
        )
    )


def _primary_ip4_id(vm):
    return _object_id(
        vm.serialize().get(
            'primary_ip4'
        )
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

    all_vms = list(
        nb_api.virtualization
        .virtual_machines
        .all()
    )

    all_interfaces = list(
        nb_api.virtualization
        .interfaces
        .all()
    )

    all_macs = list(
        nb_api.dcim
        .mac_addresses
        .all()
    )

    all_ips = list(
        nb_api.ipam
        .ip_addresses
        .all()
    )

    interfaces_by_vm = {}

    for interface in all_interfaces:
        vm_id = _object_id(
            interface.serialize().get(
                'virtual_machine'
            )
        )

        if vm_id is not None:
            interfaces_by_vm.setdefault(
                vm_id,
                [],
            ).append(interface)

    macs_by_address = {}

    for mac in all_macs:
        value = _canonical_mac(
            mac.serialize().get(
                'mac_address'
            )
        )

        if value:
            macs_by_address.setdefault(
                value,
                [],
            ).append(mac)

    ips_by_address = {}

    for ip in all_ips:
        value = ip.serialize().get(
            'address'
        )

        if not value:
            continue

        try:
            canonical = (
                _canonical_ip(value)
            )
        except ValueError:
            continue

        ips_by_address.setdefault(
            canonical,
            [],
        ).append(ip)

    contexts = []

    discovered_macs = {}
    discovered_ips = {}

    for host in hosts:
        for container in host.containers:
            netbox_vm = _find_lxc_vm(
                all_vms,
                container,
            )

            vm_cluster_id = _object_id(
                netbox_vm.serialize().get(
                    'cluster'
                )
            )

            if vm_cluster_id != cluster.id:
                raise LXCNetworkApplyError(
                    f'LXC '
                    f'{container.source_id} '
                    f'is outside target cluster'
                )

            existing_interfaces = (
                interfaces_by_vm.get(
                    netbox_vm.id,
                    [],
                )
            )

            discovered_names = {}

            for nic in container.interfaces:
                discovered_names.setdefault(
                    nic.name.casefold(),
                    [],
                ).append(nic)

            duplicates = [
                name
                for name, items
                in discovered_names.items()
                if len(items) > 1
            ]

            if duplicates:
                raise LXCNetworkApplyError(
                    f'Duplicate discovered '
                    f'LXC NIC names: '
                    + ','.join(
                        sorted(duplicates)
                    )
                )

            context = {
                'container':
                    container,
                'netbox_vm':
                    netbox_vm,
                'nics': [],
                'primary_candidate':
                    None,
            }

            ipv4_candidates = []

            for nic in container.interfaces:
                interface = _find_interface(
                    existing_interfaces,
                    container,
                    nic,
                )

                if interface is None:
                    changes = {}

                    desired_cf = (
                        build_nic_custom_fields(
                            container,
                            nic,
                            {},
                        )
                    )
                else:
                    (
                        changes,
                        desired_cf,
                    ) = _interface_changes(
                        interface,
                        container,
                        nic,
                    )

                mac_value = _canonical_mac(
                    nic.mac_address
                )

                existing_mac = None

                if mac_value:
                    discovered_macs.setdefault(
                        mac_value,
                        [],
                    ).append(
                        (
                            container.original_name,
                            nic.name,
                        )
                    )

                    matches = (
                        macs_by_address.get(
                            mac_value,
                            [],
                        )
                    )

                    if len(matches) > 1:
                        raise LXCNetworkApplyError(
                            f'Duplicate NetBox MAC '
                            f'{mac_value}'
                        )

                    if len(matches) == 1:
                        existing_mac = matches[0]

                        (
                            assigned_type,
                            assigned_id,
                        ) = _assigned_object(
                            existing_mac
                        )

                        allowed = (
                            assigned_type is None
                            and assigned_id is None
                        )

                        if (
                            interface is not None
                            and assigned_type
                            == 'virtualization.vminterface'
                            and assigned_id
                            == interface.id
                        ):
                            allowed = True

                        if not allowed:
                            raise LXCNetworkApplyError(
                                f'MAC {mac_value} '
                                f'already assigned to '
                                f'{assigned_type}:'
                                f'{assigned_id}'
                            )

                    current_primary_mac = (
                        _primary_mac_id(
                            interface
                        )
                    )

                    if (
                        current_primary_mac
                        is not None
                        and (
                            existing_mac is None
                            or current_primary_mac
                            != existing_mac.id
                        )
                    ):
                        raise LXCNetworkApplyError(
                            f'Primary MAC conflict '
                            f'on '
                            f'{container.original_name}:'
                            f'{nic.name}'
                        )

                ip_contexts = []

                for raw_ip in nic.ip_addresses:
                    address = _usable_ip(
                        raw_ip
                    )

                    if address is None:
                        continue

                    discovered_ips.setdefault(
                        address,
                        [],
                    ).append(
                        (
                            container.original_name,
                            nic.name,
                        )
                    )

                    if (
                        ipaddress.ip_interface(
                            address
                        ).version == 4
                    ):
                        ipv4_candidates.append(
                            address
                        )

                    matches = (
                        ips_by_address.get(
                            address,
                            [],
                        )
                    )

                    if len(matches) > 1:
                        raise LXCNetworkApplyError(
                            f'Duplicate NetBox IP '
                            f'{address}'
                        )

                    existing_ip = (
                        matches[0]
                        if matches
                        else None
                    )

                    if existing_ip is not None:
                        (
                            assigned_type,
                            assigned_id,
                        ) = _assigned_object(
                            existing_ip
                        )

                        allowed = (
                            assigned_type is None
                            and assigned_id is None
                        )

                        if (
                            interface is not None
                            and assigned_type
                            == 'virtualization.vminterface'
                            and assigned_id
                            == interface.id
                        ):
                            allowed = True

                        if not allowed:
                            raise LXCNetworkApplyError(
                                f'IP {address} '
                                f'already assigned to '
                                f'{assigned_type}:'
                                f'{assigned_id}'
                            )

                    ip_contexts.append({
                        'address':
                            address,
                        'existing':
                            existing_ip,
                    })

                context[
                    'nics'
                ].append({
                    'source':
                        nic,
                    'existing':
                        interface,
                    'changes':
                        changes,
                    'desired_custom_fields':
                        desired_cf,
                    'mac_value':
                        mac_value,
                    'existing_mac':
                        existing_mac,
                    'ips':
                        ip_contexts,
                })

            unique_ipv4 = sorted(
                set(
                    ipv4_candidates
                )
            )

            if len(unique_ipv4) == 1:
                context[
                    'primary_candidate'
                ] = unique_ipv4[0]

            contexts.append(context)

    duplicate_macs = [
        value
        for value, locations
        in discovered_macs.items()
        if len(locations) > 1
    ]

    if duplicate_macs:
        raise LXCNetworkApplyError(
            'Duplicate discovered MACs: '
            + ','.join(
                sorted(duplicate_macs)
            )
        )

    duplicate_ips = [
        value
        for value, locations
        in discovered_ips.items()
        if len(locations) > 1
    ]

    if duplicate_ips:
        raise LXCNetworkApplyError(
            'Duplicate discovered IPs: '
            + ','.join(
                sorted(duplicate_ips)
            )
        )

    interface_create = 0
    interface_update = 0
    interface_skip = 0

    mac_create = 0
    mac_match = 0

    ip_create = 0
    ip_match = 0

    primary_candidates = 0

    print(
        '=== LXC NETWORK APPLY PRECHECK ==='
    )

    print(
        f'target_site={site.name} '
        f'cluster={cluster.name}'
    )

    print()

    for context in contexts:
        container = context[
            'container'
        ]

        netbox_vm = context[
            'netbox_vm'
        ]

        print(
            f'LXC id={netbox_vm.id} '
            f'vmid={container.vmid} '
            f'name={container.original_name!r}'
        )

        for nic_context in context[
            'nics'
        ]:
            nic = nic_context[
                'source'
            ]

            existing = nic_context[
                'existing'
            ]

            if existing is None:
                action = 'CREATE'
                interface_create += 1

            elif nic_context['changes']:
                action = 'UPDATE'
                interface_update += 1

            else:
                action = 'SKIP'
                interface_skip += 1

            print(
                f'  {action} INTERFACE '
                f'name={nic.name} '
                f'bridge={nic.bridge or "-"} '
                f'vlan='
                f'{nic.vlan_id if nic.vlan_id is not None else "-"}'
            )

            if nic_context[
                'mac_value'
            ]:
                if (
                    nic_context[
                        'existing_mac'
                    ] is None
                ):
                    mac_create += 1
                    mac_action = 'CREATE'
                else:
                    mac_match += 1
                    mac_action = 'MATCH'

                print(
                    f'    {mac_action} MAC '
                    f'{nic_context["mac_value"]}'
                )

            for ip_context in (
                nic_context['ips']
            ):
                if (
                    ip_context[
                        'existing'
                    ] is None
                ):
                    ip_create += 1
                    ip_action = 'CREATE'
                else:
                    ip_match += 1
                    ip_action = 'MATCH'

                print(
                    f'    {ip_action} IP '
                    f'{ip_context["address"]}'
                )

        candidate = context[
            'primary_candidate'
        ]

        if candidate is not None:
            primary_candidates += 1

            print(
                f'  PRIMARY IPv4 '
                f'candidate={candidate}'
            )

    print()
    print(
        'LXC NETWORK PRECHECK SUMMARY'
    )

    print(
        f'  interface_create='
        f'{interface_create}'
    )

    print(
        f'  interface_update='
        f'{interface_update}'
    )

    print(
        f'  interface_skip='
        f'{interface_skip}'
    )

    print(
        f'  mac_create={mac_create}'
    )

    print(
        f'  mac_match={mac_match}'
    )

    print(
        f'  ip_create={ip_create}'
    )

    print(
        f'  ip_match={ip_match}'
    )

    print(
        f'  primary_candidates='
        f'{primary_candidates}'
    )

    print()
    print('PRECHECK PASSED')

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
                        name=nic.name,
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
                    f'name={nic.name}'
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
                    f'name={nic.name}'
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
                    address
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
