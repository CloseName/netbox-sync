from .netbox_vm_metadata import (
    MANAGED_VM_CUSTOM_FIELDS,
    build_vm_custom_fields,
    find_vm_sync_identity_matches,
    vm_identity_source_id,
)


class VMApplyError(RuntimeError):
    pass


def _object_id(value):
    if value is None:
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, dict):
        return value.get('id')

    return getattr(value, 'id', None)


def _choice_value(value):
    if value is None:
        return None

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        return value.get('value')

    return getattr(value, 'value', value)


def _integer_value(value):
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return int(float(value))


def _required(
        endpoint,
        description,
        **filters,
):
    result = endpoint.get(**filters)

    if result is None:
        raise VMApplyError(
            f'NetBox prerequisite not found: '
            f'{description} filters={filters}'
        )

    return result


def _resolve_cluster(
        nb_api,
        site,
        cluster_type,
        cluster_name,
        cluster_id=None,
):
    matches = []

    for cluster in (
        nb_api.virtualization
        .clusters
        .filter(**({'id':cluster_id} if cluster_id else {'name':cluster_name}))
    ):
        data = cluster.serialize()

        if (
            _object_id(data.get('type'))
            == cluster_type.id
            and data.get('scope_type')
            == 'dcim.site'
            and data.get('scope_id')
            == site.id
        ):
            matches.append(cluster)

    if len(matches) != 1:
        raise VMApplyError(
            f'Expected exactly one target '
            f'cluster {cluster_name!r}; '
            f'found {len(matches)}'
        )

    return matches[0]


def _desired_status(vm):
    mapping = {
        'running': 'active',
        'stopped': 'offline',
        'paused': 'paused',
    }

    try:
        return mapping[vm.status]
    except KeyError as exc:
        raise VMApplyError(
            f'Unsupported Proxmox VM '
            f'status: {vm.status!r}'
        ) from exc


def _desired_memory(vm):
    return (
        vm.memory_bytes
        // 1024**2
    )


def _desired_disk(vm):
    return sum(
        disk.size_bytes
        for disk in vm.disks
    ) // 1024**2


def _desired_start_on_boot(vm):
    return (
        'on'
        if vm.autostart
        else 'off'
    )


def _identity(vm):
    return (
        f'{vm.source}:'
        f'{vm_identity_source_id(vm)}'
    )


def _tenant_id(vm):
    data = vm.serialize()
    return _object_id(
        data.get('tenant')
    )


def _name_matches(
        existing_vms,
        name,
        *,
        tenant_id=None,
        exclude_id=None,
):
    wanted = name.casefold()
    matches = []

    for candidate in existing_vms:
        if (
            exclude_id is not None
            and candidate.id == exclude_id
        ):
            continue

        if candidate.name.casefold() != wanted:
            continue

        if _tenant_id(candidate) != tenant_id:
            continue

        matches.append(candidate)

    return matches


def _identity_matches(
        all_vms,
        discovered_vm,
):
    return find_vm_sync_identity_matches(all_vms, discovered_vm)


def _managed_metadata(
        discovered_vm,
        existing_vm,
):
    existing = {}

    if existing_vm is not None:
        existing = dict(
            getattr(
                existing_vm,
                'custom_fields',
                None,
            )
            or {}
        )

    try:
        desired = build_vm_custom_fields(
            discovered_vm,
            existing,
        )
    except ValueError as exc:
        raise VMApplyError(
            f'Invalid managed VM metadata '
            f'for {_identity(discovered_vm)}: '
            f'{exc}'
        ) from exc

    changed = [
        field_name
        for field_name
        in MANAGED_VM_CUSTOM_FIELDS
        if (
            existing.get(field_name)
            != desired.get(field_name)
        )
    ]

    return desired, changed


def build_vm_create_fields(
        discovered_vm,
        cluster,
        desired_custom_fields=None,
):
    """Build the shared managed field set for a newly discovered VM."""

    if desired_custom_fields is None:
        desired_custom_fields, _ = _managed_metadata(
            discovered_vm, None,
        )
    return {
        'name': discovered_vm.original_name,
        'cluster': cluster.id,
        'status': _desired_status(discovered_vm),
        'vcpus': int(discovered_vm.vcpus),
        'memory': _desired_memory(discovered_vm),
        'disk': _desired_disk(discovered_vm),
        'start_on_boot': _desired_start_on_boot(discovered_vm),
        'custom_fields': desired_custom_fields,
    }


