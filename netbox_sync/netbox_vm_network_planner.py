from .vm_network_plan_primary import plan_primary_ipv4
from .vm_network_plan_ip import plan_interface_ips
from .vm_network_plan_mac import plan_interface_mac
from .vm_network_plan_inventory import prepare_vm_network_plan_inventory
from .netbox_record_values import object_id as _object_id
from .interface_display import interface_display_name, validate_interface_names
from .netbox_vm_network_apply import _interface_match
from .netbox_vm_interface_metadata import find_nic_sync_identity_matches
import ipaddress

from .netbox_vm_metadata import find_vm_sync_identity_matches


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

    inventory = prepare_vm_network_plan_inventory(
        nb_api, cluster, _canonical_mac=_canonical_mac, _canonical_address=_canonical_address,
    )
    target_vms = inventory.target_vms
    interfaces_by_vm = inventory.interfaces_by_vm
    macs_by_address = inventory.macs_by_address
    ips_by_address = inventory.ips_by_address
    ips_by_id = inventory.ips_by_id
    vlans_by_vid = inventory.vlans_by_vid
    prefixes_by_prefix = inventory.prefixes_by_prefix

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

            plan_interface_mac(
                nic, existing_interface, macs_by_address, counters,
                _canonical_mac=_canonical_mac, _assigned_object=_assigned_object,
            )

            plan_interface_ips(
                nic, existing_interface, ips_by_address, prefixes_by_prefix,
                site, counters, discovered_ipv4, _usable_address=_usable_address,
                _network_of=_network_of, _select_scoped=_select_scoped,
                _assigned_object=_assigned_object,
            )

        plan_primary_ipv4(
            netbox_vm, discovered_ipv4, ips_by_id, counters,
            _existing_primary_ipv4=_existing_primary_ipv4,
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
