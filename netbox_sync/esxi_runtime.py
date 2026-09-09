"""Migration-aware normal runtime reconciliation for ESXi sources."""

from collections import Counter
from dataclasses import replace

from .esxi_migration import (
    ObjectMigrationClassification,
    build_esxi_migration_plan,
)
from .netbox_vm_apply import apply_virtual_machines
from .netbox_vm_network_apply import apply_vm_networks
from .source_identity import virtual_machine_source_identity


class EsxiRuntimeError(RuntimeError):
    """Normal ESXi runtime validation failed closed."""


def _managed_vm_ids(plan):
    selected = tuple(
        item
        for item in plan.virtual_machines
        if item.classification == ObjectMigrationClassification.MANAGED
    )
    external_ids = [item.external_id for item in selected]
    if len(external_ids) != len(set(external_ids)):
        raise EsxiRuntimeError(
            'ESXi runtime plan contains duplicate managed VM identities'
        )
    if any(len(item.candidates) != 1 for item in selected):
        raise EsxiRuntimeError(
            'Managed ESXi VM must have exactly one NetBox identity match'
        )
    return frozenset(external_ids)


def _filtered_hosts(hosts, config, managed_ids):
    filtered = []
    discovered_ids = set()
    for host in hosts:
        if host.source != 'esxi' or host.source_instance != config.source_instance:
            raise EsxiRuntimeError('Discovered host is outside ESXi source scope')
        selected = []
        for vm in host.virtual_machines:
            identity = virtual_machine_source_identity(vm)
            if identity.external_id in discovered_ids:
                raise EsxiRuntimeError('Duplicate discovered ESXi VM identity')
            discovered_ids.add(identity.external_id)
            if identity.external_id in managed_ids:
                selected.append(vm)
        filtered.append(replace(host, virtual_machines=selected))
    if not managed_ids.issubset(discovered_ids):
        raise EsxiRuntimeError('Managed ESXi VM is missing from discovery')
    return tuple(filtered)


def _print_plan(plan):
    vm_counts = Counter(item.classification.value for item in plan.virtual_machines)
    host_counts = Counter(item.classification.value for item in plan.hosts)
    print('=== ESXI RUNTIME PREFLIGHT ===')
    print(f'source_instance={plan.source_instance}')
    print(
        'hosts='
        + ' '.join(
            f'{name.lower()}={count}' for name, count in sorted(host_counts.items())
        )
    )
    print(
        'virtual_machines='
        + ' '.join(
            f'{name.lower()}={count}' for name, count in sorted(vm_counts.items())
        )
    )
    for item in plan.hosts:
        print(
            f'HOST {item.classification.value} '
            f'name={item.discovered_name!r} external_id={item.external_id!r}'
        )
    for item in plan.virtual_machines:
        if item.classification != ObjectMigrationClassification.MANAGED:
            print(
                f'VM {item.classification.value} '
                f'name={item.discovered_name!r} external_id={item.external_id!r} '
                'action=REPORT_ONLY'
            )
    print('host_networking=UNSUPPORTED_REPORT_ONLY')
    print('disappearance=RETAIN_ONLY')


def execute_esxi_runtime(nb_api, hosts, config, *, confirmed=False):
    """Reconcile only identity-managed ESXi VMs through the normal runtime."""

    if config.source_type != 'esxi':
        raise EsxiRuntimeError('ESXi runtime requires source_type=esxi')
    if not isinstance(confirmed, bool):
        raise TypeError('confirmed must be a boolean')

    from .host_mapping import validate
    validate(nb_api,config.target,hosts)
    try:
        plan = build_esxi_migration_plan(nb_api, hosts, config)
        managed_ids = _managed_vm_ids(plan)
        filtered_hosts = _filtered_hosts(hosts, config, managed_ids)
    except EsxiRuntimeError:
        raise
    except Exception as exc:
        raise EsxiRuntimeError(f'ESXi runtime preflight failed: {exc}') from exc

    _print_plan(plan)

    # Every stage validates the complete managed set before the first write.
    apply_virtual_machines(
        nb_api, filtered_hosts, config.target, confirmed=False,
    )
    apply_vm_networks(
        nb_api, filtered_hosts, config, confirmed=False,
    )

    if not confirmed:
        print('ESXi runtime preflight completed. No changes were written to NetBox.')
        return plan

    apply_virtual_machines(
        nb_api, filtered_hosts, config.target, confirmed=True,
    )
    apply_vm_networks(
        nb_api, filtered_hosts, config, confirmed=True,
    )
    return plan
