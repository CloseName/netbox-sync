from .vm_network_inventory import prepare_vm_network_inventory
from .netbox_record_values import object_id as _object_id
from .interface_display import interface_display_name, validate_interface_names
from .host_mapping import cluster_filter
import ipaddress
from .network_scopes import scope_key,object_id as scope_object_id

from .netbox_vm_metadata import (
    find_vm_sync_identity_matches,
)

from .netbox_vm_interface_metadata import (
    MANAGED_VM_INTERFACE_CUSTOM_FIELDS,
    build_nic_custom_fields,
    find_nic_sync_identity_matches,
    nic_identity_source_id,
)


from .vm_network_preflight import (
    VMNetworkApplyError,
    ManagedMACConflict,
    _canonical_mac,
    _usable_address,
    _assigned_object,
    _find_vm,
    _interface_match,
    _desired_interface_changes,
    _current_primary_mac_id,
    _current_primary_ip_id,
    _primary_ip_belongs_to_vm,
    prepare_vm_network_contexts,
)


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

    inventory = prepare_vm_network_inventory(nb_api, cluster, _canonical_mac=_canonical_mac)
    contexts = prepare_vm_network_contexts(hosts, inventory)

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
                f'name={interface_display_name(vm, nic)} '
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
