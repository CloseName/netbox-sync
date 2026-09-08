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


VALID_SYNC_MODES = {'inventory', 'plan', 'apply'}


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


def _get_pve_token_name(pve_user: str, token_id: str) -> str:
    if '!' not in token_id:
        return token_id

    token_user, token_name = token_id.split('!', 1)

    if token_user != pve_user:
        raise RuntimeError(
            f'PVE token belongs to "{token_user}", '
            f'but PVE_API_USER is "{pve_user}"'
        )

    if not token_name:
        raise RuntimeError('PVE token name is empty')

    return token_name


def _get_sync_mode() -> str:
    sync_mode = os.getenv('SYNC_MODE', 'inventory').strip().lower()

    if sync_mode not in VALID_SYNC_MODES:
        print(
            f'Invalid SYNC_MODE="{sync_mode}". '
            f'Allowed values: {", ".join(sorted(VALID_SYNC_MODES))}.'
        )
        sys.exit(2)

    return sync_mode


def _run_inventory(
        _nb_objects: dict,
        hosts,
) -> None:
    """
    Read-only inventory mode.

    This function only reads data from Proxmox and NetBox.
    It must not create, update or delete any NetBox objects.
    """

    print('=== SAFE INVENTORY MODE ===')
    print('No changes will be written to NetBox.')
    print()

    print('NetBox inventory:')
    print(f'  Devices:          {len(_nb_objects["devices"])}')
    print(f'  Virtual machines: {len(_nb_objects["virtual_machines"])}')
    print(f'  IP addresses:     {len(_nb_objects["ip_addresses"])}')
    print(f'  Prefixes:         {len(_nb_objects["prefixes"])}')
    print(f'  VLANs:            {len(_nb_objects["vlans"])}')
    print()

    print(f'Discovered infrastructure hosts: {len(hosts)}')
    print()

    for host in hosts:
        print(f'HOST {host.normalized_name}')
        print(f'  source:             {host.source}')
        print(f'  source_instance:    {host.source_instance}')
        print(f'  source_id:          {host.source_id}')
        print(f'  original_name:      {host.original_name}')
        print(f'  management_ip:      {host.management_ip or "-"}')
        print(f'  hypervisor:         {host.hypervisor}')
        print(f'  hypervisor_version: {host.hypervisor_version or "-"}')
        print(f'  cpu_model:          {host.cpu.model or "-"}')
        print(f'  cpu_vendor:         {host.cpu.vendor or "-"}')
        print(f'  cpu_sockets:        {host.cpu.sockets}')
        print(f'  cpu_cores:          {host.cpu.cores}')
        print(f'  logical_cpus:       {host.cpu.logical_cpus}')
        print(f'  memory_mib:         {host.memory_bytes // 1024**2}')
        print(f'  physical_disks:     {len(host.disks)}')

        for disk in host.disks:
            print(
                f'    DISK path={disk.path} '
                f'model={disk.model or "-"} '
                f'serial={disk.serial or "-"} '
                f'type={disk.disk_type or "-"} '
                f'size_gib={disk.size_bytes / 1024**3:.2f} '
                f'health={disk.health or "-"}'
            )

        print(f'  storages:           {len(host.storages)}')

        for storage in host.storages:
            print(
                f'    STORAGE name={storage.name} '
                f'type={storage.storage_type or "-"} '
                f'total_gib={storage.total_bytes / 1024**3:.2f} '
                f'active={storage.active}'
            )

        print(f'  host_interfaces:    {len(host.interfaces)}')

        for interface in sorted(
                host.interfaces,
                key=lambda item: item.name
        ):
            addresses = (
                ','.join(interface.addresses)
                if interface.addresses
                else '-'
            )

            ports = (
                ','.join(interface.bridge_ports)
                if interface.bridge_ports
                else '-'
            )

            print(
                f'    HOST_NIC name={interface.name} '
                f'type={interface.interface_type or "-"} '
                f'active={interface.active} '
                f'autostart={interface.autostart} '
                f'method={interface.method or "-"} '
                f'vlan={interface.vlan_id if interface.vlan_id is not None else "-"} '
                f'vlan_aware={interface.vlan_aware} '
                f'ports={ports} '
                f'ips={addresses} '
                f'gateway={interface.gateway or "-"} '
                f'comment={interface.comments or "-"}'
            )

        print()

        print(f'  virtual_machines:   {len(host.virtual_machines)}')

        for vm in sorted(
                host.virtual_machines,
                key=lambda item: item.vmid
        ):
            print(
                f'    VM vmid={vm.vmid} '
                f'source_id={vm.source_id} '
                f'name={vm.original_name} '
                f'status={vm.status} '
                f'vcpus={vm.vcpus} '
                f'memory_mib={vm.memory_bytes // 1024**2} '
                f'autostart={vm.autostart}'
            )

            for disk in vm.disks:
                print(
                    f'      DISK name={disk.name} '
                    f'storage={disk.storage or "-"} '
                    f'size_gib={disk.size_bytes / 1024**3:.2f}'
                )

            for interface in vm.interfaces:
                addresses = (
                    ','.join(interface.ip_addresses)
                    if interface.ip_addresses
                    else '-'
                )

                print(
                    f'      NIC name={interface.name} '
                    f'mac={interface.mac_address or "-"} '
                    f'bridge={interface.bridge or "-"} '
                    f'vlan={interface.vlan_id if interface.vlan_id is not None else "-"} '
                    f'ips={addresses}'
                )

        print(f'  containers:         {len(host.containers)}')

        for container in sorted(
                host.containers,
                key=lambda item: item.vmid
        ):
            print(
                f'    LXC vmid={container.vmid} '
                f'source_id={container.source_id} '
                f'name={container.original_name} '
                f'status={container.status} '
                f'os={container.os_type or "-"} '
                f'arch={container.architecture or "-"} '
                f'vcpus={container.vcpus} '
                f'memory_mib={container.memory_bytes // 1024**2} '
                f'swap_mib={container.swap_bytes // 1024**2} '
                f'autostart={container.autostart} '
                f'unprivileged={container.unprivileged}'
            )

            for disk in container.disks:
                print(
                    f'      DISK name={disk.name} '
                    f'storage={disk.storage or "-"} '
                    f'size_gib={disk.size_bytes / 1024**3:.2f}'
                )

            for interface in container.interfaces:
                addresses = (
                    ','.join(interface.ip_addresses)
                    if interface.ip_addresses
                    else '-'
                )

                print(
                    f'      NIC name={interface.name} '
                    f'mac={interface.mac_address or "-"} '
                    f'bridge={interface.bridge or "-"} '
                    f'vlan={interface.vlan_id if interface.vlan_id is not None else "-"} '
                    f'ips={addresses}'
                )

        print()



