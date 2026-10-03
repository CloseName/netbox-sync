from .interface_display import interface_display_name, validate_interface_names
from .netbox_vm_network_apply import _interface_match
from .netbox_vm_interface_metadata import find_nic_sync_identity_matches
import ipaddress

from .netbox_vm_metadata import find_vm_sync_identity_matches


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


def _canonical_address(value):
    return str(
        ipaddress.ip_interface(
            str(value)
        )
    )


def _usable_address(value):
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


def _network_of(address):
    return str(
        ipaddress.ip_interface(
            address
        ).network
    )


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


def _scope_rank(data, site_id):
    scope_type = data.get(
        'scope_type'
    )

    scope_id = data.get(
        'scope_id'
    )

    if (
        scope_type == 'dcim.site'
        and scope_id == site_id
    ):
        return 0

    if (
        scope_type is None
        and scope_id is None
    ):
        return 1

    return None


def _select_scoped(
        records,
        site_id,
):
    eligible = []

    for record in records:
        data = record.serialize()

        rank = _scope_rank(
            data,
            site_id,
        )

        if rank is not None:
            eligible.append(
                (
                    rank,
                    record,
                )
            )

    if not eligible:
        return None, 'not-found'

    best_rank = min(
        item[0]
        for item in eligible
    )

    best = [
        record
        for rank, record
        in eligible
        if rank == best_rank
    ]

    if len(best) > 1:
        return None, 'ambiguous'

    return best[0], 'match'


def _vm_identity_match(
        target_vms,
        discovered_vm,
):
    return find_vm_sync_identity_matches(target_vms, discovered_vm)


def _existing_primary_ipv4(
        vm,
        ips_by_id,
):
    data = vm.serialize()

    primary_id = _object_id(
        data.get('primary_ip4')
    )

    if primary_id is None:
        return None

    ip = ips_by_id.get(
        primary_id
    )

    if ip is None:
        return None

    address = ip.serialize().get(
        'address'
    )

    if not address:
        return None

    return _canonical_address(
        address
    )


