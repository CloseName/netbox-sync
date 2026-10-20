"""Explicit network reconciliation for migration-validated managed ESXi VMs."""

from dataclasses import replace

from .esxi_migration import (
    EsxiMigrationPlan,
    ObjectMigrationClassification,
    build_esxi_migration_plan,
)
from .netbox_vm_network_apply import apply_vm_networks
from .source_identity import virtual_machine_source_identity


class EsxiNetworkBootstrapError(RuntimeError):
    """A controlled ESXi network bootstrap failed closed."""


def _discovered_by_identity(hosts, config):
    discovered = {}
    for host in hosts:
        if str(host.source) != "esxi" or host.source_instance != config.source_instance:
            raise EsxiNetworkBootstrapError("Discovered host is outside ESXi source scope")
        for vm in host.virtual_machines:
            identity = virtual_machine_source_identity(vm)
            if (
                identity.type != "esxi"
                or identity.instance != config.source_instance
                or identity.external_id in discovered
            ):
                raise EsxiNetworkBootstrapError("Discovered ESXi VM identity is invalid or duplicated")
            discovered[identity.external_id] = vm
    return discovered


def _selected_managed(plan):
    selected = tuple(
        item for item in plan.virtual_machines if item.classification == ObjectMigrationClassification.MANAGED
    )
    external_ids = [item.external_id for item in selected]
    if len(external_ids) != len(set(external_ids)):
        raise EsxiNetworkBootstrapError("Migration plan contains duplicate managed VM identities")
    if any(len(item.candidates) != 1 for item in selected):
        raise EsxiNetworkBootstrapError("Managed VM migration item must have exactly one identity match")
    return selected


def _fresh_plan(nb_api, hosts, config):
    try:
        return build_esxi_migration_plan(nb_api, hosts, config)
    except Exception as exc:
        raise EsxiNetworkBootstrapError(f"ESXi network bootstrap preflight failed: {exc}") from exc


def _validate_plan(plan, fresh, selected, discovered):
    if (
        fresh.source_instance != plan.source_instance
        or fresh.site_id != plan.site_id
        or fresh.cluster_id != plan.cluster_id
    ):
        raise EsxiNetworkBootstrapError("ESXi network bootstrap target changed after preflight")
    fresh_by_id = {item.external_id: item for item in fresh.virtual_machines}
    selected_ids = set()
    for planned in selected:
        current = fresh_by_id.get(planned.external_id)
        if current is None or planned.external_id not in discovered:
            raise EsxiNetworkBootstrapError(f"MANAGED VM evidence is stale for {planned.external_id}")
        same_managed_object = (
            current.classification == ObjectMigrationClassification.MANAGED
            and current.discovered_name == planned.discovered_name
            and len(current.candidates) == 1
            and current.candidates[0].object_id == planned.candidates[0].object_id
        )
        if not same_managed_object:
            raise EsxiNetworkBootstrapError(f"MANAGED VM evidence is stale for {planned.external_id}")
        selected_ids.add(planned.external_id)
    return selected_ids


def _filtered_hosts(hosts, selected_ids):
    return tuple(
        replace(
            host,
            virtual_machines=[
                vm for vm in host.virtual_machines if virtual_machine_source_identity(vm).external_id in selected_ids
            ],
        )
        for host in hosts
    )


def apply_esxi_managed_vm_network_bootstrap(
    nb_api,
    hosts,
    config,
    migration_plan,
    *,
    confirmed=False,
):
    """Reconcile networks only for freshly validated managed ESXi VMs."""

    if not isinstance(migration_plan, EsxiMigrationPlan):
        raise TypeError("migration_plan must be EsxiMigrationPlan")
    if not confirmed:
        raise EsxiNetworkBootstrapError("ESXi network bootstrap requires explicit confirmation")
    if config.source_type != "esxi":
        raise EsxiNetworkBootstrapError("ESXi network bootstrap requires source_type=esxi")
    if config.source_instance != migration_plan.source_instance:
        raise EsxiNetworkBootstrapError("Configuration source instance does not match migration plan")

    discovered = _discovered_by_identity(hosts, config)
    selected = _selected_managed(migration_plan)
    fresh = _fresh_plan(nb_api, hosts, config)
    selected_ids = _validate_plan(
        migration_plan,
        fresh,
        selected,
        discovered,
    )
    filtered_hosts = _filtered_hosts(hosts, selected_ids)
    return apply_vm_networks(
        nb_api,
        filtered_hosts,
        config,
        confirmed=True,
    )