def _run_plan(_pve_api: ProxmoxAPI, _nb_objects: dict) -> None:
    """
    Build a read-only synchronization plan.

    No NetBox objects are created, updated or deleted.
    """

    print('=== SAFE PLAN MODE ===')
    print('No changes will be written to NetBox.')
    print()

    create_count = 0
    update_count = 0
    unchanged_count = 0
    blocked_count = 0

    for pve_node in _pve_api.nodes.get():
        node_name = pve_node['node']
        nb_device = _nb_objects['devices'].get(node_name.lower())
        pve_vms = _pve_api.nodes(node_name).qemu.get()

        if nb_device is None:
            print(
                f'BLOCKED node={node_name}: '
                f'NetBox device with matching name was not found'
            )

            for pve_vm in pve_vms:
                print(
                    f'  BLOCKED vmid={pve_vm["vmid"]} '
                    f'name={pve_vm.get("name", "-")}'
                )
                blocked_count += 1

            continue

        print(
            f'NODE node={node_name} '
            f'netbox_device_id={nb_device.id}'
        )

        for pve_vm in pve_vms:
            vmid = str(pve_vm['vmid'])

            pve_config = _pve_api \
                .nodes(node_name) \
                .qemu(pve_vm['vmid']) \
                .config.get()

            expected_name = pve_vm['name']
            expected_vcpus = int(_get_virtual_machine_vcpus(pve_config))
            expected_memory = int(pve_config['memory'])
            expected_status = (
                'active'
                if pve_vm['status'] == 'running'
                else 'offline'
            )

            nb_vm = _nb_objects['virtual_machines'].get(vmid)

            if nb_vm is None:
                print(
                    f'  CREATE vmid={vmid} '
                    f'name={expected_name} '
                    f'vcpus={expected_vcpus} '
                    f'memory={expected_memory} '
                    f'status={expected_status}'
                )
                create_count += 1
                continue

            changes = []

            if str(nb_vm.name) != expected_name:
                changes.append(
                    f'name:{nb_vm.name}->{expected_name}'
                )

            try:
                current_vcpus = int(float(nb_vm.vcpus))
            except (TypeError, ValueError):
                current_vcpus = None

            if current_vcpus != expected_vcpus:
                changes.append(
                    f'vcpus:{current_vcpus}->{expected_vcpus}'
                )

            try:
                current_memory = int(nb_vm.memory)
            except (TypeError, ValueError):
                current_memory = None

            if current_memory != expected_memory:
                changes.append(
                    f'memory:{current_memory}->{expected_memory}'
                )

            current_status = str(
                getattr(nb_vm.status, 'value', nb_vm.status)
            )

            if current_status != expected_status:
                changes.append(
                    f'status:{current_status}->{expected_status}'
                )

            current_device = getattr(nb_vm, 'device', None)
            current_device_id = getattr(current_device, 'id', None)

            if current_device_id != nb_device.id:
                changes.append(
                    f'device:{current_device_id}->{nb_device.id}'
                )

            if changes:
                print(
                    f'  UPDATE vmid={vmid} '
                    f'name={expected_name} '
                    + ' '.join(changes)
                )
                update_count += 1
            else:
                print(
                    f'  SKIP vmid={vmid} '
                    f'name={expected_name} '
                    f'reason=no-change'
                )
                unchanged_count += 1

    print()
    print('Plan summary:')
    print(f'  CREATE:  {create_count}')
    print(f'  UPDATE:  {update_count}')
    print(f'  SKIP:    {unchanged_count}')
    print(f'  BLOCKED: {blocked_count}')


