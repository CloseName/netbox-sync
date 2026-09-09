from .host_mapping import cluster_filter
from .netbox_lxc_metadata import (
    MANAGED_LXC_CUSTOM_FIELDS,
    build_lxc_custom_fields,
    find_lxc_sync_identity_matches,
)


class LXCApplyError(RuntimeError):
    pass


def _status(value):
    mapping = {
        'running': 'active',
        'stopped': 'offline',
        'paused': 'paused',
    }

    if value not in mapping:
        raise LXCApplyError(
            f'Unsupported LXC status: {value!r}'
        )

    return mapping[value]


def _disk_mib(container):
    return sum(
        disk.size_bytes
        for disk in container.disks
    ) // 1024**2


def _desired_fields(
    container,
    cluster,
    existing=None,
):
    current_cf = {}

    if existing is not None:
        current_cf = dict(
            getattr(
                existing,
                'custom_fields',
                None,
            )
            or {}
        )

    custom_fields = (
        build_lxc_custom_fields(
            container,
            current_cf,
        )
    )

    return {
        'name':
            container.original_name,

        'cluster':
            cluster.id,

        'status':
            _status(
                container.status
            ),

        'vcpus':
            container.vcpus,

        'memory':
            container.memory_bytes
            // 1024**2,

        'disk':
            _disk_mib(
                container
            ),

        'start_on_boot':
            (
                'on'
                if container.autostart
                else 'off'
            ),

        'custom_fields':
            custom_fields,
    }


def _find_identity_matches(
    all_vms,
    container,
):
    return find_lxc_sync_identity_matches(all_vms, container)


def _changes(
    existing,
    desired,
):
    data = existing.serialize()

    result = {}

    scalar_fields = (
        'name',
        'status',
        'vcpus',
        'memory',
        'disk',
        'start_on_boot',
    )

    for field in scalar_fields:
        if data.get(field) != desired[field]:
            result[field] = desired[field]

    current_cluster = data.get(
        'cluster'
    )

    if isinstance(
        current_cluster,
        dict,
    ):
        current_cluster = (
            current_cluster.get('id')
        )

    if current_cluster != desired['cluster']:
        result[
            'cluster'
        ] = desired['cluster']

    current_cf = dict(
        getattr(
            existing,
            'custom_fields',
            None,
        )
        or {}
    )

    desired_cf = desired[
        'custom_fields'
    ]

    if any(
        current_cf.get(field)
        != desired_cf.get(field)
        for field
        in MANAGED_LXC_CUSTOM_FIELDS
    ):
        result[
            'custom_fields'
        ] = desired_cf

    return result


def apply_lxc_containers(
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
        raise LXCApplyError(
            'Target site not found'
        )

    clusters = list(
        nb_api.virtualization.clusters.filter(
            **cluster_filter(config)
        )
    )

    target_clusters = []

    for cluster in clusters:
        data = cluster.serialize()

        if (
            data.get('scope_type')
            == 'dcim.site'
            and data.get(
                'scope_id'
            ) == site.id
        ):
            target_clusters.append(
                cluster
            )

    if len(target_clusters) != 1:
        raise LXCApplyError(
            'Expected exactly one '
            'target cluster'
        )

    cluster = target_clusters[0]

    all_vms = list(
        nb_api.virtualization
        .virtual_machines
        .all()
    )

    target_vms = [
        vm
        for vm in all_vms
        if (
            getattr(
                getattr(
                    vm,
                    'cluster',
                    None,
                ),
                'id',
                None,
            )
            == cluster.id
        )
    ]

    contexts = []

    discovered_ids = set()

    for host in hosts:
        for container in host.containers:
            source_id = str(
                container.source_id
            )

            if source_id in discovered_ids:
                raise LXCApplyError(
                    f'Duplicate discovered '
                    f'LXC identity: '
                    f'{source_id}'
                )

            discovered_ids.add(
                source_id
            )

            identity_matches = (
                _find_identity_matches(
                    all_vms,
                    container,
                )
            )

            if len(identity_matches) > 1:
                raise LXCApplyError(
                    f'Duplicate NetBox '
                    f'LXC identity: '
                    f'{source_id}'
                )

            existing = None

            if len(identity_matches) == 1:
                existing = (
                    identity_matches[0]
                )

                existing_cluster = getattr(
                    getattr(
                        existing,
                        'cluster',
                        None,
                    ),
                    'id',
                    None,
                )

                if (
                    existing_cluster
                    != cluster.id
                ):
                    raise LXCApplyError(
                        f'LXC identity '
                        f'{source_id} exists '
                        f'outside target cluster'
                    )

            else:
                name_matches = [
                    vm
                    for vm in target_vms
                    if (
                        vm.name.casefold()
                        == container
                        .original_name
                        .casefold()
                    )
                ]

                if name_matches:
                    raise LXCApplyError(
                        f'LXC adoption candidate '
                        f'exists without '
                        f'sync identity: '
                        f'{container.original_name!r}'
                    )

            desired = _desired_fields(
                container,
                cluster,
                existing,
            )

            changes = {}

            if existing is not None:
                changes = _changes(
                    existing,
                    desired,
                )

            contexts.append({
                'container':
                    container,
                'existing':
                    existing,
                'desired':
                    desired,
                'changes':
                    changes,
            })

    create_count = 0
    update_count = 0
    skip_count = 0

    print(
        '=== LXC APPLY PRECHECK ==='
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

        existing = context[
            'existing'
        ]

        changes = context[
            'changes'
        ]

        if existing is None:
            action = 'CREATE'
            create_count += 1
        elif changes:
            action = 'UPDATE'
            update_count += 1
        else:
            action = 'SKIP'
            skip_count += 1

        print(
            f'{action} LXC '
            f'vmid={container.vmid} '
            f'name='
            f'{container.original_name!r}'
        )

        if changes:
            print(
                '  fields='
                + ','.join(
                    sorted(
                        changes.keys()
                    )
                )
            )

    print()

    print(
        'LXC PRECHECK SUMMARY'
    )

    print(
        f'  create={create_count}'
    )

    print(
        f'  update={update_count}'
    )

    print(
        f'  skip={skip_count}'
    )

    print()

    print(
        'PRECHECK PASSED'
    )

    if not confirmed:
        print(
            'APPLY_CONFIRM=LXC_WRITE '
            'is not set.'
        )

        print(
            'No changes were written '
            'to NetBox.'
        )

        return

    created = 0
    updated = 0
    skipped = 0

    print()
    print(
        '=== LXC APPLY ==='
    )

    for context in contexts:
        container = context[
            'container'
        ]

        existing = context[
            'existing'
        ]

        desired = context[
            'desired'
        ]

        changes = context[
            'changes'
        ]

        if existing is None:
            vm = (
                nb_api.virtualization
                .virtual_machines
                .create(
                    **desired
                )
            )

            created += 1

            print(
                f'CREATE LXC '
                f'id={vm.id} '
                f'vmid={container.vmid} '
                f'name={vm.name!r}'
            )

        elif changes:
            existing.update(
                changes
            )

            updated += 1

            print(
                f'UPDATE LXC '
                f'id={existing.id} '
                f'vmid={container.vmid} '
                f'name={existing.name!r}'
            )

        else:
            skipped += 1

    print()

    print(
        'LXC APPLY SUMMARY'
    )

    print(
        f'  created={created}'
    )

    print(
        f'  updated={updated}'
    )

    print(
        f'  skipped={skipped}'
    )
