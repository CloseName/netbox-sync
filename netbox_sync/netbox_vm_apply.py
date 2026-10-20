from .vm_apply_writes import write_virtual_machines
from .vm_apply_report import report_vm_precheck
from .vm_apply_preflight import prepare_vm_contexts
from .vm_apply_inventory import prepare_vm_apply_inventory
from .netbox_record_values import object_id as _object_id, choice_value as _choice_value
from .netbox_vm_name import netbox_vm_name
from .netbox_vm_metadata import (
    MANAGED_VM_CUSTOM_FIELDS,
    build_vm_custom_fields,
    find_vm_sync_identity_matches,
    vm_identity_source_id,
)


class VMApplyError(RuntimeError):
    pass


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


def _description_fields(discovered_vm):
    """Keep full provider notes and a short native NetBox description."""
    if discovered_vm.description is None:
        return {}
    comments = discovered_vm.description.strip()
    description = ' '.join(comments.split())
    if len(description) > 200:
        description = description[:199] + '…'
    return {'description': description, 'comments': comments}


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
        'name': netbox_vm_name(discovered_vm),
        'cluster': cluster.id,
        'status': _desired_status(discovered_vm),
        'vcpus': int(discovered_vm.vcpus),
        'memory': _desired_memory(discovered_vm),
        'disk': _desired_disk(discovered_vm),
        'start_on_boot': _desired_start_on_boot(discovered_vm),
        'custom_fields': desired_custom_fields,
        **_description_fields(discovered_vm),
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
    from .selectel_authority import owned_fields
    protected = owned_fields(data.get('custom_fields'))
    for field, value in _description_fields(discovered_vm).items():
        if (data.get(field) or '') != value:
            changes[field] = value

    if data.get('name') != (
        netbox_vm_name(discovered_vm)
    ):
        changes['name'] = (
            netbox_vm_name(discovered_vm)
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

    return {field: value for field, value in changes.items() if field not in protected}


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
            netbox_vm_name(discovered_vm),
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
            netbox_vm_name(discovered_vm),
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
    inventory = prepare_vm_apply_inventory(
        nb_api, config, _required=_required, _resolve_cluster=_resolve_cluster,
    )
    site = inventory.site
    cluster = inventory.cluster
    all_vms = inventory.all_vms
    target_vms = inventory.target_vms

    discovered, contexts = prepare_vm_contexts(
        nb_api, hosts, all_vms, target_vms, cluster, _identity=_identity, netbox_vm_name=netbox_vm_name, VMApplyError=VMApplyError, _preflight_vm=_preflight_vm, _object_id=_object_id,
    )

    report_vm_precheck(
        site, cluster, discovered, target_vms, contexts, _identity=_identity, _desired_status=_desired_status, _desired_memory=_desired_memory, _desired_disk=_desired_disk, _desired_start_on_boot=_desired_start_on_boot, VMApplyError=VMApplyError,
    )

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

    write_virtual_machines(
        nb_api, cluster, contexts, build_vm_create_fields=build_vm_create_fields,
    )