def _load_nb_objects(_nb_api: pynetbox.api) -> dict:
    _nb_objects = {
        'devices': {},
        'virtual_machines': {},
        'virtual_machines_interfaces': {},
        'mac_addresses': {},
        'prefixes': {},
        'ip_addresses': {},
        'vlans': {},
        'disks': {},
        'tags': {},
    }

    # Load NetBox devices
    for _nb_device in _nb_api.dcim.devices.all():
        _nb_objects['devices'][_nb_device.name.lower()] = _nb_device

    # Load NetBox virtual machines
    for _nb_virtual_machine in _nb_api.virtualization.virtual_machines.all():
        _nb_objects['virtual_machines'][_nb_virtual_machine.serial] = _nb_virtual_machine

    # Load NetBox interfaces
    for _nb_interface in _nb_api.virtualization.interfaces.all():
        if _nb_interface.virtual_machine.id not in _nb_objects['virtual_machines_interfaces']:
            _nb_objects['virtual_machines_interfaces'][_nb_interface.virtual_machine.id] = {}

        _nb_objects['virtual_machines_interfaces'][_nb_interface.virtual_machine.id][_nb_interface.name] = _nb_interface

    # Load NetBox mac addresses
    for _nb_mac_address in _nb_api.dcim.mac_addresses.all():
        _nb_objects['mac_addresses'][_nb_mac_address.mac_address] = _nb_mac_address

    # Load NetBox IP ranges
    for _nb_prefix in _nb_api.ipam.prefixes.all():
        _nb_objects['prefixes'][_nb_prefix.prefix] = _nb_prefix

    # Load NetBox IP addresses
    for _nb_ip_address in _nb_api.ipam.ip_addresses.all():
        _nb_objects['ip_addresses'][_nb_ip_address['address']] = _nb_ip_address

    # Load NetBox vLANs
    for _nb_vlan in _nb_api.ipam.vlans.all():
        _nb_objects['vlans'][str(_nb_vlan.vid)] = _nb_vlan

    # Load NetBox disks
    for _nb_disk in _nb_api.virtualization.virtual_disks.all():
        if _nb_disk.virtual_machine.id not in _nb_objects['disks']:
            _nb_objects['disks'][_nb_disk.virtual_machine.id] = {}

        _nb_objects['disks'][_nb_disk.virtual_machine.id][_nb_disk.name] = _nb_disk

    # Load NetBox tags
    for _nb_tag in _nb_api.extras.tags.all():
        _nb_objects['tags'][_nb_tag.name] = _nb_tag

    return _nb_objects


def _process_pve_tags(
        _pve_api: ProxmoxAPI,
        _nb_api: pynetbox.api,
        _nb_objects: dict,
) -> dict:
    # TODO: First tags

    # Then pool (we treat them as tags)
    for _pve_pool in _pve_api.pools.get():
        _tag_name = f'Pool/{_pve_pool["poolid"]}'
        _nb_tag = _nb_objects['tags'].get(_tag_name)
        if _nb_tag is None:
            _nb_tag = _nb_api.extras.tags.create(
                name=_tag_name,
                slug=f'pool-{_pve_pool["poolid"]}'.lower(),
                description=f'Proxmox pool {_pve_pool["poolid"]}',
            )
            _nb_objects['tags'][_nb_tag.name] = _nb_tag

    return _nb_objects


