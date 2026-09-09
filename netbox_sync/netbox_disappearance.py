from .host_mapping import cluster_filter
from .netbox_vm_metadata import (
    vm_identity_source_id,
)

from .netbox_lxc_metadata import (
    lxc_identity_source_id,
)

from .netbox_vm_interface_metadata import (
    nic_identity_source_id,
)
from .source_identity import (
    SourceIdentity,
    lxc_nic_source_identity,
    lxc_source_identity,
    virtual_machine_nic_source_identity,
    virtual_machine_source_identity,
)


def _local_source_id(obj):
    value = str(
        obj.source_id
    )

    prefix = (
        f'{obj.source}:'
    )

    if value.startswith(prefix):
        return value[
            len(prefix):
        ]

    return value


def _identities(custom_fields):
    custom_fields = dict(
        custom_fields or {}
    )

    values = custom_fields.get(
        'sync_identities'
    )

    if not isinstance(
        values,
        list,
    ):
        return []

    result = []

    for item in values:
        if not isinstance(
            item,
            dict,
        ):
            continue

        source = item.get(
            'source'
        )

        source_id = item.get(
            'source_id',
            item.get('id'),
        )

        if (
            source
            and source_id
        ):
            result.append(
                (
                    str(source),
                    str(source_id),
                )
            )

    return result


def _v2_identities(custom_fields):
    values = dict(custom_fields or {}).get('sync_identities')
    if not isinstance(values, list):
        return []

    result = []
    for value in values:
        parsed = SourceIdentity.from_record(value)
        if parsed is not None:
            result.append(parsed)
    return result


def _identity_label(identity):
    if isinstance(identity, SourceIdentity):
        return (
            f'{identity.type}/{identity.instance}/'
            f'{identity.kind}/{identity.external_id}'
        )
    return f'{identity[0]}:{identity[1]}'


def _object_id(value):
    if value is None:
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, dict):
        return value.get('id')

    return getattr(
        value,
        'id',
        None,
    )


def report_missing_managed_objects(
    nb_api,
    hosts,
    config,
):
    site = nb_api.dcim.sites.get(
        slug=config.site_slug
    )

    if site is None:
        raise RuntimeError(
            'Target site not found'
        )

    clusters = list(
        nb_api.virtualization
        .clusters
        .filter(
            **cluster_filter(config)
        )
    )

    clusters = [
        cluster
        for cluster in clusters
        if (
            cluster.serialize().get(
                'scope_type'
            ) == 'dcim.site'
            and cluster.serialize().get(
                'scope_id'
            ) == site.id
        )
    ]

    if len(clusters) != 1:
        raise RuntimeError(
            'Expected exactly one '
            'target cluster'
        )

    cluster = clusters[0]

    source_scopes = set()
    source_instances = set()
    discovered_guests = set()
    discovered_interfaces = set()

    for host in hosts:
        source = str(
            host.source
        )
        source_instances.add((source, str(host.source_instance)))

        host_source_id = (
            _local_source_id(
                host
            )
        )

        if host.legacy_identity_owner:
            source_scopes.add(
                (
                    source,
                    host_source_id + ':',
                )
            )

        for vm in host.virtual_machines:
            guest_identity = (
                str(vm.source),
                vm_identity_source_id(
                    vm
                ),
            )

            discovered_guests.add(
                guest_identity
            )
            discovered_guests.add(virtual_machine_source_identity(vm))

            for nic in vm.interfaces:
                discovered_interfaces.add(
                    (
                        str(vm.source),
                        nic_identity_source_id(
                            vm,
                            nic,
                        ),
                    )
                )
                discovered_interfaces.add(
                    virtual_machine_nic_source_identity(vm, nic)
                )

        for container in host.containers:
            guest_identity = (
                str(container.source),
                lxc_identity_source_id(
                    container
                ),
            )

            discovered_guests.add(
                guest_identity
            )
            discovered_guests.add(lxc_source_identity(container))

            for nic in container.interfaces:
                discovered_interfaces.add(
                    (
                        str(
                            container.source
                        ),
                        nic_identity_source_id(
                            container,
                            nic,
                        ),
                    )
                )
                discovered_interfaces.add(
                    lxc_nic_source_identity(container, nic)
                )

    def managed_identity(
        custom_fields,
    ):
        v2_matches = [
            identity
            for identity in _v2_identities(custom_fields)
            if (identity.type, identity.instance) in source_instances
        ]

        if len(v2_matches) > 1:
            raise RuntimeError(
                'Object has multiple managed Proxmox v2 identities: '
                + repr(v2_matches)
            )

        if v2_matches:
            return v2_matches[0]

        matches = []

        for identity in _identities(
            custom_fields
        ):
            source, source_id = identity

            for (
                scoped_source,
                prefix,
            ) in source_scopes:
                if (
                    source
                    == scoped_source
                    and source_id.startswith(
                        prefix
                    )
                ):
                    matches.append(
                        identity
                    )

        if len(matches) > 1:
            raise RuntimeError(
                'Object has multiple managed '
                'Proxmox identities: '
                + repr(matches)
            )

        if not matches:
            return None

        return matches[0]

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
            ).append(
                interface
            )

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