def _vm_changes(
        existing_vm,
        discovered_vm,
        cluster,
        desired_custom_fields,
        changed_custom_fields,
):
    data = existing_vm.serialize()
    changes = {}

    if data.get('name') != (
        discovered_vm.original_name
    ):
        changes['name'] = (
            discovered_vm.original_name
        )

    if (
        _object_id(data.get('cluster'))
        != cluster.id
    ):
        changes['cluster'] = cluster.id

    desired_status = _desired_status(
        discovered_vm
    )

    if (
        _choice_value(data.get('status'))
        != desired_status
    ):
        changes['status'] = desired_status

    desired_vcpus = int(
        discovered_vm.vcpus
    )

    if (
        _integer_value(data.get('vcpus'))
        != desired_vcpus
    ):
        changes['vcpus'] = desired_vcpus

    desired_memory = _desired_memory(
        discovered_vm
    )

    if (
        _integer_value(data.get('memory'))
        != desired_memory
    ):
        changes['memory'] = desired_memory

    desired_disk = _desired_disk(
        discovered_vm
    )

    if (
        _integer_value(data.get('disk'))
        != desired_disk
    ):
        changes['disk'] = desired_disk

    desired_start = (
        _desired_start_on_boot(
            discovered_vm
        )
    )

    if (
        _choice_value(
            data.get('start_on_boot')
        )
        != desired_start
    ):
        changes[
            'start_on_boot'
        ] = desired_start

    if changed_custom_fields:
        # Full merged map preserves all
        # unrelated/manual custom fields.
        changes[
            'custom_fields'
        ] = desired_custom_fields

    return changes


def _blocked_context(
        vm,
        reason,
        *,
        candidates=None,
):
    return {
        'vm': vm,
        'action': 'blocked',
        'reason': reason,
        'candidates': (
            candidates or []
        ),
    }


def _preflight_vm(
        all_vms,
        target_vms,
        discovered_vm,
        cluster,
):
    identity_matches = (
        _identity_matches(
            all_vms,
            discovered_vm,
        )
    )

    if len(identity_matches) > 1:
        return _blocked_context(
            discovered_vm,
            'duplicate_sync_identity',
            candidates=identity_matches,
        )

    existing = None
    match_reason = None

    if len(identity_matches) == 1:
        existing = identity_matches[0]
        data = existing.serialize()

        if (
            _object_id(
                data.get('cluster')
            )
            != cluster.id
        ):
            return _blocked_context(
                discovered_vm,
                'identity_outside_target_cluster',
                candidates=[existing],
            )

        match_reason = 'sync_identity'

        conflicts = _name_matches(
            target_vms,
            discovered_vm.original_name,
            tenant_id=_tenant_id(existing),
            exclude_id=existing.id,
        )

        if conflicts:
            return _blocked_context(
                discovered_vm,
                'desired_name_conflict',
                candidates=conflicts,
            )

    else:
        # New sync-created VMs have no tenant,
        # so bootstrap fallback considers only
        # tenant-less VMs in the target cluster.
        name_matches = _name_matches(
            target_vms,
            discovered_vm.original_name,
            tenant_id=None,
        )

        if len(name_matches) > 1:
            return _blocked_context(
                discovered_vm,
                'duplicate_name_candidate',
                candidates=name_matches,
            )

        if len(name_matches) == 1:
            return _blocked_context(
                discovered_vm,
                'adopt_candidate',
                candidates=name_matches,
            )

    (
        desired_custom_fields,
        changed_custom_fields,
    ) = _managed_metadata(
        discovered_vm,
        existing,
    )

    changes = {}

    if existing is not None:
        changes = _vm_changes(
            existing,
            discovered_vm,
            cluster,
            desired_custom_fields,
            changed_custom_fields,
        )

    return {
        'vm': discovered_vm,
        'action': (
            'match'
            if existing is not None
            else 'create'
        ),
        'reason': match_reason,
        'existing': existing,
        'desired_custom_fields':
            desired_custom_fields,
        'changed_custom_fields':
            changed_custom_fields,
        'changes': changes,
    }