def _process_pve_virtual_machine(
        _pve_api: ProxmoxAPI,
        _nb_api: pynetbox.api,
        _nb_objects: dict,
        _nb_device: any,
        _pve_tags: [str],
        _pve_virtual_machine: dict,
        _is_replicated: bool,
        _has_ha: bool,
) -> dict:
    _pve_node_name = _nb_device.name.lower()

    pve_virtual_machine_config = _pve_api.nodes(_pve_node_name).qemu(_pve_virtual_machine['vmid']).config.get()

    try:
        pve_virtual_machine_agent_interfaces = _pve_api \
            .nodes(_pve_node_name) \
            .qemu(_pve_virtual_machine['vmid']) \
            .agent('network-get-interfaces') \
            .get()
    except ResourceException:
        pve_virtual_machine_agent_interfaces = {'result': []}

    # Extract IP addresses from QEMU
    pve_virtual_machine_ip_addresses = {}
    for result in pve_virtual_machine_agent_interfaces['result']:
        pve_virtual_machine_ip_addresses[result['name']] = result['ip-addresses']

    # Create the virtual machine if it exists, update it otherwise
    nb_virtual_machine = _nb_objects['virtual_machines'].get(str(_pve_virtual_machine['vmid']))
    if nb_virtual_machine is None:
        nb_virtual_machine = _nb_api.virtualization.virtual_machines.create(
            serial=_pve_virtual_machine['vmid'],
            name=_pve_virtual_machine['name'],
            site=_nb_device.site.id,
            cluster=os.environ.get('NB_CLUSTER_ID', 1),
            device=_nb_device.id,
            vcpus=_get_virtual_machine_vcpus(pve_virtual_machine_config),
            memory=int(pve_virtual_machine_config['memory']),
            status='active' if _pve_virtual_machine['status'] == 'running' else 'offline',
            tags=list(map(lambda _pve_tag_name: _nb_objects['tags'][_pve_tag_name].id, _pve_tags)),
            custom_fields={
                'autostart': pve_virtual_machine_config.get('onboot') == 1,
                'replicated': _is_replicated,
                'ha': _has_ha,
            }
        )
    else:
        nb_virtual_machine.name = _pve_virtual_machine['name']
        nb_virtual_machine.site = _nb_device.site.id
        nb_virtual_machine.cluster = os.environ.get('NB_CLUSTER_ID', 1)
        nb_virtual_machine.device = _nb_device.id
        nb_virtual_machine.vcpus = _get_virtual_machine_vcpus(pve_virtual_machine_config)
        nb_virtual_machine.memory = int(pve_virtual_machine_config['memory'])
        nb_virtual_machine.status = 'active' if _pve_virtual_machine['status'] == 'running' else 'offline'
        nb_virtual_machine.tags = list(map(lambda _pve_tag_name: _nb_objects['tags'][_pve_tag_name].id, _pve_tags))
        nb_virtual_machine.custom_fields['autostart'] = pve_virtual_machine_config.get('onboot') == 1
        nb_virtual_machine.custom_fields['replicated'] = _is_replicated
        nb_virtual_machine.custom_fields['ha'] = _has_ha
        nb_virtual_machine.save()

    # Handle the VM network interfaces
    _process_pve_virtual_machine_network_interfaces(
        _nb_api,
        _nb_objects,
        pve_virtual_machine_config,
        nb_virtual_machine,
        pve_virtual_machine_ip_addresses,
    )

    # Handle the VM disks
    _process_pve_virtual_machine_disks(
        _nb_api,
        _nb_objects,
        pve_virtual_machine_config,
        nb_virtual_machine,
    )

    return _nb_objects


def _process_pve_virtual_machine_network_interfaces(
        _nb_api: pynetbox.api,
        _nb_objects: dict,
        _pve_virtual_machine_config: dict,
        _nb_virtual_machine: any,
        _pve_virtual_machine_ip_addresses: dict,
) -> dict:
    # Handle the VM network interfaces
    for (_config_key, _config_value) in _pve_virtual_machine_config.items():
        if not _config_key.startswith('net'):
            continue

        _network_definition = _parse_pve_network_definition(_config_value)

        # Determinate MAC address
        network_mac_address = None
        for _model in ['virtio', 'e1000']:
            if _model in _network_definition:
                network_mac_address = _network_definition[_model]
                break

        if network_mac_address is None:
            continue

        _process_pve_virtual_machine_network_interface(
            _nb_api,
            _nb_objects,
            _nb_virtual_machine,
            _config_key,
            network_mac_address,
            _network_definition.get('tag'),
            _pve_virtual_machine_ip_addresses,
        )

    return _nb_objects


