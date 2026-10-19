# pylint: disable=fixme,too-many-branches

"""
NetBox Sync: Synchronize Proxmox Virtual Environment (PVE) information to a NetBox instance
"""

import os
import sys
from typing import Optional

import pynetbox
import urllib3
from proxmoxer import ProxmoxAPI, ResourceException

from .proxmox_discovery import discover_hosts
from .netbox_planner import plan_hosts
from .source_config import SourceConfig
from .source_bootstrap import (
    LEGACY_MODE,
    REGISTRY_ALL_MODE,
    load_runtime_source_config,
    load_runtime_source_configs,
    runtime_source_mode,
)
from .secret_resolver import FileSecretResolver, LegacyFileSecretResolver
from .orchestrator import run_sources
from .scheduled_failure import mark as _scheduled_stage
from .source_executor import SourceExecutorDispatch
from .esxi_executor import execute_esxi_source
from .esxi_runtime import execute_esxi_runtime
from .netbox_apply import apply_hosts
from .netbox_vm_apply import apply_virtual_machines
from .netbox_vm_network_apply import apply_vm_networks
from .netbox_lxc_apply import apply_lxc_containers
from .netbox_lxc_network_apply import apply_lxc_networks
from .netbox_full_apply import apply_full_sync
from .run_history import postgres_run_repository


from .legacy_netbox_writes import (
    _process_pve_tags,
    _process_pve_virtual_machine,
    _process_pve_virtual_machine_network_interfaces,
    _process_pve_virtual_machine_network_interface,
    _process_pve_virtual_machine_disks,
    _process_pve_virtual_machine_disk,
    _parse_pve_network_definition,
    _parse_pve_disk_definition,
    _process_pve_disk_size,
    _get_virtual_machine_vcpus,
)
from . import legacy_inventory as _legacy_inventory
from .legacy_inventory import _run_inventory, _load_nb_objects
from . import entrypoint as _entrypoint
from . import sync_execution as _sync_execution
from . import proxmox_executor as _proxmox_executor
from .proxmox_executor import _get_pve_token_name
from .entrypoint import VALID_SYNC_MODES, _get_sync_mode, _print_multi_source_result


def _read_secret(variable_name: str) -> str:
    file_variable_name = f'{variable_name}_FILE'
    file_path = os.getenv(file_variable_name)

    if file_path:
        try:
            with open(file_path, 'r', encoding='utf-8') as secret_file:
                value = secret_file.read().strip()
        except OSError as exc:
            raise RuntimeError(
                f'Unable to read secret file configured by {file_variable_name}'
            ) from exc
    else:
        value = os.getenv(variable_name, '').strip()

    if not value:
        raise RuntimeError(
            f'Missing required secret: set {variable_name} or {file_variable_name}'
        )

    return value


def _run_plan(_pve_api: ProxmoxAPI, _nb_objects: dict) -> None:
    """Keep the historical report API and per-call CPU helper lookup."""
    return _legacy_inventory._run_plan(
        _pve_api, _nb_objects, _get_virtual_machine_vcpus=_get_virtual_machine_vcpus,
    )


def execute_proxmox_source(source_config, sync_mode, legacy_secrets=False):
    """Keep the package API and existing adapter injection points available."""
    return _proxmox_executor.execute_proxmox_source(
        source_config, sync_mode, legacy_secrets=legacy_secrets,
        _scheduled_stage=_scheduled_stage,
        LegacyFileSecretResolver=LegacyFileSecretResolver,
        FileSecretResolver=FileSecretResolver,
        ProxmoxAPI=ProxmoxAPI,
        _get_pve_token_name=_get_pve_token_name,
        discover_hosts=discover_hosts,
        execute_discovered_source=execute_discovered_source,
    )


def execute_discovered_source(source_config, hosts, sync_mode, pve_api=None):
    """Preserve the package API and resolve existing collaborators per invocation."""
    return _sync_execution.execute_discovered_source(
        source_config, hosts, sync_mode, pve_api=pve_api,
        _scheduled_stage=_scheduled_stage,
        _read_secret=_read_secret,
        execute_esxi_runtime=execute_esxi_runtime,
        apply_full_sync=apply_full_sync,
        _load_nb_objects=_load_nb_objects,
        _run_inventory=_run_inventory,
        plan_hosts=plan_hosts,
        apply_hosts=apply_hosts,
        apply_virtual_machines=apply_virtual_machines,
        apply_vm_networks=apply_vm_networks,
        apply_lxc_containers=apply_lxc_containers,
        apply_lxc_networks=apply_lxc_networks,
        _process_pve_tags=_process_pve_tags,
        _process_pve_virtual_machine=_process_pve_virtual_machine,
    )


def _source_dispatch(sync_mode):
    return SourceExecutorDispatch({
        'proxmox': lambda config: execute_proxmox_source(
            config,
            sync_mode,
        ),
        'esxi': lambda config: execute_esxi_source(
            config,
            sync_mode,
            execute_discovered_source,
        ),
    })


def main():
    """Stable console entrypoint; resolve dependencies at invocation time."""
    return _entrypoint.run(
        _get_sync_mode=_get_sync_mode, runtime_source_mode=runtime_source_mode,
        _source_dispatch=_source_dispatch, postgres_run_repository=postgres_run_repository,
        _print_multi_source_result=_print_multi_source_result,
        load_runtime_source_config=load_runtime_source_config,
        execute_proxmox_source=execute_proxmox_source,
    )


if __name__ == '__main__':
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    main()
