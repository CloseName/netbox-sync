"""Map Proxmox VE API inventory into provider-neutral discovery models."""

import logging
import re

from .discovery import (
    DiscoveredCPU,
    DiscoveredDisk,
    DiscoveredHost,
    DiscoveredStorage,
    DiscoveredHostInterface,
)


LOGGER = logging.getLogger(__name__)


def _validated_vmid(value):
    """Return one positive unambiguous Proxmox VMID."""

    if isinstance(value, bool):
        raise ValueError('Proxmox VMID must be a positive integer')
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and re.fullmatch(r'[1-9][0-9]*', value):
        result = int(value)
    else:
        raise ValueError('Proxmox VMID must be a positive integer')
    if result <= 0:
        raise ValueError('Proxmox VMID must be a positive integer')
    return result


def _workload_status(value):
    """Map provider status into the closed shared status vocabulary."""

    return {
        'running': 'running',
        'stopped': 'stopped',
        'paused': 'paused',
        'suspended': 'paused',
    }.get(str(value), 'stopped')


def _config_flag(value):
    """Normalize the bounded boolean forms returned by Proxmox config."""

    return value is True or str(value).strip().lower() in {'1', 'true', 'on'}


def _warn_malformed(kind, source_config):
    LOGGER.warning(
        'Ignoring malformed Proxmox %s during discovery',
        kind,
        extra={'source_instance': source_config.source_instance},
    )



def _discover_host_interfaces(pve_api, node_name):
    discovered = []

    for raw in pve_api.nodes(node_name).network.get():
        name = raw.get('iface')

        if not name:
            continue

        addresses = []

        cidr = raw.get('cidr')
        address = raw.get('address')
        netmask = raw.get('netmask')

        if cidr:
            addresses.append(str(cidr))
        elif address:
            if netmask:
                addresses.append(f'{address}/{netmask}')
            else:
                addresses.append(str(address))

        vlan_id = None

        if raw.get('type') == 'vlan':
            try:
                vlan_id = int(name.rsplit('.', 1)[1])
            except (IndexError, ValueError):
                pass

        bridge_ports = [
            value
            for value in str(
                raw.get('bridge_ports') or ''
            ).split()
            if value
        ]

        discovered.append(
            DiscoveredHostInterface(
                name=name,
                interface_type=raw.get('type'),
                active=_config_flag(raw.get('active', 0)),
                autostart=_config_flag(raw.get('autostart', 0)),
                method=raw.get('method'),
                addresses=addresses,
                gateway=raw.get('gateway'),
                bridge_ports=bridge_ports,
                vlan_id=vlan_id,
                vlan_aware=_config_flag(raw.get('bridge_vlan_aware', 0)),
                comments=(
                    str(raw.get('comments')).strip()
                    if raw.get('comments')
                    else None
                ),
            )
        )

    return discovered

def discover_hosts(pve_api, source_config) -> list[DiscoveredHost]:
    cluster_status = pve_api.cluster.status.get()

    node_ips = {}

    for item in cluster_status:
        if item.get('type') != 'node':
            continue

        node_name = item.get('name')

        if node_name:
            node_ips[node_name] = item.get('ip')

    hosts = []

    for node in pve_api.nodes.get():
        node_name = node['node']

        status = pve_api.nodes(node_name).status.get()
        cpu_info = status.get('cpuinfo', {})
        memory = status.get('memory', {})

        cpu = DiscoveredCPU(
            model=cpu_info.get('model'),
            vendor=cpu_info.get('vendor'),
            sockets=int(cpu_info.get('sockets', 0)),
            cores=int(cpu_info.get('cores', 0)),
            logical_cpus=int(cpu_info.get('cpus', 0)),
        )

        disks = []

        for disk in pve_api.nodes(node_name).disks.list.get():
            disks.append(
                DiscoveredDisk(
                    path=disk.get('devpath', disk.get('path', '')),
                    model=disk.get('model'),
                    serial=disk.get('serial'),
                    size_bytes=int(disk.get('size', 0)),
                    disk_type=disk.get('type'),
                    health=disk.get('health'),
                )
            )

        storages = []

        for storage in pve_api.nodes(node_name).storage.get():
            storages.append(
                DiscoveredStorage(
                    name=storage['storage'],
                    storage_type=storage.get('type'),
                    content=storage.get('content'),
                    total_bytes=int(storage.get('total', 0)),
                    used_bytes=int(storage.get('used', 0)),
                    available_bytes=int(storage.get('avail', 0)),
                    active=bool(storage.get('active')),
                )
            )

        pve_version = status.get('pveversion')

        if pve_version and pve_version.startswith('pve-manager/'):
            pve_version = pve_version.split('/', 2)[1]

        hosts.append(
            DiscoveredHost(
                source='proxmox',
                source_instance=(
                    source_config.source_instance
                ),
                legacy_identity_owner=(
                    source_config.legacy_identity_owner
                ),
                source_id=node_name,
                original_name=node_name,
                normalized_name=node_name.upper(),
                management_ip=node_ips.get(node_name),
                hypervisor='Proxmox VE',
                hypervisor_version=pve_version,
                cpu=cpu,
                memory_bytes=int(memory.get('total', 0)),
                disks=disks,
                storages=storages,
                virtual_machines=_discover_virtual_machines(
                    pve_api,
                    node_name,
                    source_config,
                ),
                containers=_discover_containers(
                    pve_api,
                    node_name,
                    source_config,
                ),
                interfaces=_discover_host_interfaces(pve_api, node_name),
            )
        )

    return hosts