def _process_pve_virtual_machine_network_interface(
        _nb_api: pynetbox.api,
        _nb_objects: dict,
        _nb_virtual_machine: any,
        _interface_name: str,
        _interface_mac_address: str,
        _interface_vlan_id: Optional[int],
        _pve_virtual_machine_ip_addresses: dict,
) -> dict:
    nb_virtual_machines_interface = _nb_objects['virtual_machines_interfaces'] \
        .get(_nb_virtual_machine.id, {}) \
        .get(_interface_name)

    if nb_virtual_machines_interface is None:
        nb_virtual_machines_interface = _nb_api.virtualization.interfaces.create(
            virtual_machine=_nb_virtual_machine.id,
            name=_interface_name,
            description=_interface_mac_address,
        )

        if _nb_virtual_machine.id not in _nb_objects['virtual_machines_interfaces']:
            _nb_objects['virtual_machines_interfaces'][_nb_virtual_machine.id] = {}

        _nb_objects['virtual_machines_interfaces'][_nb_virtual_machine.id][
            _interface_name] = nb_virtual_machines_interface

    # Create the MAC address and link it to the VM
    nb_mac_address = _nb_objects['mac_addresses'].get(_interface_mac_address)
    if nb_mac_address is None:
        nb_mac_address = _nb_api.dcim.mac_addresses.create(
            mac_address=_interface_mac_address,
            assigned_object_type='virtualization.vminterface',
            assigned_object_id=nb_virtual_machines_interface.id,
        )

        _nb_objects['mac_addresses'][_interface_mac_address] = nb_mac_address

        nb_virtual_machines_interface.primary_mac_address = nb_mac_address.id
        nb_virtual_machines_interface.save()

    # TODO: Improve Multiple IP address handling
    _pve_virtual_machine_ip_address = None
    for raw_interface_name in ['eth0', 'ens18', 'ens19']:
        if raw_interface_name in _pve_virtual_machine_ip_addresses:
            _pve_virtual_machine_ip_address = _pve_virtual_machine_ip_addresses[raw_interface_name][0]
            break

    if _pve_virtual_machine_ip_address is not None:
        _virtual_machine_address = _pve_virtual_machine_ip_address['ip-address']
        _virtual_machine_address_mask = _pve_virtual_machine_ip_address['prefix']
        _virtual_machine_full_address = f'{_virtual_machine_address}/{_virtual_machine_address_mask}'

        # First, determinate if the prefix exists
        _prefix_network_address = '.'.join(_virtual_machine_address.split('.')[:-1]) + '.0'
        _prefix_network_full_address = f'{_prefix_network_address}/{_virtual_machine_address_mask}'

        nb_prefix = _nb_objects['prefixes'].get(_prefix_network_full_address)
        if nb_prefix is None:
            nb_prefix = _nb_api.ipam.prefixes.create(prefix=_prefix_network_full_address)
            _nb_objects['prefixes'][nb_prefix.prefix] = nb_prefix

        if 'dns_name' in nb_prefix.custom_fields and nb_prefix.custom_fields['dns_name'] is not None:
            ip_address_dns_name = f'{_nb_virtual_machine.name}.{nb_prefix.custom_fields["dns_name"]}'
        else:
            ip_address_dns_name = ''

        nb_ip_address = _nb_objects['ip_addresses'].get(_virtual_machine_full_address)
        if nb_ip_address is None:
            nb_ip_address = _nb_api.ipam.ip_addresses.create(
                address=_virtual_machine_full_address,
                assigned_object_type='virtualization.vminterface',
                assigned_object_id=nb_virtual_machines_interface.id,
                dns_name=ip_address_dns_name
            )
            _nb_objects['ip_addresses'][nb_ip_address.address] = nb_ip_address
        else:
            nb_ip_address.assigned_object_type = 'virtualization.vminterface'
            nb_ip_address.assigned_object_id = nb_virtual_machines_interface.id
            nb_ip_address.dns_name = ip_address_dns_name
            nb_ip_address.save()

        _nb_virtual_machine.primary_ip4 = nb_ip_address.id
        _nb_virtual_machine.save()

        # Handle VLAN
        if _interface_vlan_id is not None:
            nb_vlan = _nb_objects['vlans'].get(str(_interface_vlan_id))
            if nb_vlan is None:
                nb_vlan = _nb_api.ipam.vlans.create(
                    vid=_interface_vlan_id,
                    name=f'VLAN {_interface_vlan_id}',
                )
                _nb_objects['vlans'][_interface_vlan_id] = nb_vlan

            nb_prefix.vlan = nb_vlan.id
            nb_prefix.save()

    return _nb_objects


