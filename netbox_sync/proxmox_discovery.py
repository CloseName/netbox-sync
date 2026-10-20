"""Map Proxmox VE API inventory into provider-neutral discovery models."""

from .proxmox_components import qemu_interfaces, qemu_disks, lxc_interfaces, lxc_disks


import logging
import re
from .hardware_identity import collect_proxmox

from .discovery import (
    DiscoveredCPU,
    DiscoveredHost,
    DiscoveredStorage,
    DiscoveredHostInterface,
    DiscoveredInterface,
    DiscoveredVirtualDisk,
    DiscoveredVirtualMachine,
    DiscoveredContainer,
)


LOGGER = logging.getLogger(__name__)


def _validated_vmid(value):
    """Return one positive unambiguous Proxmox VMID."""

    if isinstance(value, bool):
        raise ValueError("Proxmox VMID must be a positive integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value):
        result = int(value)
    else:
        raise ValueError("Proxmox VMID must be a positive integer")
    if result <= 0:
        raise ValueError("Proxmox VMID must be a positive integer")
    return result


def _workload_status(value):
    """Map provider status into the closed shared status vocabulary."""

    return {
        "running": "running",
        "stopped": "stopped",
        "paused": "paused",
        "suspended": "paused",
    }.get(str(value), "stopped")


def _config_flag(value):
    """Normalize the bounded boolean forms returned by Proxmox config."""

    return value is True or str(value).strip().lower() in {"1", "true", "on"}


def _warn_malformed(kind, source_config):
    LOGGER.warning(
        "Ignoring malformed Proxmox %s during discovery",
        kind,
        extra={"source_instance": source_config.source_instance},
    )


def _discover_host_interfaces(pve_api, node_name, rows=None):
    discovered = []

    for raw in pve_api.nodes(node_name).network.get() if rows is None else rows:
        name = raw.get("iface")

        if not name:
            continue

        addresses = []

        cidr = raw.get("cidr")
        address = raw.get("address")
        netmask = raw.get("netmask")

        if cidr:
            addresses.append(str(cidr))
        elif address:
            if netmask:
                addresses.append(f"{address}/{netmask}")
            else:
                addresses.append(str(address))

        vlan_id = None

        if raw.get("type") == "vlan":
            try:
                vlan_id = int(name.rsplit(".", 1)[1])
            except (IndexError, ValueError):
                pass

        bridge_ports = [value for value in str(raw.get("bridge_ports") or "").split() if value]

        discovered.append(
            DiscoveredHostInterface(
                name=name,
                interface_type=raw.get("type"),
                active=_config_flag(raw.get("active", 0)),
                autostart=_config_flag(raw.get("autostart", 0)),
                method=raw.get("method"),
                addresses=addresses,
                gateway=raw.get("gateway"),
                bridge_ports=bridge_ports,
                vlan_id=vlan_id,
                vlan_aware=_config_flag(raw.get("bridge_vlan_aware", 0)),
                comments=(str(raw.get("comments")).strip() if raw.get("comments") else None),
            )
        )

    return discovered


def _node_addresses(cluster_status):
    """Index named cluster nodes in provider order, retaining the last address."""
    node_ips = {}

    for item in cluster_status:
        if item.get("type") != "node":
            continue

        node_name = item.get("name")

        if node_name:
            node_ips[node_name] = item.get("ip")

    return node_ips


def _host_resources(status):
    """Build the CPU projection with the original numeric coercions."""
    cpu_info = status.get("cpuinfo", {})
    memory = status.get("memory", {})

    cpu = DiscoveredCPU(
        model=cpu_info.get("model"),
        vendor=cpu_info.get("vendor"),
        sockets=int(cpu_info.get("sockets", 0)),
        cores=int(cpu_info.get("cores", 0)),
        logical_cpus=int(cpu_info.get("cpus", 0)),
    )

    return cpu, memory


def _host_storages(pve_api, node_name):
    """Read and project node storage before network and guest discovery."""
    storages = []

    for storage in pve_api.nodes(node_name).storage.get():
        storages.append(
            DiscoveredStorage(
                name=storage["storage"],
                storage_type=storage.get("type"),
                content=storage.get("content"),
                total_bytes=int(storage.get("total", 0)),
                used_bytes=int(storage.get("used", 0)),
                available_bytes=int(storage.get("avail", 0)),
                active=bool(storage.get("active")),
            )
        )

    return storages


def discover_hosts(pve_api, source_config) -> list[DiscoveredHost]:
    """Collect Proxmox nodes, resources and separate VM/LXC inventories with host topology."""

    cluster_status = pve_api.cluster.status.get()

    node_ips = _node_addresses(cluster_status)

    hosts = []

    for node in pve_api.nodes.get():
        node_name = node["node"]

        status = pve_api.nodes(node_name).status.get()
        cpu, memory = _host_resources(status)

        storages = _host_storages(pve_api, node_name)

        pve_version = status.get("pveversion")

        if pve_version and pve_version.startswith("pve-manager/"):
            pve_version = pve_version.split("/", 2)[1]

        from .proxmox_host_network import snapshot

        network_rows = pve_api.nodes(node_name).network.get()

        hosts.append(
            DiscoveredHost(
                source="proxmox",
                source_instance=(source_config.source_instance),
                legacy_identity_owner=(source_config.legacy_identity_owner),
                source_id=node_name,
                original_name=node_name,
                normalized_name=node_name.upper(),
                management_ip=node_ips.get(node_name),
                hypervisor="Proxmox VE",
                hardware_identity=collect_proxmox(),
                hypervisor_version=pve_version,
                cpu=cpu,
                memory_bytes=int(memory.get("total", 0)),
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
                interfaces=_discover_host_interfaces(pve_api, node_name, network_rows),
            )
        )
        host = hosts[-1]
        host.proxmox_host_network = snapshot(
            network_rows,
            guest_bridges=[
                nic.bridge
                for guest in [*host.virtual_machines, *host.containers]
                for nic in guest.interfaces
                if nic.bridge
            ],
        )

    return hosts


def _parse_config_definition(raw_value: str) -> dict:
    result = {}

    for component in str(raw_value).split(","):
        if "=" in component:
            key, value = component.split("=", 1)
            result[key] = value
        elif ":" in component and "storage" not in result:
            storage, value = component.split(":", 1)
            result["storage"] = storage
            result["volume"] = value

    return result


def _parse_size_bytes(raw_size: str) -> int:
    if not raw_size:
        return 0

    raw_size = str(raw_size).strip().upper()

    units = {
        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
        "T": 1024**4,
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

    discovered_vms = []

    for vm in pve_api.nodes(node_name).qemu.get():
        try:
            vmid = _validated_vmid(vm.get("vmid"))
            config = pve_api.nodes(node_name).qemu(vmid).config.get()
            if not isinstance(config, dict):
                raise ValueError("Proxmox QEMU config must be an object")
            sockets = int(config.get("sockets", 1))
            cores = int(config.get("cores", 1))
            vcpus = int(config.get("vcpus", sockets * cores))
            memory_mib = int(config.get("memory", 0))
            if min(sockets, cores, vcpus, memory_mib) < 0:
                raise ValueError("Proxmox QEMU resources cannot be negative")
        except (AttributeError, KeyError, TypeError, ValueError):
            _warn_malformed("QEMU VM", source_config)
            continue

        interfaces = qemu_interfaces(
            pve_api,
            node_name,
            vmid,
            config,
            source_config,
            ResourceException=ResourceException,
            DiscoveredInterface=DiscoveredInterface,
            _warn_malformed=_warn_malformed,
            _parse_config_definition=_parse_config_definition,
        )

        disks = qemu_disks(
            config,
            DiscoveredVirtualDisk=DiscoveredVirtualDisk,
            _parse_config_definition=_parse_config_definition,
            _parse_size_bytes=_parse_size_bytes,
        )

        original_name = str(vm.get("name", f"vm-{vmid}"))

        discovered_vms.append(
            DiscoveredVirtualMachine(
                source="proxmox",
                source_instance=(source_config.source_instance),
                legacy_identity_owner=(source_config.legacy_identity_owner),
                source_id=f"proxmox:{node_name}:{vmid}",
                description=config.get("description"),
                node_source_id=node_name,
                vmid=vmid,
                original_name=original_name,
                # Naming policy will be implemented separately.
                normalized_name=original_name,
                status=_workload_status(vm.get("status")),
                vcpus=vcpus,
                memory_bytes=memory_mib * 1024**2,
                autostart=_config_flag(config.get("onboot", 0)),
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
    discovered_containers = []

    for container in pve_api.nodes(node_name).lxc.get():
        try:
            vmid = _validated_vmid(container.get("vmid"))
            config = pve_api.nodes(node_name).lxc(vmid).config.get()
            if not isinstance(config, dict):
                raise ValueError("Proxmox LXC config must be an object")
            vcpus = int(config.get("cores", 1))
            memory_mib = int(config.get("memory", 0))
            swap_mib = int(config.get("swap", 0))
            if min(vcpus, memory_mib, swap_mib) < 0:
                raise ValueError("Proxmox LXC resources cannot be negative")
        except (AttributeError, KeyError, TypeError, ValueError):
            _warn_malformed("LXC container", source_config)
            continue

        interfaces = lxc_interfaces(
            config,
            source_config,
            DiscoveredInterface=DiscoveredInterface,
            _warn_malformed=_warn_malformed,
            _parse_config_definition=_parse_config_definition,
        )

        disks = lxc_disks(
            config,
            DiscoveredVirtualDisk=DiscoveredVirtualDisk,
            _parse_config_definition=_parse_config_definition,
            _parse_size_bytes=_parse_size_bytes,
        )

        original_name = str(config.get("hostname", container.get("name", f"lxc-{vmid}")))

        discovered_containers.append(
            DiscoveredContainer(
                source="proxmox",
                source_instance=(source_config.source_instance),
                legacy_identity_owner=(source_config.legacy_identity_owner),
                source_id=f"proxmox:{node_name}:lxc:{vmid}",
                node_source_id=node_name,
                vmid=vmid,
                original_name=original_name,
                normalized_name=original_name,
                status=_workload_status(container.get("status")),
                architecture=config.get("arch"),
                os_type=config.get("ostype"),
                vcpus=vcpus,
                memory_bytes=memory_mib * 1024**2,
                swap_bytes=swap_mib * 1024**2,
                autostart=_config_flag(config.get("onboot", 0)),
                unprivileged=_config_flag(config.get("unprivileged", 0)),
                disks=disks,
                interfaces=interfaces,
            )
        )

    return discovered_containers
