from .host_mapping import cluster_filter
import ipaddress

from .netbox_vm_metadata import (
    find_vm_sync_identity_matches,
)

from .netbox_vm_interface_metadata import (
    MANAGED_VM_INTERFACE_CUSTOM_FIELDS,
    build_nic_custom_fields,
    find_nic_sync_identity_matches,
    nic_identity_source_id,
)


class VMNetworkApplyError(RuntimeError):
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


def _usable_address(value):
    try:
        interface = ipaddress.ip_interface(
            str(value)
        )
    except ValueError:
        return None

    ip = interface.ip

    if (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return None

    return str(interface)


def _assigned_object(record):
    data = record.serialize()

    return (
        data.get('assigned_object_type'),
        data.get('assigned_object_id'),
    )


def _find_vm(
        target_vms,
        discovered_vm,
):
    matches = find_vm_sync_identity_matches(target_vms, discovered_vm)

    if len(matches) != 1:
        raise VMNetworkApplyError(
            f'Expected exactly one NetBox VM '
            f'for {discovered_vm.source_id}; '
            f'found {len(matches)}'
        )

    return matches[0]


def _interface_match(
        existing_interfaces,
        vm,
        nic,
):
    identity_matches = find_nic_sync_identity_matches(
        existing_interfaces, vm, nic,
    )

    if len(identity_matches) > 1:
        raise VMNetworkApplyError(
            f'Duplicate NIC identity '
            f'{vm.source}:'
            f'{nic_identity_source_id(vm, nic)}'
        )

    if len(identity_matches) == 1:
        return identity_matches[0]

    name_matches = [
        interface
        for interface in existing_interfaces
        if (
            interface.name.casefold()
            == nic.name.casefold()
        )
    ]

    if name_matches:
        raise VMNetworkApplyError(
            f'NIC adoption candidate exists '
            f'without sync identity: '
            f'vm={vm.original_name!r} '
            f'nic={nic.name!r}'
        )

    return None


def _desired_interface_changes(
        existing,
        vm,
        nic,
):
    current_custom_fields = dict(
        getattr(
            existing,
            'custom_fields',
            None,
        )
        or {}
    )

    desired_custom_fields = (
        build_nic_custom_fields(
            vm,
            nic,
            current_custom_fields,
        )
    )

    changes = {}

    if existing.name != nic.name:
        changes['name'] = nic.name

    data = existing.serialize()

    if data.get('enabled') is not True:
        changes['enabled'] = True

    changed_cf = any(
        current_custom_fields.get(field)
        != desired_custom_fields.get(field)
        for field in
        MANAGED_VM_INTERFACE_CUSTOM_FIELDS
    )

    if changed_cf:
        changes[
            'custom_fields'
        ] = desired_custom_fields

    return (
        changes,
        desired_custom_fields,
    )


def _current_primary_mac_id(interface):
    if interface is None:
        return None

    return _object_id(
        interface.serialize().get(
            'primary_mac_address'
        )
    )


def _current_primary_ip_id(vm):
    return _object_id(
        vm.serialize().get(
            'primary_ip4'
        )
    )


def _primary_ip_belongs_to_vm(ip_record, interfaces_by_id, vm_id):
    if ip_record is None:
        return False
    assigned_type, assigned_id = _assigned_object(ip_record)
    if assigned_type != 'virtualization.vminterface':
        return False
    interface = interfaces_by_id.get(_object_id(assigned_id))
    if interface is None:
        return False
    return _object_id(
        interface.serialize().get('virtual_machine')
    ) == vm_id


def resolve_vm_network_target(config):
    """Resolve target fields from SourceConfig or the legacy flat target."""

    target = getattr(config, 'target', None) or config
    try:
        return target.site_slug, target.cluster_name
    except AttributeError as exc:
        raise VMNetworkApplyError(
            'VM network target configuration is incomplete'
        ) from exc


def apply_vm_networks(
        nb_api,
        hosts,
        config,
        *,
        confirmed=False,
):
    site_slug, cluster_name = resolve_vm_network_target(config)
    site = nb_api.dcim.sites.get(
        slug=site_slug
    )

    if site is None:
        raise VMNetworkApplyError(
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
        raise VMNetworkApplyError(
            'Expected exactly one '
            'target cluster'
        )

    cluster = cluster_matches[0]

    target_vms = list(
        nb_api.virtualization
        .virtual_machines
        .filter(
            cluster_id=cluster.id
        )
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
    interfaces_by_id = {}

    for interface in all_interfaces:
        interfaces_by_id[interface.id] = interface
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
    ips_by_id = {}

    for ip in all_ips:
        ips_by_id[ip.id] = ip
        address = ip.serialize().get(
            'address'
        )

        if not address:
            continue

        try:
            canonical = str(
                ipaddress.ip_interface(
                    address
                )
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
        for vm in host.virtual_machines:
            netbox_vm = _find_vm(
                target_vms,
                vm,
            )

            existing_interfaces = (
                interfaces_by_vm.get(
                    netbox_vm.id,
                    [],
                )
            )

            nic_names = {}

            for nic in vm.interfaces:
                nic_names.setdefault(
                    nic.name.casefold(),
                    [],
                ).append(nic)

            duplicates = [
                name
                for name, items
                in nic_names.items()
                if len(items) > 1
            ]

            if duplicates:
                raise VMNetworkApplyError(
                    f'Duplicate discovered NIC '
                    f'names on {vm.original_name}: '
                    + ','.join(duplicates)
                )

            vm_context = {
                'source_vm': vm,
                'netbox_vm': netbox_vm,
                'nics': [],
                'primary_candidate': None,
                'primary_action': None,
                'primary_current': None,
            }

            vm_ipv4 = []

            for nic in vm.interfaces:
                existing = _interface_match(
                    existing_interfaces,
                    vm,
                    nic,
                )

                if existing is None:
                    desired_cf = (
                        build_nic_custom_fields(
                            vm,
                            nic,
                            {},
                        )
                    )

                    interface_changes = {}
                else:
                    (
                        interface_changes,
                        desired_cf,
                    ) = (
                        _desired_interface_changes(
                            existing,
                            vm,
                            nic,
                        )
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
                            vm.original_name,
                            nic.name,
                        )
                    )

                    mac_matches = (
                        macs_by_address.get(
                            mac_value,
                            [],
                        )
                    )

                    if len(mac_matches) > 1:
                        raise VMNetworkApplyError(
                            f'Duplicate NetBox MAC '
                            f'{mac_value}'
                        )

                    if len(mac_matches) == 1:
                        existing_mac = (
                            mac_matches[0]
                        )

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
                            existing is not None
                            and assigned_type
                            == 'virtualization.vminterface'
                            and assigned_id
                            == existing.id
                        ):
                            allowed = True

                        if not allowed:
                            raise VMNetworkApplyError(
                                f'MAC {mac_value} '
                                f'already assigned to '
                                f'{assigned_type}:'
                                f'{assigned_id}'
                            )

                    current_primary_mac = (
                        _current_primary_mac_id(
                            existing
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
                        raise VMNetworkApplyError(
                            f'Existing primary MAC '
                            f'conflicts on '
                            f'{vm.original_name}:'
                            f'{nic.name}'
                        )

                ip_contexts = []

                for raw_address in (
                    nic.ip_addresses
                ):
                    address = _usable_address(
                        raw_address
                    )

                    if address is None:
                        continue

                    discovered_ips.setdefault(
                        address,
                        [],
                    ).append(
                        (
                            vm.original_name,
                            nic.name,
                        )
                    )

                    if (
                        ipaddress.ip_interface(
                            address
                        ).version == 4
                    ):
                        vm_ipv4.append(address)

                    matches = (
                        ips_by_address.get(
                            address,
                            [],
                        )
                    )

                    if len(matches) > 1:
                        raise VMNetworkApplyError(
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
                            existing is not None
                            and assigned_type
                            == 'virtualization.vminterface'
                            and assigned_id
                            == existing.id
                        ):
                            allowed = True

                        if not allowed:
                            raise VMNetworkApplyError(
                                f'IP {address} '
                                f'already assigned to '
                                f'{assigned_type}:'
                                f'{assigned_id}'
                            )

                    ip_contexts.append({
                        'address': address,
                        'existing':
                            existing_ip,
                    })

                vm_context[
                    'nics'
                ].append({
                    'source': nic,
                    'existing':
                        existing,
                    'interface_changes':
                        interface_changes,
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
                set(vm_ipv4)
            )

            if len(unique_ipv4) == 1:
                candidate = unique_ipv4[0]
                current_primary = _current_primary_ip_id(netbox_vm)
                candidate_records = ips_by_address.get(candidate, ())
                candidate_id = (
                    candidate_records[0].id
                    if len(candidate_records) == 1
                    else None
                )
                if current_primary is None:
                    primary_action = 'set'
                elif current_primary == candidate_id:
                    primary_action = 'match'
                else:
                    current_record = ips_by_id.get(current_primary)
                    current_address = (
                        current_record.serialize().get('address')
                        if current_record is not None
                        else None
                    )
                    if not _primary_ip_belongs_to_vm(
                            current_record,
                            interfaces_by_id,
                            netbox_vm.id,
                    ):
                        raise VMNetworkApplyError(
                            'Existing primary IPv4 conflicts on '
                            f'{vm.original_name}: current={current_address!r} '
                            f'discovered={candidate!r}'
                        )
                    primary_action = 'preserve_manual'
                    vm_context['primary_current'] = current_address
                vm_context[
                    'primary_candidate'
                ] = candidate
                vm_context['primary_action'] = primary_action

            contexts.append(vm_context)

    duplicate_macs = {
        value: locations
        for value, locations
        in discovered_macs.items()
        if len(locations) > 1
    }

    if duplicate_macs:
        raise VMNetworkApplyError(
            'Duplicate discovered MACs: '
            + ','.join(
                sorted(duplicate_macs)
            )
        )

    duplicate_ips = {
        value: locations
        for value, locations
        in discovered_ips.items()
        if len(locations) > 1
    }

    if duplicate_ips:
        raise VMNetworkApplyError(
            'Duplicate discovered IPs: '
            + ','.join(
                sorted(duplicate_ips)
            )
        )

    interface_create = 0
    interface_update = 0
    interface_skip = 0
    mac_create = 0
    mac_reuse = 0
    ip_create = 0
    ip_reuse = 0
    primary_set = 0
    primary_match = 0
    primary_preserve_manual = 0

    print('=== VM NETWORK APPLY PRECHECK ===')
    print(
        f'target_site={site.name} '
        f'cluster={cluster.name}'
    )
    print()

    for context in contexts:
        vm = context['source_vm']
        netbox_vm = context['netbox_vm']

        print(
            f'VM id={netbox_vm.id} '
            f'vmid={vm.vmid} '
            f'name={vm.original_name!r}'
        )

        for nic_context in context['nics']:
            nic = nic_context['source']
            existing = nic_context['existing']

            if existing is None:
                interface_create += 1
                action = 'CREATE'
            elif nic_context[
                'interface_changes'
            ]:
                interface_update += 1
                action = 'UPDATE'
            else:
                interface_skip += 1
                action = 'SKIP'

            print(
                f'  {action} INTERFACE '
                f'name={nic.name} '
                f'bridge={nic.bridge or "-"} '
                f'vlan='
                f'{nic.vlan_id if nic.vlan_id is not None else "-"}'
            )

            if nic_context['mac_value']:
                if (
                    nic_context[
                        'existing_mac'
                    ] is None
                ):
                    mac_create += 1
                    mac_action = 'CREATE'
                else:
                    mac_reuse += 1
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
                    ip_reuse += 1
                    ip_action = 'MATCH'

                print(
                    f'    {ip_action} IP '
                    f'{ip_context["address"]}'
                )

        candidate = context[
            'primary_candidate'
        ]

        if candidate is not None:
            primary_action = context['primary_action']
            if primary_action == 'set':
                primary_set += 1
                print(f'  PRIMARY IPv4 SET candidate={candidate}')
            elif primary_action == 'match':
                primary_match += 1
                print(f'  PRIMARY IPv4 MATCH candidate={candidate}')
            else:
                primary_preserve_manual += 1
                print(
                    '  PRIMARY IPv4 PRESERVE '
                    f'vm={vm.original_name!r} '
                    f'current={context["primary_current"]!r} '
                    f'discovered={candidate!r} '
                    'reason=same-vm-existing-primary'
                )

    print()
    print('PRECHECK SUMMARY')
    print(
        f'  interface_create={interface_create}'
    )
    print(
        f'  interface_update={interface_update}'
    )
    print(
        f'  interface_skip={interface_skip}'
    )
    print(
        f'  mac_create={mac_create}'
    )
    print(
        f'  mac_match={mac_reuse}'
    )
    print(
        f'  ip_create={ip_create}'
    )
    print(
        f'  ip_match={ip_reuse}'
    )
    print(
        f'  primary_set={primary_set}'
    )
    print(
        f'  primary_match={primary_match}'
    )
    print(
        '  primary_preserve_manual='
        f'{primary_preserve_manual}'
    )

    print()
    print('PRECHECK PASSED')

    if not confirmed:
        print(
            'APPLY_CONFIRM=VM_NETWORK_WRITE '
            'is not set.'
        )
        print(
            'No changes were written '
            'to NetBox.'
        )
        return

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
                    f'vm={netbox_vm.name!r} '
                    f'name={nic.name}'
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
                    address
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