def _process_pve_virtual_machine_disks(
        _nb_api: pynetbox.api,
        _nb_objects: dict,
        _pve_virtual_machine_config: dict,
        _nb_virtual_machine: any,
) -> dict:
    # Handle the VM disks
    for (_config_key, _config_value) in _pve_virtual_machine_config.items():
        if not _config_key.startswith('scsi'):
            continue
        if _config_key == 'scsihw':
            continue

        _disk_definition = _parse_pve_disk_definition(_config_value)

        _process_pve_virtual_machine_disk(
            _nb_api,
            _nb_objects,
            _nb_virtual_machine,
            _disk_definition['name'],
            _process_pve_disk_size(_disk_definition['size']),
            _disk_definition.get('backup', '1') == '1',
        )

    return _nb_objects


def _process_pve_virtual_machine_disk(
        _nb_api: pynetbox.api,
        _nb_objects: dict,
        _nb_virtual_machine: any,
        _disk_name: str,
        _disk_size: int,
        _has_backup: bool,
) -> dict:
    nb_disk = _nb_objects['disks'].get(_nb_virtual_machine.id, {}).get(_disk_name)
    if nb_disk is None:
        _nb_api.virtualization.virtual_disks.create(
            name=_disk_name,
            size=_disk_size,
            virtual_machine=_nb_virtual_machine.id,
            custom_fields={
                'backup': _has_backup,
            }
        )
    else:
        nb_disk.size = _disk_size
        nb_disk.custom_fields['backup'] = _has_backup
        nb_disk.save()

    return _nb_objects


def _parse_pve_network_definition(_raw_network_definition: str) -> dict:
    _network_definition = {}

    for _component in _raw_network_definition.split(','):
        _component_parts = _component.split('=')
        _network_definition[_component_parts[0]] = _component_parts[1]

    return _network_definition


def _parse_pve_disk_definition(_raw_disk_definition: str) -> dict:
    _disk_definition = {}

    for _component in _raw_disk_definition.split(','):
        _component_parts = _component.split('=')
        if len(_component_parts) == 1:
            _disk_definition['name'] = _component_parts[0]
        else:
            _disk_definition[_component_parts[0]] = _component_parts[1]

    return _disk_definition


def _process_pve_disk_size(_raw_disk_size: str) -> int:
    size = _raw_disk_size[:-1]
    size_unit = _raw_disk_size[-1]

    if size_unit == 'M':
        return int(size)
    if size_unit == 'G':
        return int(size) * 1_000
    if size_unit == 'T':
        return int(size) * 1_000_000

    return -1


def _get_virtual_machine_vcpus(_pve_virtual_machine_config: dict) -> int:
    if 'vcpus' in _pve_virtual_machine_config:
        return _pve_virtual_machine_config['vcpus']

    return _pve_virtual_machine_config['cores'] * _pve_virtual_machine_config['sockets']


def execute_proxmox_source(
        source_config,
        sync_mode,
        legacy_secrets=False,
):
    """Execute the existing validated pipeline for one Proxmox source."""

    resolver_class = (
        LegacyFileSecretResolver
        if legacy_secrets
        else FileSecretResolver
    )
    pve_credentials = resolver_class().resolve_credentials(
        source_config.credentials
    )

    # Instantiate connection to the Proxmox VE API
    pve_user = pve_credentials.username

    pve_api = ProxmoxAPI(
        host=source_config.address,
        user=pve_user,
        token_name=_get_pve_token_name(pve_user, pve_credentials.token_id),
        token_value=pve_credentials.token_secret,
        verify_ssl=source_config.verify_ssl,
    )

    hosts = discover_hosts(pve_api, source_config)
    return execute_discovered_source(
        source_config,
        hosts,
        sync_mode,
        pve_api=pve_api,
    )


