"""Map standalone ESXi API inventory into generic discovery models."""

import logging
import re
from uuid import UUID

from .discovery import (
    DiscoveredCPU,
    DiscoveredDisk,
    DiscoveredHost,
    DiscoveredHostInterface,
    DiscoveredInterface,
    DiscoveredStorage,
    DiscoveredVirtualDisk,
    DiscoveredVirtualMachine,
)


def _value(obj, path, default=None):
    current = obj
    for component in path.split('.'):
        if current is None:
            return default
        current = getattr(current, component, None)
    return default if current is None else current


def _items(value):
    return tuple(value or ())


LOGGER = logging.getLogger(__name__)


def _normalized_uuid(value):
    """Return one canonical non-zero UUID or ``None`` for unusable input."""

    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    if candidate.startswith('{') and candidate.endswith('}'):
        candidate = candidate[1:-1]
    compact = candidate.replace('-', '').replace(' ', '')
    if not re.fullmatch(r'[0-9A-Fa-f]{32}', compact):
        return None
    try:
        parsed = UUID(hex=compact)
    except (AttributeError, TypeError, ValueError):
        return None
    if parsed.int == 0:
        return None
    return str(parsed)


def _managed_object_id(obj):
    value = getattr(obj, '_moId', None)
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate or candidate.casefold() == 'none':
        return None
    return candidate


def _vm_external_id(vm):
    """Use instance UUID, then BIOS UUID, then the managed-object ID."""

    for path in ('config.instanceUuid', 'summary.config.instanceUuid', 'config.uuid'):
        candidate = _normalized_uuid(_value(vm, path))
        if candidate is not None:
            return candidate
    managed_id = _managed_object_id(vm)
    if managed_id is not None:
        return managed_id
    raise ValueError('ESXi VM has no usable stable external identifier')


def _validated_host_hardware_uuid(value):
    candidate = _normalized_uuid(value)
    if candidate is None:
        return None
    parsed = UUID(candidate)
    if sum(byte != 0 for byte in parsed.bytes) < len(parsed.bytes) // 2:
        return None
    return candidate


def _host_external_id(host):
    for path in ('hardware.systemInfo.uuid', 'summary.hardware.uuid'):
        candidate = _validated_host_hardware_uuid(_value(host, path))
        if candidate is not None:
            return candidate
    managed_id = _managed_object_id(host)
    if managed_id is not None:
        return managed_id
    raise ValueError('ESXi host has no usable stable external identifier')


def _management_ip(host):
    vnics = _items(_value(host, 'config.network.vnic', ()))
    for vnic in vnics:
        address = _value(vnic, 'spec.ip.ipAddress')
        if address:
            return str(address)
    return None


def _management_pnic_names(host):
    management_ip = _management_ip(host)
    portgroup_names = {
        str(
            getattr(vnic, 'portgroup', None)
            or _value(vnic, 'spec.portgroup', '')
        )
        for vnic in _items(_value(host, 'config.network.vnic', ()))
        if _value(vnic, 'spec.ip.ipAddress') == management_ip
    }
    vswitch_names = {
        str(_value(portgroup, 'spec.vswitchName'))
        for portgroup in _items(_value(host, 'config.network.portgroup', ()))
        if str(_value(portgroup, 'spec.name', '')) in portgroup_names
    }
    pnic_keys = {
        str(key)
        for vswitch in _items(_value(host, 'config.network.vswitch', ()))
        if str(getattr(vswitch, 'name', '')) in vswitch_names
        for key in _items(getattr(vswitch, 'pnic', ()))
    }
    return {
        str(getattr(pnic, 'device', ''))
        for pnic in _items(_value(host, 'config.network.pnic', ()))
        if (
            str(getattr(pnic, 'key', '')) in pnic_keys
            or str(getattr(pnic, 'device', '')) in pnic_keys
        )
    }


def _host_interfaces(host):
    result = []
    management_pnics = _management_pnic_names(host)
    for pnic in _items(_value(host, 'config.network.pnic', ())):
        name = getattr(pnic, 'device', None)
        if not name:
            continue
        result.append(
            DiscoveredHostInterface(
                name=str(name),
                interface_type='physical',
                active=getattr(pnic, 'linkSpeed', None) is not None,
                comments=(
                    f'MAC {pnic.mac}'
                    if getattr(pnic, 'mac', None)
                    else None
                ),
                mac_address=getattr(pnic, 'mac', None),
                management=str(name) in management_pnics,
            )
        )
    return result