def plan_vm_networks(
        nb_api,
        host,
        cluster,
        site,
):
    print()
    print(
        '  QEMU VM NETWORK'
    )

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

    all_vlans = list(
        nb_api.ipam
        .vlans
        .all()
    )

    all_prefixes = list(
        nb_api.ipam
        .prefixes
        .all()
    )

    interfaces_by_vm = {}

    for interface in all_interfaces:
        data = interface.serialize()

        vm_id = _object_id(
            data.get(
                'virtual_machine'
            )
        )

        if vm_id is None:
            continue

        interfaces_by_vm.setdefault(
            vm_id,
            [],
        ).append(interface)

    macs_by_address = {}

    for mac in all_macs:
        data = mac.serialize()

        value = _canonical_mac(
            data.get(
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
        data = ip.serialize()

        ips_by_id[ip.id] = ip

        address = data.get(
            'address'
        )

        if not address:
            continue

        try:
            canonical = (
                _canonical_address(
                    address
                )
            )
        except ValueError:
            continue

        ips_by_address.setdefault(
            canonical,
            [],
        ).append(ip)

    vlans_by_vid = {}

    for vlan in all_vlans:
        data = vlan.serialize()

        vid = data.get('vid')

        if vid is None:
            continue

        vlans_by_vid.setdefault(
            int(vid),
            [],
        ).append(vlan)

    prefixes_by_prefix = {}

    for prefix in all_prefixes:
        data = prefix.serialize()

        value = data.get(
            'prefix'
        )

        if not value:
            continue

        prefixes_by_prefix.setdefault(
            str(value),
            [],
        ).append(prefix)

    counters = {
        'vm_match': 0,
        'vm_blocked': 0,

        'interface_create': 0,
        'interface_match': 0,
        'interface_conflict': 0,

        'mac_create': 0,
        'mac_match': 0,
        'mac_conflict': 0,

        'ip_create': 0,
        'ip_match': 0,
        'ip_conflict': 0,

        'primary_set': 0,
        'warnings': 0,
    }

    for discovered_vm in sorted(
        host.virtual_machines,
        key=lambda item: item.vmid,
    ):
        vm_matches = (
            _vm_identity_match(
                target_vms,
                discovered_vm,
            )
        )

        if len(vm_matches) != 1:
            counters[
                'vm_blocked'
            ] += 1

            print(
                f'    BLOCKED NETWORK '
                f'vmid={discovered_vm.vmid} '
                f'name={discovered_vm.original_name!r} '
                f'vm_matches={len(vm_matches)}'
            )

            continue

        netbox_vm = vm_matches[0]

        counters[
            'vm_match'
        ] += 1

        print()
        print(
            f'    VM id={netbox_vm.id} '
            f'vmid={discovered_vm.vmid} '
            f'name={discovered_vm.original_name!r}'
        )

        existing_interfaces = (
            interfaces_by_vm.get(
                netbox_vm.id,
                [],
            )
        )

        try:
            validate_interface_names(discovered_vm, existing_interfaces,
                                     _interface_match, ValueError)
        except (ValueError, RuntimeError) as exc:
            counters['interface_conflict'] += 1
            print(f'      CONFLICT INTERFACE {exc}')
            continue

        discovered_names = {}

        for nic in discovered_vm.interfaces:
            discovered_names.setdefault(
                interface_display_name(discovered_vm, nic).casefold(),
                [],
            ).append(nic)

        duplicate_source_names = [
            name
            for name, items
            in discovered_names.items()
            if len(items) > 1
        ]

        if duplicate_source_names:
            counters[
                'interface_conflict'
            ] += len(
                duplicate_source_names
            )

            print(
                '      CONFLICT '
                'duplicate discovered '
                'interface names: '
                + ','.join(
                    sorted(
                        duplicate_source_names
                    )
                )
            )

            continue

        discovered_ipv4 = []

        for nic in sorted(
            discovered_vm.interfaces,
            key=lambda item: item.name,
        ):
            existing_matches = (
                find_nic_sync_identity_matches(
                    existing_interfaces, discovered_vm, nic,
                )
            )

            existing_interface = None

            if len(existing_matches) > 1:
                counters[
                    'interface_conflict'
                ] += 1

                print(
                    f'      CONFLICT INTERFACE '
                    f'name={interface_display_name(discovered_vm, nic)!r} '
                    f'matches={len(existing_matches)}'
                )

                continue

            if len(existing_matches) == 1:
                existing_interface = (
                    existing_matches[0]
                )

                counters[
                    'interface_match'
                ] += 1

                print(
                    f'      MATCH INTERFACE '
                    f'id={existing_interface.id} '
                    f'name={interface_display_name(discovered_vm, nic)}'
                )
            else:
                counters[
                    'interface_create'
                ] += 1

                print(
                    f'      CREATE INTERFACE '
                    f'name={interface_display_name(discovered_vm, nic)}'
                )

            print(
                f'        bridge='
                f'{nic.bridge or "-"}'
            )

            if nic.vlan_id is None:
                print(
                    '        vlan=-'
                )
            else:
                vlan, vlan_state = (
                    _select_scoped(
                        vlans_by_vid.get(
                            nic.vlan_id,
                            [],
                        ),
                        site.id,
                    )
                )

                if vlan_state == 'match':
                    print(
                        f'        MATCH VLAN '
                        f'id={vlan.id} '
                        f'vid={nic.vlan_id}'
                    )
                elif vlan_state == 'ambiguous':
                    counters[
                        'warnings'
                    ] += 1

                    print(
                        f'        WARN VLAN '
                        f'vid={nic.vlan_id} '
                        f'ambiguous '
                        f'action=not-set'
                    )
                else:
                    counters[
                        'warnings'
                    ] += 1

                    print(
                        f'        WARN VLAN '
                        f'vid={nic.vlan_id} '
                        f'not-found '
                        f'action=not-created'
                    )

            mac_value = _canonical_mac(
                nic.mac_address
            )

            if mac_value:
                mac_matches = (
                    macs_by_address.get(
                        mac_value,
                        [],
                    )
                )

                if len(mac_matches) > 1:
                    counters[
                        'mac_conflict'
                    ] += 1

                    print(
                        f'        CONFLICT MAC '
                        f'{mac_value} '
                        f'matches='
                        f'{len(mac_matches)}'
                    )

                elif len(mac_matches) == 1:
                    mac = mac_matches[0]

                    (
                        assigned_type,
                        assigned_id,
                    ) = _assigned_object(
                        mac
                    )

                    allowed = (
                        assigned_type is None
                        and assigned_id is None
                    )

                    if (
                        existing_interface
                        is not None
                        and assigned_type
                        == 'virtualization.vminterface'
                        and assigned_id
                        == existing_interface.id
                    ):
                        allowed = True

                    if allowed:
                        counters[
                            'mac_match'
                        ] += 1

                        print(
                            f'        MATCH MAC '
                            f'id={mac.id} '
                            f'{mac_value}'
                        )
                    else:
                        counters[
                            'mac_conflict'
                        ] += 1

                        print(
                            f'        CONFLICT MAC '
                            f'id={mac.id} '
                            f'{mac_value} '
                            f'assigned='
                            f'{assigned_type}:'
                            f'{assigned_id}'
                        )
                else:
                    counters[
                        'mac_create'
                    ] += 1

                    print(
                        f'        CREATE MAC '
                        f'{mac_value}'
                    )

            usable_addresses = []

            for raw_address in (
                nic.ip_addresses
            ):
                address = _usable_address(
                    raw_address
                )

                if address is None:
                    print(
                        f'        IGNORE IP '
                        f'{raw_address} '
                        f'reason=non-routable'
                    )
                    continue

                usable_addresses.append(
                    address
                )

                ip_interface = (
                    ipaddress.ip_interface(
                        address
                    )
                )

                if (
                    ip_interface.version == 4
                ):
                    discovered_ipv4.append(
                        address
                    )

                network = _network_of(
                    address
                )

                prefix, prefix_state = (
                    _select_scoped(
                        prefixes_by_prefix.get(
                            network,
                            [],
                        ),
                        site.id,
                    )
                )

                if prefix_state == 'match':
                    print(
                        f'        MATCH PREFIX '
                        f'id={prefix.id} '
                        f'prefix={network}'
                    )

                elif prefix_state == 'ambiguous':
                    counters[
                        'warnings'
                    ] += 1

                    print(
                        f'        WARN PREFIX '
                        f'prefix={network} '
                        f'ambiguous '
                        f'action=not-created'
                    )

                else:
                    counters[
                        'warnings'
                    ] += 1

                    print(
                        f'        WARN PREFIX '
                        f'prefix={network} '
                        f'not-found '
                        f'action=not-created'
                    )

                ip_matches = (
                    ips_by_address.get(
                        address,
                        [],
                    )
                )

                if len(ip_matches) > 1:
                    counters[
                        'ip_conflict'
                    ] += 1

                    print(
                        f'        CONFLICT IP '
                        f'{address} '
                        f'matches='
                        f'{len(ip_matches)}'
                    )

                    continue

                if len(ip_matches) == 1:
                    ip = ip_matches[0]

                    (
                        assigned_type,
                        assigned_id,
                    ) = _assigned_object(
                        ip
                    )

                    allowed = (
                        assigned_type is None
                        and assigned_id is None
                    )

                    if (
                        existing_interface
                        is not None
                        and assigned_type
                        == 'virtualization.vminterface'
                        and assigned_id
                        == existing_interface.id
                    ):
                        allowed = True

                    if allowed:
                        counters[
                            'ip_match'
                        ] += 1

                        print(
                            f'        MATCH IP '
                            f'id={ip.id} '
                            f'address={address}'
                        )
                    else:
                        counters[
                            'ip_conflict'
                        ] += 1

                        print(
                            f'        CONFLICT IP '
                            f'id={ip.id} '
                            f'address={address} '
                            f'assigned='
                            f'{assigned_type}:'
                            f'{assigned_id}'
                        )

                else:
                    counters[
                        'ip_create'
                    ] += 1

                    print(
                        f'        CREATE IP '
                        f'address={address}'
                    )

        unique_ipv4 = sorted(
            set(discovered_ipv4)
        )

        current_primary = (
            _existing_primary_ipv4(
                netbox_vm,
                ips_by_id,
            )
        )

        if len(unique_ipv4) == 1:
            candidate = unique_ipv4[0]

            if current_primary == candidate:
                print(
                    f'      KEEP PRIMARY IPv4 '
                    f'{candidate}'
                )
            else:
                counters[
                    'primary_set'
                ] += 1

                print(
                    f'      SET PRIMARY IPv4 '
                    f'{candidate}'
                )

        elif not unique_ipv4:
            print(
                '      PRIMARY IPv4 '
                'action=unchanged '
                'reason=no-discovered-address'
            )

        else:
            print(
                '      PRIMARY IPv4 '
                'action=unchanged '
                'reason=ambiguous '
                f'candidates='
                + ','.join(unique_ipv4)
            )

    print()
    print(
        '    VM NETWORK PLAN SUMMARY'
    )

    for key in (
        'vm_match',
        'vm_blocked',
        'interface_create',
        'interface_match',
        'interface_conflict',
        'mac_create',
        'mac_match',
        'mac_conflict',
        'ip_create',
        'ip_match',
        'ip_conflict',
        'primary_set',
        'warnings',
    ):
        print(
            f'      {key}='
            f'{counters[key]}'
        )