def _parse_config_definition(raw_value: str) -> dict:
    result = {}

    for component in str(raw_value).split(','):
        if '=' in component:
            key, value = component.split('=', 1)
            result[key] = value
        elif ':' in component and 'storage' not in result:
            storage, value = component.split(':', 1)
            result['storage'] = storage
            result['volume'] = value

    return result


def _parse_size_bytes(raw_size: str) -> int:
    if not raw_size:
        return 0

    raw_size = str(raw_size).strip().upper()

    units = {
        'K': 1024,
        'M': 1024 ** 2,
        'G': 1024 ** 3,
        'T': 1024 ** 4,
    }

    suffix = raw_size[-1]

    try:
        if suffix in units:
            return int(float(raw_size[:-1]) * units[suffix])

        return int(raw_size)
    except ValueError:
        return 0


def _discover_virtual_machines(
        pve_api,
        node_name: str,
        source_config,
):
    from proxmoxer import ResourceException

    from .discovery import (
        DiscoveredInterface,
        DiscoveredVirtualDisk,
        DiscoveredVirtualMachine,
    )

    discovered_vms = []

    for vm in pve_api.nodes(node_name).qemu.get():
        try:
            vmid = _validated_vmid(vm.get('vmid'))
            config = pve_api.nodes(node_name).qemu(vmid).config.get()
            if not isinstance(config, dict):
                raise ValueError('Proxmox QEMU config must be an object')
            sockets = int(config.get('sockets', 1))
            cores = int(config.get('cores', 1))
            vcpus = int(config.get('vcpus', sockets * cores))
            memory_mib = int(config.get('memory', 0))
            if min(sockets, cores, vcpus, memory_mib) < 0:
                raise ValueError('Proxmox QEMU resources cannot be negative')
        except (AttributeError, KeyError, TypeError, ValueError):
            _warn_malformed('QEMU VM', source_config)
            continue

        interfaces = []

        agent_by_mac = {}

        try:
            agent_result = (
                pve_api.nodes(node_name)
                .qemu(vmid)
                .agent('network-get-interfaces')
                .get()
            )

            if not isinstance(agent_result, dict):
                raise ValueError('QEMU guest agent response must be an object')
            for agent_interface in agent_result.get('result', []):
                if not isinstance(agent_interface, dict):
                    continue
                mac = str(
                    agent_interface.get('hardware-address', '')
                ).lower()

                if not mac:
                    continue

                ips = []

                for ip in agent_interface.get('ip-addresses', []):
                    address = ip.get('ip-address')
                    prefix = ip.get('prefix')

                    if not address:
                        continue

                    if ':' in address:
                        continue

                    if address.startswith('127.'):
                        continue

                    if prefix is not None:
                        ips.append(f'{address}/{prefix}')
                    else:
                        ips.append(address)

                agent_by_mac[mac] = ips

        except (ResourceException, AttributeError, TypeError, ValueError):
            pass

        for key, raw_value in config.items():
            key = str(key)
            if not re.fullmatch(r'net[0-9]+', key):
                continue
            if not isinstance(raw_value, str) or not raw_value.strip():
                _warn_malformed('QEMU NIC', source_config)
                continue

            definition = _parse_config_definition(raw_value)

            mac = None

            for model in ('virtio', 'e1000', 'e1000e', 'rtl8139', 'vmxnet3'):
                if model in definition:
                    mac = definition[model]
                    break

            vlan_id = None
            if definition.get('tag') not in (None, ''):
                try:
                    vlan_id = int(definition['tag'])
                except ValueError:
                    pass

            interfaces.append(
                DiscoveredInterface(
                    name=key,
                    mac_address=mac,
                    bridge=definition.get('bridge'),
                    vlan_id=vlan_id,
                    ip_addresses=agent_by_mac.get(
                        str(mac).lower(), []
                    ) if mac else [],
                    external_id=key,
                )
            )

        disks = []

        for key, raw_value in config.items():
            key = str(key)

            if not key.startswith(
                ('scsi', 'virtio', 'sata', 'ide')
            ):
                continue

            if key in ('scsihw',):
                continue

            definition = _parse_config_definition(raw_value)

            # ISO/CD-ROM devices are not VM disks.
            if definition.get('media') == 'cdrom':
                continue

            if str(raw_value).strip().lower() == 'none':
                continue

            size_bytes = _parse_size_bytes(
                definition.get('size', '')
            )

            storage = definition.get('storage')

            if storage is None:
                raw_first = str(raw_value).split(',', 1)[0]
                if ':' in raw_first:
                    storage = raw_first.split(':', 1)[0]

            disks.append(
                DiscoveredVirtualDisk(
                    name=key,
                    storage=storage,
                    size_bytes=size_bytes,
                )
            )

        original_name = str(
            vm.get('name', f'vm-{vmid}')
        )

        discovered_vms.append(
            DiscoveredVirtualMachine(
                source='proxmox',
                source_instance=(
                    source_config.source_instance
                ),
                legacy_identity_owner=(
                    source_config.legacy_identity_owner
                ),
                source_id=f'proxmox:{node_name}:{vmid}',
                description=config.get('description'),
                node_source_id=node_name,
                vmid=vmid,
                original_name=original_name,

                # Naming policy will be implemented separately.
                normalized_name=original_name,

                status=_workload_status(vm.get('status')),
                vcpus=vcpus,
                memory_bytes=memory_mib * 1024 ** 2,
                autostart=_config_flag(config.get('onboot', 0)),
                disks=disks,
                interfaces=interfaces,
            )
        )

    return discovered_vms