def execute_discovered_source(
        source_config,
        hosts,
        sync_mode,
        pve_api=None,
):
    """Run the shared NetBox pipeline for generic discovered objects."""

    # Select the NetBox token by synchronization mode.
    #
    # inventory / plan:
    #   read-only token
    #
    # apply:
    #   dedicated write-enabled token, available only through
    #   the explicit apply compose override.
    if sync_mode == 'apply':
        apply_scope = os.getenv(
            'APPLY_SCOPE',
            '',
        ).strip().lower()

        if apply_scope not in {
            'host',
            'vm',
            'vm-network',
            'lxc',
            'lxc-network',
            'full',
        }:
            raise SystemExit(
                'SYNC_MODE=apply requires '
                'APPLY_SCOPE=host, vm, '
                'vm-network, lxc, '
                'lxc-network, or full. '
                'No changes were written.'
            )

        nb_token_variable = 'NB_APPLY_API_TOKEN'
    else:
        nb_token_variable = 'NB_API_TOKEN'

    # Read durable truth only inside the trusted scheduled runtime.
    if os.environ.get('NETBOX_SYNC_NETBOX_CONFIG_FILE'):
        from .bootstrap_state import runtime_netbox
        netbox_url, netbox_token = runtime_netbox(os.environ['NETBOX_SYNC_NETBOX_CONFIG_FILE'], 'apply' if sync_mode == 'apply' else 'read')
    else:
        netbox_url, netbox_token = os.environ['NB_API_URL'], _read_secret(nb_token_variable)
    nb_api = pynetbox.api(url=netbox_url, token=netbox_token)

    if source_config.source_type == 'esxi' and sync_mode == 'plan':
        execute_esxi_runtime(
            nb_api,
            hosts,
            source_config,
            confirmed=False,
        )
        return

    if source_config.source_type == 'esxi' and sync_mode == 'apply':
        if apply_scope != 'full':
            raise SystemExit(
                'Normal ESXi apply requires APPLY_SCOPE=full. '
                'No changes were written.'
            )
        from .application.runtime_plan import build_runtime_plan
        history_plan = build_runtime_plan(nb_api, hosts, source_config)
        execute_esxi_runtime(
            nb_api,
            hosts,
            source_config,
            confirmed=(
                os.getenv('APPLY_CONFIRM', '') == 'FULL_WRITE'
            ),
        )
        return history_plan

    # Load NetBox objects
    nb_objects = _load_nb_objects(nb_api)

    if sync_mode == 'inventory':
        _run_inventory(
            nb_objects,
            hosts,
        )
        return

    if sync_mode == 'plan':
        target_config = source_config.target

        plan_hosts(
            nb_api,
            nb_objects,
            hosts,
            target_config,
        )
        return

    if sync_mode == 'apply':
        target_config = source_config.target

        if apply_scope == 'host':
            apply_hosts(
                nb_api,
                hosts,
                target_config,
                confirmed=(
                    os.getenv(
                        'APPLY_CONFIRM',
                        ''
                    ) == 'HOST_WRITE'
                ),
            )
            return

        if apply_scope == 'vm':
            apply_virtual_machines(
                nb_api,
                hosts,
                target_config,
                confirmed=(
                    os.getenv(
                        'APPLY_CONFIRM',
                        ''
                    ) == 'VM_WRITE'
                ),
            )
            return

        if apply_scope == 'vm-network':
            apply_vm_networks(
                nb_api,
                hosts,
                target_config,
                confirmed=(
                    os.getenv(
                        'APPLY_CONFIRM',
                        ''
                    )
                    == 'VM_NETWORK_WRITE'
                ),
            )
            return

        if apply_scope == 'lxc':
            apply_lxc_containers(
                nb_api,
                hosts,
                target_config,
                confirmed=(
                    os.getenv(
                        'APPLY_CONFIRM',
                        ''
                    )
                    == 'LXC_WRITE'
                ),
            )
            return

        if apply_scope == 'lxc-network':
            apply_lxc_networks(
                nb_api,
                hosts,
                target_config,
                confirmed=(
                    os.getenv(
                        'APPLY_CONFIRM',
                        ''
                    )
                    == 'LXC_NETWORK_WRITE'
                ),
            )
            return

        if apply_scope == 'full':
            from .application.runtime_plan import build_runtime_plan
            history_plan = build_runtime_plan(nb_api, hosts, source_config)
            apply_full_sync(
                nb_api,
                hosts,
                target_config,
                confirmed=(
                    os.getenv(
                        'APPLY_CONFIRM',
                        ''
                    )
                    == 'FULL_WRITE'
                ),
            )
            return history_plan

    print('=== APPLY MODE ===')
    print('WARNING: changes to NetBox are enabled.')

    # Process Proxmox tags
    _process_pve_tags(
        pve_api,
        nb_api,
        nb_objects,
    )

    # Fetch VM tags from Proxmox
    pve_vm_tags = {}
    for pve_vm_resource in pve_api.cluster.resources.get(type='vm'):
        pve_vm_tags[pve_vm_resource['vmid']] = []

        if 'pool' in pve_vm_resource:
            pve_vm_tags[pve_vm_resource['vmid']].append(f'Pool/{pve_vm_resource["pool"]}')

        if 'tags' in pve_vm_resource:
            pass  # TODO: pve_vm_tags[pve_vm_resource['vmid']].append(pve_vm_resource['tags'])

    pve_ha_virtual_machine_ids = list(
        map(
            lambda r: int(r['sid'].split(':')[1]),
            filter(lambda r: r['type'] == 'service', pve_api.cluster.ha.status.current.get())
        )
    )

    # Process Proxmox nodes
    for pve_node in pve_api.nodes.get():
        pve_replicated_virtual_machine_ids = list(
            map(lambda r: r['guest'], pve_api.nodes(pve_node['node']).replication.get())
        )

        # This script does not create the hardware devices.
        nb_device = nb_objects['devices'].get(pve_node['node'].lower())
        if nb_device is None:
            print(f'The device {pve_node["node"]} is not created on NetBox. Exiting.')
            sys.exit(1)
        else:
            nb_device.status = 'active' if pve_node['status'] == 'online' else 'offline'
            nb_device.save()

        # Process Proxmox virtual machines per node
        for pve_virtual_machine in pve_api.nodes(pve_node['node']).qemu.get():
            _process_pve_virtual_machine(
                pve_api,
                nb_api,
                nb_objects,
                nb_device,
                pve_vm_tags.get(pve_virtual_machine['vmid'], []),
                pve_virtual_machine,
                pve_virtual_machine['vmid'] in pve_replicated_virtual_machine_ids,
                pve_virtual_machine['vmid'] in pve_ha_virtual_machine_ids,
            )