def _host_disks(host):
    result = []
    for lun in _items(_value(host, 'config.storageDevice.scsiLun', ())):
        capacity = getattr(lun, 'capacity', None)
        blocks = int(getattr(capacity, 'block', 0) or 0)
        block_size = int(getattr(capacity, 'blockSize', 0) or 0)
        operational = getattr(lun, 'operationalState', None)
        result.append(
            DiscoveredDisk(
                path=str(
                    getattr(lun, 'deviceName', None)
                    or getattr(lun, 'canonicalName', '')
                ),
                model=getattr(lun, 'model', None),
                serial=getattr(lun, 'serialNumber', None),
                size_bytes=blocks * block_size,
                disk_type=getattr(lun, 'deviceType', None),
                health=(
                    ','.join(str(item) for item in operational)
                    if operational
                    else None
                ),
            )
        )
    return result


def _datastores(host):
    result = []
    for datastore in _items(getattr(host, 'datastore', ())):
        summary = getattr(datastore, 'summary', None)
        total = int(getattr(summary, 'capacity', 0) or 0)
        available = int(getattr(summary, 'freeSpace', 0) or 0)
        result.append(
            DiscoveredStorage(
                name=str(
                    getattr(summary, 'name', None)
                    or getattr(datastore, 'name', '')
                ),
                storage_type=getattr(summary, 'type', None),
                content='virtual-machines',
                total_bytes=total,
                used_bytes=max(total - available, 0),
                available_bytes=available,
                active=bool(getattr(summary, 'accessible', False)),
            )
        )
    return result


def _portgroups(host):
    result = {}
    for portgroup in _items(_value(host, 'config.network.portgroup', ())):
        name = _value(portgroup, 'spec.name')
        if name:
            result[str(name)] = _value(portgroup, 'spec.vlanId')
    return result


def _guest_addresses(vm):
    by_key = {}
    by_mac = {}
    for network in _items(_value(vm, 'guest.net', ())):
        addresses = []
        configured = _items(_value(network, 'ipConfig.ipAddress', ()))
        if configured:
            for item in configured:
                address = getattr(item, 'ipAddress', None)
                prefix = getattr(item, 'prefixLength', None)
                if address:
                    addresses.append(
                        f'{address}/{prefix}' if prefix is not None else str(address)
                    )
        else:
            addresses.extend(str(item) for item in _items(
                getattr(network, 'ipAddress', ())
            ))
        key = getattr(network, 'deviceConfigId', None)
        mac = getattr(network, 'macAddress', None)
        if key is not None:
            by_key[str(key)] = addresses
        if mac:
            by_mac[str(mac).casefold()] = addresses
    return by_key, by_mac


def _vm_disks_and_interfaces(vm, host):
    disks = []
    interfaces = []
    addresses_by_key, addresses_by_mac = _guest_addresses(vm)
    portgroups = _portgroups(host)
    nic_keys = set()
    for device in _items(_value(vm, 'config.hardware.device', ())):
        label = str(_value(device, 'deviceInfo.label', ''))
        key = getattr(device, 'key', None)
        if hasattr(device, 'capacityInKB'):
            datastore = _value(device, 'backing.datastore.name')
            disks.append(
                DiscoveredVirtualDisk(
                    name=label or f'disk-{key}',
                    storage=str(datastore) if datastore else None,
                    size_bytes=int(getattr(device, 'capacityInKB', 0) or 0) * 1024,
                )
            )
            continue
        mac = getattr(device, 'macAddress', None)
        if not mac:
            continue
        network = _value(device, 'backing.deviceName')
        network_name = str(network) if network else None
        if key is None:
            raise ValueError('ESXi VM NIC has no stable device key')
        external_id = str(key).strip()
        if not external_id or external_id.casefold() == 'none':
            raise ValueError('ESXi VM NIC has no stable device key')
        if external_id in nic_keys:
            raise ValueError('ESXi VM has duplicate NIC device keys')
        nic_keys.add(external_id)
        interfaces.append(
            DiscoveredInterface(
                name=label or f'nic-{external_id}',
                mac_address=str(mac),
                bridge=network_name,
                vlan_id=portgroups.get(network_name),
                ip_addresses=(
                    addresses_by_key.get(external_id)
                    or addresses_by_mac.get(str(mac).casefold())
                    or []
                ),
                external_id=external_id,
            )
        )
    return disks, interfaces


def _vm_autostart(vm, host):
    for item in _items(_value(host, 'config.autoStart.powerInfo', ())):
        if getattr(item, 'key', None) == vm:
            return getattr(item, 'startAction', None) not in (None, 'none')
    return False