def _discover_containers(
        pve_api,
        node_name: str,
        source_config,
):
    from .discovery import (
        DiscoveredContainer,
        DiscoveredInterface,
        DiscoveredVirtualDisk,
    )

    discovered_containers = []

    for container in pve_api.nodes(node_name).lxc.get():
        try:
            vmid = _validated_vmid(container.get('vmid'))
            config = (
                pve_api.nodes(node_name)
                .lxc(vmid)
                .config.get()
            )
            if not isinstance(config, dict):
                raise ValueError('Proxmox LXC config must be an object')
            vcpus = int(config.get('cores', 1))
            memory_mib = int(config.get('memory', 0))
            swap_mib = int(config.get('swap', 0))
            if min(vcpus, memory_mib, swap_mib) < 0:
                raise ValueError('Proxmox LXC resources cannot be negative')
        except (AttributeError, KeyError, TypeError, ValueError):
            _warn_malformed('LXC container', source_config)
            continue

        interfaces = []

        for key, raw_value in config.items():
            key = str(key)

            if not re.fullmatch(r'net[0-9]+', key):
                continue
            if not isinstance(raw_value, str) or not raw_value.strip():
                _warn_malformed('LXC NIC', source_config)
                continue

            definition = _parse_config_definition(raw_value)

            vlan_id = None

            if definition.get('tag') not in (None, ''):
                try:
                    vlan_id = int(definition['tag'])
                except ValueError:
                    pass

            ip_addresses = []

            raw_ip = definition.get('ip')

            if raw_ip and raw_ip.lower() not in ('dhcp', 'manual'):
                ip_addresses.append(raw_ip)

            interfaces.append(
                DiscoveredInterface(
                    name=definition.get('name', key),
                    mac_address=definition.get('hwaddr'),
                    bridge=definition.get('bridge'),
                    vlan_id=vlan_id,
                    ip_addresses=ip_addresses,
                    external_id=key,
                )
            )

        disks = []

        for key, raw_value in config.items():
            key = str(key)

            if key != 'rootfs' and not key.startswith('mp'):
                continue

            definition = _parse_config_definition(raw_value)

            storage = definition.get('storage')

            if storage is None:
                first_component = str(raw_value).split(',', 1)[0]

                if ':' in first_component:
                    storage = first_component.split(':', 1)[0]

            disks.append(
                DiscoveredVirtualDisk(
                    name=key,
                    storage=storage,
                    size_bytes=_parse_size_bytes(
                        definition.get('size', '')
                    ),
                )
            )

        original_name = str(
            config.get(
                'hostname',
                container.get('name', f'lxc-{vmid}')
            )
        )

        discovered_containers.append(
            DiscoveredContainer(
                source='proxmox',
                source_instance=(
                    source_config.source_instance
                ),
                legacy_identity_owner=(
                    source_config.legacy_identity_owner
                ),
                source_id=f'proxmox:{node_name}:lxc:{vmid}',
                node_source_id=node_name,

                vmid=vmid,
                original_name=original_name,
                normalized_name=original_name,

                status=_workload_status(container.get('status')),
                architecture=config.get('arch'),
                os_type=config.get('ostype'),

                vcpus=vcpus,
                memory_bytes=memory_mib * 1024 ** 2,
                swap_bytes=swap_mib * 1024 ** 2,

                autostart=_config_flag(config.get('onboot', 0)),

                unprivileged=_config_flag(config.get('unprivileged', 0)),

                disks=disks,
                interfaces=interfaces,
            )
        )

    return discovered_containers