def _print_multi_source_result(result):
    for source_result in result.results:
        if source_result.success:
            print(f'SOURCE {source_result.source_id} SUCCESS')
        else:
            print(
                f'SOURCE {source_result.source_id} FAILED '
                f'{source_result.error_type}: '
                f'{source_result.error_summary}'
            )
        if source_result.history_error_code:
            print(
                f'SOURCE {source_result.source_id} HISTORY '
                f'{source_result.history_status.value} '
                f'{source_result.history_error_code}'
            )
    print()
    print('MULTI-SOURCE SUMMARY')
    print(f'total={result.total}')
    print(f'succeeded={result.succeeded}')
    print(f'failed={result.failed}')
    print(f'history_failures={result.history_failures}')


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
    """NetBox Sync main entrypoint."""

    sync_mode = _get_sync_mode()
    print(f'SYNC_MODE={sync_mode}')
    source_mode = runtime_source_mode(os.environ)
    if source_mode == REGISTRY_ALL_MODE:
        from .scheduler_runtime import (run_scheduler_tick,  # pylint: disable=import-outside-toplevel
                                        scheduler_summary_lines)
        from .source_bootstrap import load_scheduler_source_configs  # pylint: disable=import-outside-toplevel
        from .application.scheduling import stale_threshold  # pylint: disable=import-outside-toplevel
        configs = load_scheduler_source_configs()
        dispatch = _source_dispatch(sync_mode)
        history = postgres_run_repository(
            (os.environ.get('NETBOX_SYNC_RUN_WRITER_DSN', '') if sync_mode == 'apply'
             else os.environ.get('NETBOX_SYNC_REGISTRY_DSN', '')),
            os.environ['NETBOX_SYNC_REGISTRY_SCHEMA'],
        )
        tick = run_scheduler_tick(
            configs, dispatch.execute, history,
            stale_seconds=stale_threshold(
                os.environ.get('NETBOX_SYNC_DIAGNOSTICS_STALE_SECONDS', '7200')),
            execute_due=sync_mode == 'apply',
        )
        result = tick.execution
        _print_multi_source_result(result)
        for line in scheduler_summary_lines(tick):
            print(line)
        if tick.failed:
            raise SystemExit(1)
        return

    source_config = load_runtime_source_config()
    if source_mode == LEGACY_MODE:
        execute_proxmox_source(
            source_config,
            sync_mode,
            legacy_secrets=True,
        )
        return
    _source_dispatch(sync_mode).execute(source_config)


if __name__ == '__main__':
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    main()