def _power_status(value):
    """Map VMware power states into the closed shared status vocabulary."""

    return {
        'poweredOn': 'running',
        'poweredOff': 'stopped',
        'suspended': 'paused',
    }.get(str(value), 'stopped')


def _virtual_machine(vm, host, source_config, host_id):
    external_id = _vm_external_id(vm)
    name = str(getattr(vm, 'name', None) or _value(vm, 'config.name', external_id))
    disks, interfaces = _vm_disks_and_interfaces(vm, host)
    power_state = _value(vm, 'runtime.powerState', '')
    return DiscoveredVirtualMachine(
        source='esxi',
        source_instance=source_config.source_instance,
        legacy_identity_owner=False,
        source_id=f'esxi:{external_id}',
        node_source_id=host_id,
        vmid=external_id,
        external_id=external_id,
        original_name=name,
        normalized_name=name.upper(),
        status=_power_status(power_state),
        vcpus=int(_value(vm, 'config.hardware.numCPU', 0) or 0),
        memory_bytes=int(
            _value(vm, 'config.hardware.memoryMB', 0) or 0
        ) * 1024 * 1024,
        autostart=_vm_autostart(vm, host),
        disks=disks,
        interfaces=interfaces,
    )


def _virtual_machines(host, source_config, host_id):
    result = []
    for vm in _items(getattr(host, 'vm', ())):
        try:
            result.append(_virtual_machine(vm, host, source_config, host_id))
        except (AttributeError, TypeError, ValueError):
            # A malformed object is retained in NetBox by the global no-delete
            # policy. Do not let one bad SDK object hide the rest of the host.
            LOGGER.warning(
                'Ignoring malformed ESXi VM during discovery',
                extra={'source_instance': source_config.source_instance},
            )
    return result


def _walk_hosts(entity, seen=None):
    if entity is None:
        return
    if seen is None:
        seen = set()

    managed_id = getattr(entity, '_moId', None)
    entity_key = (
        ('managed-object', str(managed_id))
        if managed_id
        else ('python-object', id(entity))
    )
    if entity_key in seen:
        return
    seen.add(entity_key)

    if hasattr(entity, 'vm') and hasattr(entity, 'hardware'):
        yield entity
        return

    host_folder = getattr(entity, 'hostFolder', None)
    if host_folder is not None:
        yield from _walk_hosts(host_folder, seen)
    for host in _items(getattr(entity, 'host', ())):
        yield from _walk_hosts(host, seen)
    for child in _items(getattr(entity, 'childEntity', ())):
        yield from _walk_hosts(child, seen)


def discover_hosts(service_instance, source_config):
    """Discover standalone ESXi hosts and VMs without leaking SDK objects."""

    content = service_instance.RetrieveContent()
    root = getattr(content, 'rootFolder', content)
    result = []
    for host in _walk_hosts(root):
        host_id = _host_external_id(host)
        name = str(getattr(host, 'name', host_id))
        product = _value(host, 'summary.config.product')
        version = getattr(product, 'version', None)
        build = getattr(product, 'build', None)
        if version and build:
            version = f'{version} build-{build}'
        cpu_packages = _items(_value(host, 'hardware.cpuPkg', ()))
        first_cpu = cpu_packages[0] if cpu_packages else None
        cpu_info = _value(host, 'hardware.cpuInfo')
        result.append(
            DiscoveredHost(
                source='esxi',
                source_instance=source_config.source_instance,
                legacy_identity_owner=False,
                source_id=host_id,
                original_name=name,
                normalized_name=name.upper(),
                management_ip=_management_ip(host),
                hypervisor='VMware ESXi',
                hypervisor_version=version,
                manufacturer=_value(host, 'hardware.systemInfo.vendor', _value(host, 'summary.hardware.vendor')),
                model=_value(host, 'hardware.systemInfo.model', _value(host, 'summary.hardware.model')),
                cpu=DiscoveredCPU(
                    model=getattr(first_cpu, 'description', None),
                    vendor=getattr(first_cpu, 'vendor', None),
                    sockets=int(getattr(cpu_info, 'numCpuPackages', 0) or 0),
                    cores=int(getattr(cpu_info, 'numCpuCores', 0) or 0),
                    logical_cpus=int(getattr(cpu_info, 'numCpuThreads', 0) or 0),
                ),
                memory_bytes=int(_value(host, 'hardware.memorySize', 0) or 0),
                disks=_host_disks(host),
                storages=_datastores(host),
                interfaces=_host_interfaces(host),
                virtual_machines=_virtual_machines(host, source_config, host_id),
                containers=[],
            )
        )
    if not result:
        raise RuntimeError('ESXi inventory contains no hosts')
    return result