def apply_virtual_machines(
        nb_api,
        hosts,
        config,
        *,
        confirmed=False,
):
    site = _required(
        nb_api.dcim.sites,
        'site',
        slug=config.site_slug,
    )

    cluster_type = _required(
        nb_api.virtualization.cluster_types,
        'cluster type',
        slug=config.cluster_type_slug,
    )

    cluster = _resolve_cluster(
        nb_api,
        site,
        cluster_type,
        config.cluster_name,
        getattr(config,'onboarding_mapping',{}).get('references',{}).get('cluster',{}).get('id'),
    )

    all_vms = list(
        nb_api.virtualization
        .virtual_machines
        .all()
    )

    target_vms = list(
        nb_api.virtualization
        .virtual_machines
        .filter(
            cluster_id=cluster.id
        )
    )

    discovered = []

    for host in hosts:
        discovered.extend(
            host.virtual_machines
        )

    # Fail before NetBox matching if the
    # source itself supplied duplicate IDs.
    identities = {}
    names = {}

    for vm in discovered:
        identity = _identity(vm)

        identities.setdefault(
            identity,
            [],
        ).append(vm)

        names.setdefault(
            vm.original_name.casefold(),
            [],
        ).append(vm)

    duplicate_identities = {
        key: value
        for key, value
        in identities.items()
        if len(value) > 1
    }

    if duplicate_identities:
        details = ', '.join(
            sorted(
                duplicate_identities
                .keys()
            )
        )

        raise VMApplyError(
            'Duplicate discovered VM '
            f'identities: {details}'
        )

    duplicate_names = {
        key: value
        for key, value
        in names.items()
        if len(value) > 1
    }

    if duplicate_names:
        details = ', '.join(
            sorted(
                duplicate_names.keys()
            )
        )

        raise VMApplyError(
            'Duplicate discovered VM '
            f'names in target cluster: '
            f'{details}'
        )

    contexts = []

    for vm in sorted(
        discovered,
        key=lambda item: (
            item.node_source_id,
            item.vmid,
        ),
    ):
        contexts.append(
            _preflight_vm(
                all_vms,
                target_vms,
                vm,
                cluster,
            )
        )

    print(
        '=== VM APPLY PRECHECK ==='
    )
    print(
        f'target_site={site.name} '
        f'cluster={cluster.name}'
    )
    print(
        f'discovered={len(discovered)} '
        f'existing_in_cluster='
        f'{len(target_vms)}'
    )
    print()

    blocked = 0

    for context in contexts:
        vm = context['vm']

        if context['action'] == 'blocked':
            blocked += 1

            print(
                f'BLOCKED VM '
                f'vmid={vm.vmid} '
                f'name={vm.original_name!r} '
                f'identity={_identity(vm)} '
                f'reason={context["reason"]}'
            )

            for candidate in (
                context['candidates']
            ):
                print(
                    f'  candidate '
                    f'id={candidate.id} '
                    f'name={candidate.name!r}'
                )

            continue

        if context['action'] == 'create':
            print(
                f'CREATE VM '
                f'vmid={vm.vmid} '
                f'name={vm.original_name!r} '
                f'identity={_identity(vm)}'
            )
        else:
            existing = context['existing']

            print(
                f'MATCH VM '
                f'id={existing.id} '
                f'vmid={vm.vmid} '
                f'name={vm.original_name!r} '
                f'identity={_identity(vm)} '
                f'reason=sync_identity'
            )

        print(
            f'  status='
            f'{_desired_status(vm)} '
            f'vcpus={vm.vcpus} '
            f'memory={_desired_memory(vm)} '
            f'disk={_desired_disk(vm)} '
            f'start_on_boot='
            f'{_desired_start_on_boot(vm)}'
        )

        print(
            f'  managed_custom_fields_changed='
            f'{len(context["changed_custom_fields"])}'
        )

        if context['action'] == 'match':
            fields = list(
                context['changes']
            )

            print(
                '  pending_fields='
                + (
                    ','.join(fields)
                    if fields
                    else '-'
                )
            )

    print()

    if blocked:
        print(
            f'PRECHECK BLOCKED '
            f'blocked={blocked}'
        )
        print(
            'No changes were written '
            'to NetBox.'
        )

        raise VMApplyError(
            'VM apply precheck failed'
        )

    print('PRECHECK PASSED')

    if not confirmed:
        print(
            'APPLY_CONFIRM=VM_WRITE '
            'is not set.'
        )
        print(
            'No changes were written '
            'to NetBox.'
        )
        return

    print()
    print('=== VM APPLY ===')

    created = 0
    updated = 0
    skipped = 0

    for context in contexts:
        vm = context['vm']
        existing = context.get(
            'existing'
        )

        if context['action'] == 'create':
            created_vm = (
                nb_api.virtualization
                .virtual_machines
                .create(**build_vm_create_fields(
                    vm,
                    cluster,
                    context['desired_custom_fields'],
                ))
            )

            created += 1

            print(
                f'CREATE VM '
                f'id={created_vm.id} '
                f'vmid={vm.vmid} '
                f'name={created_vm.name!r}'
            )

            continue

        changes = context['changes']

        if changes:
            existing.update(changes)
            updated += 1

            print(
                f'UPDATE VM '
                f'id={existing.id} '
                f'vmid={vm.vmid} '
                f'fields='
                f'{",".join(changes)}'
            )
        else:
            skipped += 1

            print(
                f'SKIP VM '
                f'id={existing.id} '
                f'vmid={vm.vmid} '
                f'name={existing.name!r}'
            )

    print()
    print(
        f'VM APPLY SUMMARY '
        f'created={created} '
        f'updated={updated} '
        f'skipped={skipped}'
    )
