"""Explicit creation of ESXi VMs proven NEW by migration preflight."""

from .netbox_vm_name import netbox_vm_name

from .esxi_migration import (
    EsxiMigrationPlan,
    ObjectMigrationClassification,
    build_esxi_migration_plan,
)
from .netbox_vm_apply import build_vm_create_fields
from .source_identity import virtual_machine_source_identity


class EsxiNewVmBootstrapError(RuntimeError):
    """A controlled bootstrap failed before or during VM creation."""

    def __init__(self, message, *, created_vm_ids=()):
        super().__init__(message)
        self.created_vm_ids = tuple(created_vm_ids)


def _object_id(value):
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, dict):
        return value.get('id')
    return getattr(value, 'id', None)


def _serialized(record):
    serialize = getattr(record, 'serialize', None)
    return serialize() if callable(serialize) else vars(record)


def _discovered_vms(hosts, config):
    discovered = []
    for host in hosts:
        if (
                str(host.source) != 'esxi'
                or host.source_instance != config.source_instance
        ):
            raise EsxiNewVmBootstrapError(
                'Discovered host is outside ESXi source scope'
            )
        for vm in host.virtual_machines:
            if (
                    str(vm.source) != 'esxi'
                    or vm.source_instance != config.source_instance
            ):
                raise EsxiNewVmBootstrapError(
                    'Discovered VM is outside ESXi source scope'
                )
            discovered.append(vm)
    return tuple(discovered)


def _unique_discovered(discovered):
    by_identity = {}
    for vm in discovered:
        identity = virtual_machine_source_identity(vm)
        by_identity.setdefault(identity, []).append(vm)
    duplicates = [
        identity for identity, matches in by_identity.items()
        if len(matches) > 1
    ]
    if duplicates:
        details = ','.join(sorted(item.external_id for item in duplicates))
        raise EsxiNewVmBootstrapError(
            f'Duplicate discovered ESXi VM identities: {details}'
        )
    return {identity.external_id: matches[0]
            for identity, matches in by_identity.items()}


def _selected_new(plan):
    selected = tuple(
        item for item in plan.virtual_machines
        if item.classification == ObjectMigrationClassification.NEW
    )
    external_ids = [item.external_id for item in selected]
    if len(external_ids) != len(set(external_ids)):
        raise EsxiNewVmBootstrapError(
            'Migration plan contains duplicate NEW VM identities'
        )
    names = [item.discovered_name.casefold() for item in selected]
    if len(names) != len(set(names)):
        raise EsxiNewVmBootstrapError(
            'Migration plan contains duplicate NEW VM names'
        )
    if any(item.candidates or item.interfaces for item in selected):
        raise EsxiNewVmBootstrapError('Invalid NEW VM migration plan item')
    return selected


def _fresh_plan(nb_api, hosts, config):
    try:
        return build_esxi_migration_plan(nb_api, hosts, config)
    except Exception as exc:
        raise EsxiNewVmBootstrapError(
            f'ESXi VM bootstrap preflight failed: {exc}'
        ) from exc


def _validate_target(nb_api, plan, fresh):
    if (
            fresh.source_instance != plan.source_instance
            or fresh.site_id != plan.site_id
            or fresh.cluster_id != plan.cluster_id
    ):
        raise EsxiNewVmBootstrapError(
            'ESXi migration target changed after preflight'
        )
    site = nb_api.dcim.sites.get(id=fresh.site_id)
    cluster = nb_api.virtualization.clusters.get(id=fresh.cluster_id)
    if site is None or cluster is None:
        raise EsxiNewVmBootstrapError('ESXi bootstrap target no longer exists')
    data = _serialized(cluster)
    if (
            data.get('scope_type') != 'dcim.site'
            or _object_id(data.get('scope_id')) != site.id
    ):
        raise EsxiNewVmBootstrapError(
            'ESXi bootstrap cluster moved outside target site'
        )
    return cluster


def _validate_selected(selected, fresh, discovered_by_id):
    fresh_by_id = {item.external_id: item for item in fresh.virtual_machines}
    contexts = []
    for planned in selected:
        current = fresh_by_id.get(planned.external_id)
        discovered = discovered_by_id.get(planned.external_id)
        if (
                current is None
                or discovered is None
                or current.classification != ObjectMigrationClassification.NEW
                or current.discovered_name != planned.discovered_name
                or current.candidates
        ):
            raise EsxiNewVmBootstrapError(
                f'NEW VM evidence is stale for {planned.external_id}'
            )
        contexts.append(discovered)
    return tuple(contexts)


def _validate_target_names(nb_api, cluster, selected_vms):
    existing = nb_api.virtualization.virtual_machines.filter(
        cluster_id=cluster.id,
    )
    existing_names = {}
    for record in existing:
        existing_names.setdefault(str(record.name).casefold(), []).append(record)
    selected_names = set()
    for vm in selected_vms:
        name = netbox_vm_name(vm).casefold()
        if name in selected_names:
            raise EsxiNewVmBootstrapError("Duplicate VM names after truncation")
        selected_names.add(name)
        if existing_names.get(name):
            raise EsxiNewVmBootstrapError(
                f'Desired VM name already exists: {vm.original_name}'
            )


def _preflight(nb_api, hosts, config, migration_plan):
    if config.source_type != 'esxi':
        raise EsxiNewVmBootstrapError('ESXi bootstrap requires source_type=esxi')
    if config.source_instance != migration_plan.source_instance:
        raise EsxiNewVmBootstrapError(
            'Configuration source instance does not match migration plan'
        )
    discovered = _discovered_vms(hosts, config)
    discovered_by_id = _unique_discovered(discovered)
    selected = _selected_new(migration_plan)
    fresh = _fresh_plan(nb_api, hosts, config)
    cluster = _validate_target(nb_api, migration_plan, fresh)
    selected_vms = _validate_selected(selected, fresh, discovered_by_id)
    _validate_target_names(nb_api, cluster, selected_vms)
    ordered = tuple(sorted(
        selected_vms,
        key=lambda vm: (
            netbox_vm_name(vm).casefold(),
            virtual_machine_source_identity(vm).external_id,
        ),
    ))
    try:
        pending = tuple(
            (vm, build_vm_create_fields(vm, cluster))
            for vm in ordered
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise EsxiNewVmBootstrapError(
            f'Invalid ESXi VM create fields: {exc}'
        ) from exc
    return pending


def apply_esxi_new_vm_bootstrap(
        nb_api,
        hosts,
        config,
        migration_plan,
        *,
        confirmed=False,
):
    """Create only freshly revalidated NEW ESXi VMs, never their networks."""

    if not isinstance(migration_plan, EsxiMigrationPlan):
        raise TypeError('migration_plan must be EsxiMigrationPlan')
    if not confirmed:
        raise EsxiNewVmBootstrapError(
            'ESXi NEW VM bootstrap requires explicit confirmation'
        )

    pending = _preflight(
        nb_api, hosts, config, migration_plan,
    )
    created_ids = []
    for vm, fields in pending:
        try:
            created = nb_api.virtualization.virtual_machines.create(
                **fields
            )
        except Exception as exc:
            raise EsxiNewVmBootstrapError(
                f'ESXi VM creation failed for {vm.original_name}; '
                f'already created VM ids: {created_ids}',
                created_vm_ids=created_ids,
            ) from exc
        created_ids.append(created.id)
    return tuple(created_ids)
